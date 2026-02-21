"""Despacha sub-tareas a backends según config (v1 y v2).

v2: model-centric dispatch with retry + transport fallback.
v1: legacy backend-centric dispatch (preserved for backward compat).
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import io
import sys
import time
from pathlib import Path

from .config import EngineConfig, get_step_config, ModelTransport
from .prompt_builder import build_prompt, build_fusion_prompt, build_filing_prompt, _normalize_backend_output
from .validator import validate_artifact
from .step_contracts import get_allowed_schemas
from .backends.base import DispatchResult, LLMBackend, _try_recover_json
from .backends.codex import CodexBackend
from .backends.gemini import GeminiBackend
from .backends.claude import ClaudeBackend
from .backends.copilot import CopilotBackend

BACKEND_CLASSES = {
    "codex":          CodexBackend,
    "gemini":         GeminiBackend,
    "claude":         ClaudeBackend,
    "copilot":        CopilotBackend,
    "copilot_gemini": CopilotBackend,  # v1 compat
}

# Also used by v2 for transport→class resolution
TRANSPORT_CLASSES = {
    "codex":   CodexBackend,
    "gemini":  GeminiBackend,
    "claude":  ClaudeBackend,
    "copilot": CopilotBackend,
}

_RELAXED_DETECTION_SHAPES: dict[str, dict[str, type]] = {
    "CATALYST_DETECTION": {
        "caso_id": str,
        "fecha_corte": str,
        "claims_list": list,
        "catalyst_candidates": list,
    },
    "FORENSIC_DETECTION": {
        "caso_id": str,
        "fecha_corte": str,
        "red_flags": list,
        "liquidez": dict,
        "puentes": dict,
        "kill_criteria_candidatos": list,
    },
}


# ── Validation helpers (shared v1/v2) ────────────────────────


def _looks_like_transport_envelope(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if "result" in payload and ("modelUsage" in payload or "type" in payload):
        return "version_esquema" not in payload
    if "response" in payload and ("session_id" in payload or "stats" in payload):
        return "version_esquema" not in payload
    return False


def _validate_multi_candidate_strict_schema(
    config: EngineConfig, step_name: str, payload: dict | None,
) -> tuple[bool, str | None]:
    if not isinstance(payload, dict):
        return False, "output is not a JSON object"
    if not payload:
        return False, "output is an empty JSON object"
    if _looks_like_transport_envelope(payload):
        return False, "output appears to be backend envelope, not artifact payload"

    schema_names = get_allowed_schemas(step_name)
    if not schema_names:
        if len(payload.keys()) < 2:
            return False, "output does not look like a structured artifact"
        return True, None

    schemas_dir = config.get_path("schemas")
    schema_errors: list[str] = []
    for schema_name in schema_names:
        is_valid, errors = validate_artifact(payload, schema_name, schemas_dir)
        if is_valid:
            return True, None
        first_error = errors[0] if errors else "unknown validation error"
        schema_errors.append(f"{schema_name}: {first_error}")

    return False, "schema validation failed (" + " | ".join(schema_errors) + ")"


def _validate_multi_candidate_relaxed_detection(
    step_name: str, payload: dict | None,
) -> tuple[bool, str | None]:
    if not isinstance(payload, dict):
        return False, "output is not a JSON object"
    if not payload:
        return False, "output is an empty JSON object"
    if _looks_like_transport_envelope(payload):
        return False, "output appears to be backend envelope, not artifact payload"

    allowed = get_allowed_schemas(step_name)
    expected_schema = allowed[0] if allowed else None
    if expected_schema and payload.get("version_esquema") != expected_schema:
        got = payload.get("version_esquema")
        return False, f"version_esquema mismatch: expected {expected_schema}, got {got!r}"

    required_shape = _RELAXED_DETECTION_SHAPES.get(step_name, {})
    if not required_shape:
        return False, f"no relaxed shape configured for step {step_name}"

    for key, expected_type in required_shape.items():
        if key not in payload:
            return False, f"missing required field: {key}"
        if not isinstance(payload[key], expected_type):
            return False, (
                f"invalid type for {key}: expected {expected_type.__name__}, "
                f"got {type(payload[key]).__name__}"
            )
    return True, None


def _validate_multi_candidate(
    config: EngineConfig, step_name: str, payload: dict | None,
) -> tuple[bool, str | None]:
    if step_name in _RELAXED_DETECTION_SHAPES:
        return _validate_multi_candidate_relaxed_detection(step_name, payload)
    return _validate_multi_candidate_strict_schema(config, step_name, payload)


# ── v2: Transport instantiation ──────────────────────────────


def _instantiate_transport(transport: ModelTransport, config_raw: dict) -> LLMBackend | None:
    """Create a backend instance for a specific transport."""
    cls = TRANSPORT_CLASSES.get(transport.transport_name)
    if cls is None:
        return None
    return cls(
        binary_path=transport.binary,
        model=transport.model_id,
        config=config_raw,
    )


def check_model_profiles_availability(
    config: EngineConfig,
    model_profiles: set[str],
    suppress_backend_logs: bool = False,
) -> dict[str, tuple[bool, str | None]]:
    """Check availability for specific model profiles using primary transports."""
    status: dict[str, tuple[bool, str | None]] = {}
    for model_profile in sorted(model_profiles):
        spec = config.get_model_spec(model_profile)
        if spec is None or not spec.transports:
            status[model_profile] = (False, "not in model_catalog or no transports")
            continue
        primary = spec.primary_transport
        if primary is None:
            status[model_profile] = (False, "no primary transport")
            continue
        backend = _instantiate_transport(primary, config.raw)
        if backend is None:
            status[model_profile] = (False, f"unknown transport '{primary.transport_name}'")
            continue
        if suppress_backend_logs:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                available = bool(backend.check_available())
        else:
            available = bool(backend.check_available())
        if available:
            status[model_profile] = (True, None)
        else:
            error = getattr(backend, "last_health_error", None)
            status[model_profile] = (False, error or "transport unavailable")

    return status


# ── v2: Retryable error classification ───────────────────────


def _is_retryable_dispatch_error(error: str | None, raw_output: str | None = None) -> bool:
    """Classify if an error warrants retrying the same model (transport errors only).

    Returns True for transport/infrastructure failures (rate limits, timeouts, network).
    Returns False for model quality failures (bad JSON, hallucinations).

    IMPORTANT: This distinction drives the copilot transport fallback gate (Fix-B):
    - Transport error → retry same transport, then try copilot (different CLI, same model)
    - Quality error   → no retry, no copilot (same model via different CLI won't fix it)
    """
    if not error and not raw_output:
        return False
    text = f"{error or ''}\n{raw_output or ''}".lower()
    patterns = (
        "429", "rate limit", "no capacity", "resource exhausted",
        "503", "service unavailable",
        "timeout", "timed out",
        "502", "504",
        "overloaded", "usage limit",
        "connection reset", "connection aborted", "econnreset",
    )
    return any(p in text for p in patterns)


# ── v2: Core dispatch with retry + transport fallback ─────────


def _dispatch_model_with_retry(
    config: EngineConfig,
    model_profile: str,
    prompt: str,
    output_schema: Path | None = None,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> DispatchResult:
    """Dispatch to a model with retry + copilot transport fallback.

    NEVER substitutes a different model. Only changes transport (CLI).

    Flow:
    1. Try primary transport with retries (same model, same CLI)
       - JSON recovery attempted between retries
    2. If all retries fail AND last error was a transport error AND
       copilot_transport_fallback=true → try same model via copilot CLI (Fix-B)
    3. Return final result (success or error)

    Fix-B: Copilot is only tried for transport errors (429, 503, timeout, network),
    NOT for model quality failures (bad JSON, hallucinations). Using a different CLI
    for the same model won't fix a model-level quality issue.
    """
    spec = config.get_model_spec(model_profile)
    if spec is None or not spec.transports:
        return DispatchResult(
            False, None, "", model_profile, "none", 0.0,
            f"Model '{model_profile}' not found in model_catalog or has no transports",
            model_profile=model_profile,
        )

    primary = spec.primary_transport
    if primary is None:
        return DispatchResult(
            False, None, "", model_profile, "none", 0.0,
            f"Model '{model_profile}' has no primary transport",
            model_profile=model_profile,
        )

    retry_cfg = config.retry_config
    max_attempts = retry_cfg.get("max_attempts", 2)
    backoff = retry_cfg.get("backoff_seconds", 5)

    backend = _instantiate_transport(primary, config.raw)
    if backend is None:
        return DispatchResult(
            False, None, "", model_profile, primary.transport_name, 0.0,
            f"Could not instantiate {primary.transport_name} backend",
            model_profile=model_profile, transport=primary.transport_name,
        )

    attempts: list[dict] = []
    decision_log: list[str] = []

    def _record_attempt(
        phase: str,
        attempt_no: int,
        result_obj: DispatchResult,
        used_timeout: int,
    ) -> None:
        attempts.append(
            {
                "attempt": attempt_no,
                "phase": phase,
                "model_profile": model_profile,
                "model_id": result_obj.model,
                "transport": result_obj.transport or result_obj.backend,
                "timeout": used_timeout,
                "duration_s": result_obj.duration_s,
                "exit_code": result_obj.exit_code,
                "error": result_obj.error,
            }
        )

    # Phase 1: Try primary transport with retries
    last_result = None
    effective_timeout = timeout if timeout is not None else primary.timeout_seconds

    for attempt in range(1, max_attempts + 1):
        decision_log.append(f"primary:attempt_{attempt}_start")
        result = backend.dispatch(prompt, output_schema, cwd, effective_timeout)
        result.model_profile = model_profile
        result.transport = primary.transport_name
        result.attempt = attempt
        _record_attempt("primary", attempt, result, effective_timeout)

        if result.success:
            result.attempts = attempts
            return result

        last_result = result

        # JSON recovery before retry
        if result.raw_output:
            recovered = _try_recover_json(result.raw_output, result.error)
            if recovered is not None:
                print(f"[dispatch] JSON recovered for {model_profile} on attempt {attempt}", file=sys.stderr)
                result.success = True
                result.output = recovered
                result.attempts = attempts
                attempts[-1]["recovered"] = True
                return result

        if attempt < max_attempts and _is_retryable_dispatch_error(result.error, result.raw_output):
            wait = backoff * attempt
            decision_log.append(
                f"primary:attempt_{attempt}_retry_wait_{wait}s_reason=retryable_error"
            )
            print(
                f"[dispatch] Retry {attempt}/{max_attempts} for {model_profile} "
                f"via {primary.transport_name} (wait {wait}s): {(result.error or '')[:80]}",
                file=sys.stderr,
            )
            time.sleep(wait)
        else:
            decision_log.append(f"primary:attempt_{attempt}_stop")
            break

    # Fix-B: Phase 2 (copilot transport fallback) only for transport errors.
    # If the model produced bad JSON (quality failure), using the same model
    # via a different CLI won't help — skip copilot to avoid wasting tokens.
    last_is_transport_error = (
        last_result is not None
        and _is_retryable_dispatch_error(last_result.error, last_result.raw_output)
    )

    if config.copilot_transport_fallback and last_is_transport_error:
        copilot = spec.copilot_transport
        if copilot and copilot.transport_name != primary.transport_name:
            copilot_backend = _instantiate_transport(copilot, config.raw)
            if copilot_backend and copilot_backend.check_available():
                print(
                    f"[dispatch] Transport fallback: {model_profile} "
                    f"{primary.transport_name} → copilot (model_id={copilot.model_id})",
                )
                decision_log.append(
                    f"copilot_fallback:primary={primary.transport_name}_to={copilot.transport_name}"
                )
                # Fix-E / Fix-I: Respect caller timeout. Default to primary
                # transport timeout only when caller has not provided one.
                effective_timeout = timeout if timeout is not None else primary.timeout_seconds
                copilot_result = copilot_backend.dispatch(
                    prompt, output_schema, cwd, effective_timeout
                )
                # Preserve logical backend identity (short name)
                copilot_result.backend = primary.transport_name
                copilot_result.model_profile = model_profile
                copilot_result.transport = "copilot"
                copilot_result.routed_via = "copilot"
                copilot_result.fallback_reason = "transport_fallback"
                copilot_result.attempt = len(attempts) + 1
                _record_attempt("copilot_fallback", copilot_result.attempt, copilot_result, effective_timeout)

                if copilot_result.success:
                    print(
                        f"[dispatch]   ✓ {model_profile} rescued via copilot "
                        f"({copilot_result.model}, {copilot_result.duration_s:.1f}s)",
                    )
                    copilot_result.attempts = attempts
                    return copilot_result

                # JSON recovery on copilot result
                if copilot_result.raw_output:
                    recovered = _try_recover_json(copilot_result.raw_output, copilot_result.error)
                    if recovered is not None:
                        print(f"[dispatch] JSON recovered for {model_profile} via copilot", file=sys.stderr)
                        copilot_result.success = True
                        copilot_result.output = recovered
                        if attempts:
                            attempts[-1]["recovered"] = True
                        copilot_result.attempts = attempts
                        return copilot_result

                print(
                    f"[dispatch]   ✗ {model_profile} via copilot also failed: "
                    f"{(copilot_result.error or 'unknown')[:100]}",
                    file=sys.stderr,
                )
                decision_log.append("copilot_fallback:failed")
                last_result = copilot_result

            else:
                decision_log.append("copilot_fallback:unavailable")

    if last_result is None:
        return DispatchResult(
            False, None, "", model_profile, primary.transport_name, 0.0,
            f"Model '{model_profile}' execution did not run",
            model_profile=model_profile,
            transport=primary.transport_name,
            failure_ctx={
                "model_profile": model_profile,
                "backend": primary.transport_name,
                "attempts": attempts,
                "decision_log": decision_log,
                "last_error": "no result",
            },
        )

    last_result.attempts = attempts
    if last_result.failure_ctx is None:
        last_result.failure_ctx = {
            "model_profile": model_profile,
            "backend": primary.transport_name,
            "transport": last_result.transport or primary.transport_name,
            "attempts": attempts,
            "decision_log": decision_log,
            "last_error": last_result.error,
        }
    return last_result


# ── Main dispatch entry point ─────────────────────────────────


def dispatch_step(
    config: EngineConfig,
    step_name: str,
    prompt: str,
    output_schema: Path | None = None,
    cwd: Path | None = None,
) -> DispatchResult | dict[str, DispatchResult]:
    """Dispatch a step to LLM backend(s).

    v2: Uses model_catalog + pipeline_models for model-centric dispatch.
    v1: Uses task_routing + BACKEND_CLASSES for backend-centric dispatch.
    """
    step_cfg = get_step_config(config, step_name)
    is_multi = step_cfg.get("multi", False)

    if "python" in step_cfg.get("backends", []):
        raise ValueError(
            f"Step {step_name} uses 'python' backend — "
            "should be executed as a runner, not dispatched to LLM."
        )

    timeout = _get_timeout(config, step_name)

    if config.is_v2:
        return _dispatch_step_v2(config, step_name, step_cfg, prompt, output_schema, cwd, timeout, is_multi)
    else:
        return _dispatch_step_v1(config, step_name, step_cfg, prompt, output_schema, cwd, timeout, is_multi)


def _dispatch_step_v2(
    config: EngineConfig,
    step_name: str,
    step_cfg: dict,
    prompt: str,
    output_schema: Path | None,
    cwd: Path | None,
    timeout: int,
    is_multi: bool,
) -> DispatchResult | dict[str, DispatchResult]:
    """v2 model-centric dispatch."""
    model_profiles = step_cfg.get("models", [])

    # FUSION step: use fusion model for the step that requested fusion
    if step_name == "FUSION":
        fusion_model = config.fusion_model
        print(f"[dispatch] FUSION → {fusion_model} (timeout={timeout}s)")
        return _dispatch_model_with_retry(config, fusion_model, prompt, output_schema, cwd, timeout)

    if is_multi:
        # Dispatch to ALL models in parallel
        results: dict[str, DispatchResult] = {}
        dispatch_plan: dict[str, str] = {}  # model_profile → transport_name
        unavailable_models: dict[str, str] = {}
        transport_in_use: dict[str, str] = {}

        for model_profile in model_profiles:
            spec = config.get_model_spec(model_profile)
            if spec is None or not spec.transports:
                unavailable_models[model_profile] = "not in model_catalog"
                continue
            transport_name = config.resolve_transport_name(model_profile)
            # Check preflight cache
            if config.preflight_done() and not config.is_backend_available(transport_name):
                unavailable_models[model_profile] = "startup preflight: unavailable"
                continue
            if transport_name in transport_in_use:
                print(
                    f"[dispatch] WARNING: Skipping {model_profile} for {step_name}; "
                    f"transport '{transport_name}' already scheduled by {transport_in_use[transport_name]} "
                    f"(first wins).",
                    file=sys.stderr,
                )
                unavailable_models[model_profile] = (
                    f"transport collision: {transport_name} already assigned to {transport_in_use[transport_name]}"
                )
                continue
            transport_in_use[transport_name] = model_profile
            dispatch_plan[model_profile] = transport_name

        if not dispatch_plan:
            detail = "; ".join(f"{m}: {r}" for m, r in unavailable_models.items())
            return DispatchResult(
                False, None, "", "none", "none", 0.0,
                f"No routable models for {step_name}. Unavailable: {detail}",
                failure_ctx={
                    "step_context": {
                        "step": step_name,
                        "mode": "multi",
                        "requested_models": model_profiles,
                    },
                    "failed_details": [
                        f"{model}: {reason}" for model, reason in unavailable_models.items()
                    ],
                },
            )

        min_backends = config.get_min_backends(step_name)
        if len(dispatch_plan) < min_backends:
            detail = "; ".join(f"{m}: {r}" for m, r in unavailable_models.items())
            missing = max(min_backends - len(dispatch_plan), 0)
            print(
                f"[dispatch] WARNING: {step_name} has only {len(dispatch_plan)} routable model(s) "
                f"(min {min_backends}). Missing {missing}: {detail}",
                file=sys.stderr,
            )

        print(f"[dispatch] {step_name} → multi-model: {', '.join(dispatch_plan)} (timeout={timeout}s)")

        max_workers = config.execution.get("max_parallel_backends", 3)
        global_timeout = timeout + 60
        t0 = time.monotonic()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        future_to_model = {
            executor.submit(
                _dispatch_model_with_retry, config, model_profile, prompt, output_schema, cwd, timeout
            ): model_profile
            for model_profile in dispatch_plan
        }
        try:
            for future in concurrent.futures.as_completed(future_to_model, timeout=global_timeout):
                model_profile = future_to_model[future]
                transport_name = dispatch_plan[model_profile]
                elapsed = time.monotonic() - t0
                try:
                    r = future.result()
                    results[model_profile] = r
                    status = "✓" if r.success else "✗"
                    via = f" via {r.transport}" if r.transport != transport_name else ""
                    print(
                        f"[dispatch]   {status} {model_profile} ({transport_name}){via} "
                        f"({r.model}, {r.duration_s:.1f}s, {elapsed:.0f}s elapsed)"
                    )
                except Exception as e:
                    results[model_profile] = DispatchResult(
                        False, None, "", "unknown", transport_name, 0.0, str(e),
                        model_profile=model_profile, transport=transport_name,
                        failure_ctx={
                            "step_context": {
                                "step": step_name,
                                "mode": "multi",
                                "model_profile": model_profile,
                                "thread": "worker_exception",
                            },
                            "last_error": str(e),
                            "attempts": [{
                                "attempt": 1,
                                "phase": "execution",
                                "model_profile": model_profile,
                                "model_id": model_profile,
                                "transport": transport_name,
                                "duration_s": 0.0,
                                "error": str(e),
                            }],
                        },
                    )
                    print(
                        f"[dispatch]   ✗ {model_profile} ({transport_name}) "
                        f"EXCEPTION: {str(e)[:80]} ({elapsed:.0f}s elapsed)"
                    )
        except concurrent.futures.TimeoutError:
            print(f"[dispatch] WARNING: Global timeout ({global_timeout}s) reached", file=sys.stderr)
        finally:
            for future, mp in future_to_model.items():
                tn = dispatch_plan[mp]
                if mp not in results:
                    future.cancel()
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

        # Mark timed-out models
        for mp, tn in dispatch_plan.items():
            if mp not in results:
                results[mp] = DispatchResult(
                    False, None, "", "unknown", tn, 0.0,
                    f"Global aggregation timeout ({global_timeout}s) exceeded",
                    model_profile=mp, transport=tn,
                    failure_ctx={
                        "step_context": {
                            "step": step_name,
                            "mode": "multi",
                            "model_profile": mp,
                        },
                        "last_error": "global aggregation timeout",
                        "timeout_s": global_timeout,
                        "decision_log": ["aggregation_timeout"],
                    },
                )

        return results

    else:
        # Single-model dispatch
        model_profile = model_profiles[0] if model_profiles else config.default_single_model
        transport_name = config.resolve_transport_name(model_profile)
        print(f"[dispatch] {step_name} → {model_profile} via {transport_name} (timeout={timeout}s)")
        t0 = time.monotonic()
        result = _dispatch_model_with_retry(config, model_profile, prompt, output_schema, cwd, timeout)
        elapsed = time.monotonic() - t0
        status = "✓" if result.success else "✗"
        print(f"[dispatch]   {status} {step_name} done ({result.model}, {result.duration_s:.1f}s, {elapsed:.0f}s wall)")
        return result


# ── Multi-model fusion ────────────────────────────────────────


def dispatch_multi_and_fuse(
    config: EngineConfig,
    step_name: str,
    prompt: str,
    instrucciones_dir: Path,
    output_schema: Path | None = None,
    cwd: Path | None = None,
) -> DispatchResult:
    """
    1. Dispatch to N backends in parallel
    2. Collect results {backend: output_json}
    3. Build fusion prompt
    4. Dispatch fusion to integrator model
    5. Return fused result
    """
    # Step 1: Dispatch to all backends
    multi_results = dispatch_step(config, step_name, prompt, output_schema, cwd)

    if isinstance(multi_results, DispatchResult):
        return multi_results

    # Step 2: Collect successful outputs and persist traces
    successful_outputs: dict[str, dict] = {}
    rejected_outputs: dict[str, str] = {}
    for model_profile, result in multi_results.items():
        backend_name = result.backend or model_profile

        if result.success and result.output:
            normalized = _normalize_backend_output(result.output)
            if cwd:
                raw_trace_path = cwd / f"_multi_raw_{step_name}_{backend_name}.json"
                try:
                    raw_trace_path.write_text(json.dumps(result.output, indent=2, ensure_ascii=False))
                except OSError:
                    pass
                trace_path = cwd / f"_multi_{step_name}_{backend_name}.json"
                try:
                    trace_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False))
                    print(f"[dispatcher] Saved trace: {trace_path.name}")
                except OSError as e:
                    print(f"[dispatcher] WARNING: Could not save trace {trace_path.name}: {e}", file=sys.stderr)
            is_valid, reason = _validate_multi_candidate(config, step_name, normalized)
            if is_valid:
                successful_outputs[backend_name] = normalized
            else:
                rejected_outputs[backend_name] = reason or "invalid artifact payload"
                print(
                    f"[dispatcher] WARNING: Backend {backend_name} returned invalid output "
                    f"for {step_name}: {rejected_outputs[backend_name]}",
                    file=sys.stderr,
                )
        else:
            # Fix-C: JSON recovery is only attempted for v1 here.
            # For v2, _dispatch_model_with_retry already exhausted all recovery options
            # (including _try_recover_json) before returning a failed result. Retrying here
            # would be redundant and potentially confusing.
            recovered = None
            if not config.is_v2 and result.raw_output:
                recovered = _try_recover_json(result.raw_output, result.error)
            if recovered is not None:
                print(
                    f"[dispatcher] JSON recovered for {backend_name} (model_profile={model_profile}) "
                    f"on {step_name}",
                    file=sys.stderr,
                )
                normalized = _normalize_backend_output(recovered)
                if cwd:
                    raw_trace_path = cwd / f"_multi_raw_{step_name}_{backend_name}.json"
                    try:
                        raw_trace_path.write_text(json.dumps(recovered, indent=2, ensure_ascii=False))
                    except OSError:
                        pass
                    trace_path = cwd / f"_multi_{step_name}_{backend_name}.json"
                    try:
                        trace_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False))
                        print(f"[dispatcher] Saved recovered trace: {trace_path.name}")
                    except OSError as e:
                        print(f"[dispatcher] WARNING: Could not save trace {trace_path.name}: {e}", file=sys.stderr)
                is_valid, reason = _validate_multi_candidate(config, step_name, normalized)
                if is_valid:
                    successful_outputs[backend_name] = normalized
                else:
                    rejected_outputs[backend_name] = reason or "invalid artifact payload"
            else:
                print(
                    f"[dispatcher] WARNING: Backend {backend_name} (model_profile={model_profile}) "
                    f"failed for {step_name}: "
                    f"{result.error}",
                    file=sys.stderr,
                )

    if not successful_outputs:
        failed_details = []
        aggregated_attempts: list[dict] = []
        for name, result in multi_results.items():
            backend_name = result.backend or name
            if backend_name in rejected_outputs:
                failed_details.append(f"{backend_name}: {rejected_outputs[backend_name]}")
            elif not result.success or not result.output:
                failed_details.append(f"{backend_name}: {result.error or 'no output'}")
            if result.failure_ctx:
                for attempt in result.failure_ctx.get("attempts", []) or []:
                    if isinstance(attempt, dict):
                        merged = dict(attempt)
                        merged.setdefault("model_profile", result.model_profile or result.model)
                        aggregated_attempts.append(merged)
        return DispatchResult(
            False, None, "", "none", "fusion", 0.0,
            f"All backends failed or were invalid for {step_name}. "
            f"Details: {'; '.join(failed_details)}",
            failure_ctx={
                "step_context": {
                    "step": step_name,
                    "mode": "multi",
                    "models": sorted(multi_results.keys()),
                },
                "failed_details": failed_details,
                "attempts": aggregated_attempts[:30],
                "decision_log": ["multi_fusion:all_outputs_invalid"],
                "last_error": failed_details[0] if failed_details else "all outputs invalid",
            }
        )

    # Enforce min_backends
    if config.is_v2:
        min_backends = config.get_min_backends(step_name)
    else:
        multi_cfg = config.get_multi_model_config(step_name)
        backends_list = (multi_cfg or {}).get("models", [])
        min_backends = (multi_cfg or {}).get("min_backends", len(backends_list))

    if len(successful_outputs) < min_backends:
        print(
            f"[dispatch] WARNING: {step_name} has only {len(successful_outputs)} valid output(s) "
            f"(min {min_backends}). Proceeding with available outputs.",
            file=sys.stderr,
        )

    used = sorted(successful_outputs.keys())

    if len(successful_outputs) == 1:
        backend_name = list(successful_outputs.keys())[0]
        original = next(
            (r for r in multi_results.values() if (r.backend or "") == backend_name),
            None,
        )
        if original is None:
            return DispatchResult(
                False, None, "", "none", "fusion", 0.0,
                "Internal dispatch mapping inconsistency"
            )
        return DispatchResult(
            success=original.success,
            output=successful_outputs[backend_name],
            raw_output=original.raw_output,
            model=original.model,
            backend=original.backend,
            duration_s=original.duration_s,
            error=original.error,
            backends_used=used,
            model_profile=original.model_profile,
            transport=original.transport,
        )

    # Step 3: Build fusion prompt
    if config.is_v2:
        fusion_instruction = config.get_fusion_instruction(step_name)
    else:
        multi_cfg = config.get_multi_model_config(step_name) or {}
        fusion_instruction = multi_cfg.get("fusion_instruction")

    fusion_prompt = build_fusion_prompt(
        successful_outputs,
        step_name,
        instrucciones_dir,
        fusion_instruction_filename=fusion_instruction,
    )

    # Step 4: Dispatch fusion
    if config.is_v2:
        fusion_model = config.get_fusion_model_for_step(step_name)
        print(f"[dispatch] Fusion for {step_name} → {fusion_model}")
        fusion_result = _dispatch_model_with_retry(
            config, fusion_model, fusion_prompt, output_schema, cwd,
            _get_timeout(config, "FUSION"),
        )
    else:
        fusion_result = dispatch_step(config, "FUSION", fusion_prompt, output_schema, cwd)

    if isinstance(fusion_result, dict):
        fusion_result = list(fusion_result.values())[0]

    fusion_result.backends_used = used
    return fusion_result


# ── Filing dispatch ───────────────────────────────────────────


def _filing_label(filing: dict) -> str:
    ftype = filing.get("tipo", filing.get("type", "?"))
    titulo = filing.get("titulo", "")
    period = ""
    for part in titulo.replace("-", " ").split():
        if part.startswith("FY") or part.startswith("Q") or part.startswith("20"):
            period = part
            break
    if not period:
        period = filing.get("fecha_publicacion", "?")[:10]
    return f"{ftype} {period}"


def _is_retryable_filing_error(error: str | None) -> bool:
    """v1 only: classify retryable errors for filing dispatch."""
    if not error:
        return False
    text = error.lower()
    patterns = (
        "timeout", "timed out", "deadline", "temporary", "transient",
        "rate limit", "429", "502", "503", "504",
        "connection reset", "connection aborted", "network", "econnreset",
    )
    return any(p in text for p in patterns)


def dispatch_parallel_filings(
    config: EngineConfig,
    filings: list[dict],
    instrucciones_dir: Path,
    case_dir: Path,
) -> list[DispatchResult]:
    """Dispatch TP_EXTRACTOR_FILING for each filing in parallel.

    Fix-A: For v2, each filing delegates to _dispatch_model_with_retry(), which
    provides retry + copilot transport fallback + JSON recovery. The old hand-rolled
    while-loop with backend.dispatch() is replaced to avoid bypassing the orchestrator.
    """
    max_parallel = config.execution.get("max_parallel_filings", 4)
    timeout = int(config.timeouts.get("tp_extractor_per_filing", 300))

    step_cfg = get_step_config(config, "TP_EXTRACTOR_FILING")

    if config.is_v2:
        model_profiles = step_cfg.get("models", [config.default_single_model])
        model_profile = model_profiles[0]
        spec = config.get_model_spec(model_profile)
        if spec is None or not spec.transports:
            return [DispatchResult(
                False, None, "", "none", "none", 0.0,
                f"Model {model_profile} not available for TP_EXTRACTOR_FILING"
            )]
        primary = spec.primary_transport
        backend_name = primary.transport_name if primary else model_profile

        # Availability check using a temporary backend instance
        check_backend = _instantiate_transport(primary, config.raw) if primary else None
        if not check_backend or not check_backend.check_available():
            return [DispatchResult(
                False, None, "", "none", "none", 0.0,
                f"Model {model_profile} ({backend_name}) not available for TP_EXTRACTOR_FILING"
            )]
    else:
        backend_name = step_cfg["backends"][0]
        backend = _get_backend(config, backend_name)
        model_cfg = config.get_backend_config(backend_name)
        model_profile = backend_name
        retry_cfg = config.retry_config
        max_retries = min(1, retry_cfg.get("max_attempts", 2) - 1)

        if not backend or not backend.check_available():
            return [DispatchResult(
                False, None, "", "none", "none", 0.0,
                f"Backend {backend_name} not available for TP_EXTRACTOR_FILING"
            )]

    total = len(filings)
    print(f"[dispatch] Launching {total} filings → {backend_name} ({model_profile}), "
          f"max_parallel={max_parallel}, timeout={timeout}s")

    def _process_filing(filing_entry: dict) -> DispatchResult:
        local_path = filing_entry.get("local_path")
        filing_path = (case_dir.parent.parent.parent / local_path) if local_path else Path("/dev/null")

        prompt = build_filing_prompt(
            filing_path=filing_path,
            source_entry=filing_entry,
            ticker=filing_entry.get("ticker", "UNKNOWN"),
            instrucciones_dir=instrucciones_dir,
        )

        if config.is_v2:
            # Fix-A: Delegate to the central orchestrator for retry + transport fallback.
            # _dispatch_model_with_retry handles: retry on transport errors, copilot
            # fallback (Fix-B gated), and JSON recovery — all in one consistent place.
            return _dispatch_model_with_retry(config, model_profile, prompt, cwd=case_dir, timeout=timeout)
        else:
            # v1: Direct backend dispatch with simple retry loop
            attempts = 0
            while True:
                result = backend.dispatch(prompt, cwd=case_dir, timeout=timeout)
                if result.success:
                    return result
                if not result.success and result.raw_output:
                    recovered = _try_recover_json(result.raw_output, result.error)
                    if recovered is not None:
                        result.success, result.output = True, recovered
                        return result
                if attempts >= max_retries or not _is_retryable_filing_error(result.error):
                    return result
                attempts += 1
                label = _filing_label(filing_entry)
                print(
                    f"[dispatch]   ↻ retry {attempts}/{max_retries} for {label} "
                    f"({(result.error or 'unknown')[:80]})"
                )
                time.sleep(1.0 * attempts)

    t0 = time.monotonic()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
        future_to_idx = {
            executor.submit(_process_filing, filing): i
            for i, filing in enumerate(filings)
        }
        result_map = {}
        done_count = 0
        ok_count = 0
        fail_count = 0
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            label = _filing_label(filings[idx])
            try:
                result_map[idx] = future.result()
                done_count += 1
                r = result_map[idx]
                elapsed = time.monotonic() - t0
                if r.success:
                    ok_count += 1
                    print(f"[dispatch]   ✓ {done_count}/{total} {label} "
                          f"({r.duration_s:.1f}s, {elapsed:.0f}s elapsed)")
                else:
                    fail_count += 1
                    err_short = (r.error or "unknown")[:80]
                    print(f"[dispatch]   ✗ {done_count}/{total} {label} "
                          f"FAILED: {err_short} ({elapsed:.0f}s elapsed)")
            except Exception as e:
                done_count += 1
                fail_count += 1
                result_map[idx] = DispatchResult(
                    False, None, "", "unknown", "unknown", 0.0, str(e)
                )
                print(f"[dispatch]   ✗ {done_count}/{total} {label} "
                      f"EXCEPTION: {str(e)[:80]}")

        results = [result_map[i] for i in range(len(filings))]

    total_time = time.monotonic() - t0
    durations = [r.duration_s for r in results if r.success]
    avg_dur = sum(durations) / len(durations) if durations else 0
    print(f"[dispatch] Done: {ok_count} ok, {fail_count} failed, "
          f"total {total_time:.1f}s, avg {avg_dur:.1f}s/filing")

    return results


# ── v1 backend helpers (preserved for backward compat) ────────


def _get_backend(config: EngineConfig, backend_name: str) -> LLMBackend | None:
    """v1: Instantiate backend from config binaries."""
    cls = BACKEND_CLASSES.get(backend_name)
    if cls is None:
        return None
    binary_info = config.binaries.get(backend_name)
    if binary_info is None or not binary_info.available:
        return None
    model_cfg = config.get_backend_config(backend_name)
    model = model_cfg.get("default_model", "")
    return cls(binary_path=binary_info.path, model=model, config=config.raw)


def _get_timeout(config: EngineConfig, step_name: str) -> int:
    """Get appropriate timeout for a step."""
    if config.is_v2:
        override = config.raw.get("step_overrides", {}).get(step_name, {})
        if "timeout" in override:
            return override["timeout"]
        models = config.get_models_for_step(step_name)
        if models:
            spec = config.get_model_spec(models[0])
            if spec and spec.primary_transport:
                return spec.primary_transport.timeout_seconds
        return 600

    routing = config.task_routing.get(step_name, {})
    if "timeout" in routing:
        return routing["timeout"]
    model_name = config.get_model_for_task(step_name)
    model_cfg = config.get_backend_config(model_name)
    if model_cfg and "timeout_seconds" in model_cfg:
        return model_cfg["timeout_seconds"]
    return 600


# ── Preflight ─────────────────────────────────────────────────


def preflight_backends(
    config: EngineConfig,
    model_profiles: set[str] | None = None,
) -> dict[str, bool]:
    """Verify availability of all required models/backends at pipeline start."""
    print("[engine] Verificando disponibilidad de backends...", file=sys.stderr)
    results: dict[str, bool] = {}

    if config.is_v2:
        if model_profiles is not None and not model_profiles:
            print("[engine] No model profiles to preflight (empty execution slice).", file=sys.stderr)
            return results

        if model_profiles is None:
            model_profiles = set(config.pipeline_models)
            model_profiles.add(config.fusion_model)
            model_profiles.add(config.default_single_model)
        availability = check_model_profiles_availability(config, model_profiles)

        for model_profile in sorted(model_profiles):
            ok, err = availability.get(model_profile, (False, "not checked"))
            spec = config.get_model_spec(model_profile)
            if spec is None or not spec.transports:
                transport_name = model_profile
                results[transport_name] = False
                print(f"[engine]   ✗ {model_profile}: not in model_catalog", file=sys.stderr)
                continue

            primary = spec.primary_transport
            transport_name = primary.transport_name if primary else model_profile
            results[transport_name] = ok

            if ok:
                backend = _instantiate_transport(primary, config.raw) if primary else None
                warning = getattr(backend, "last_health_warning", None) if backend else None
                suffix = f" ⚠  {warning}" if warning else ""
                print(f"[engine]   ✓ {model_profile} ({transport_name}){suffix}", file=sys.stderr)
            else:
                print(f"[engine]   ✗ {model_profile} ({transport_name}): {err}", file=sys.stderr)
    else:
        for backend_name in config.models:
            if backend_name.startswith("_"):
                continue
            backend = _get_backend(config, backend_name)
            if backend is None:
                results[backend_name] = False
                print(f"[engine]   ✗ {backend_name}: binary not found", file=sys.stderr)
                continue
            available = backend.check_available()
            results[backend_name] = available
            if available:
                warning = getattr(backend, "last_health_warning", None)
                suffix = f" ⚠  {warning}" if warning else ""
                print(f"[engine]   ✓ {backend_name}{suffix}", file=sys.stderr)
            else:
                error = getattr(backend, "last_health_error", None)
                suffix = f": {error}" if error else ""
                print(f"[engine]   ✗ {backend_name}{suffix}", file=sys.stderr)

    config._backend_availability.update(results)
    available_count = sum(1 for ok in results.values() if ok)
    print(f"[engine] Backends disponibles: {available_count}/{len(results)}", file=sys.stderr)
    return results


# ── v1 dispatch (legacy) ──────────────────────────────────────


def _dispatch_step_v1(
    config: EngineConfig,
    step_name: str,
    step_cfg: dict,
    prompt: str,
    output_schema: Path | None,
    cwd: Path | None,
    timeout: int,
    is_multi: bool,
) -> DispatchResult | dict[str, DispatchResult]:
    """v1 legacy backend-centric dispatch. Preserved for backward compat."""
    backends_list = step_cfg.get("backends", [])

    if is_multi:
        results = {}
        dispatch_plan: dict[str, dict[str, object]] = {}
        unavailable_reasons: dict[str, str] = {}
        for backend_name in backends_list:
            if config.preflight_done() and not config.is_backend_available(backend_name):
                unavailable_reasons[backend_name] = "startup preflight: unavailable"
                continue
            backend = _get_backend(config, backend_name)
            primary_reason = "backend adapter not found"
            if backend:
                if backend.check_available():
                    dispatch_plan[backend_name] = {"route": "primary", "backend": backend}
                    continue
                primary_reason = backend.last_health_error or "backend health check failed"
            unavailable_reasons[backend_name] = primary_reason

        if not dispatch_plan:
            detail = "; ".join(f"{n}: {r}" for n, r in unavailable_reasons.items())
            return DispatchResult(False, None, "", "none", "none", 0.0,
                                  f"No routable backends for {step_name}. Unavailable: {detail}")

        multi_cfg = config.get_multi_model_config(step_name)
        min_backends = (multi_cfg or {}).get("min_backends", len(backends_list))
        if len(dispatch_plan) < min_backends:
            unavailable = [f"{n}: {unavailable_reasons.get(n, '?')}"
                           for n in backends_list if n not in dispatch_plan]
            return DispatchResult(
                False, None, "", "none", "none", 0.0,
                f"BLOCKED: Not enough backends for {step_name}: "
                f"{len(dispatch_plan)}/{min_backends}. Unavailable: {'; '.join(unavailable)}"
            )

        print(f"[dispatch] {step_name} → multi-model: {', '.join(dispatch_plan)} (timeout={timeout}s)")
        max_workers = config.execution.get("max_parallel_backends", 3)
        global_timeout = timeout + 60
        t0 = time.monotonic()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        future_to_name = {
            executor.submit(plan["backend"].dispatch, prompt, output_schema, cwd, timeout): name
            for name, plan in dispatch_plan.items()
        }
        try:
            for future in concurrent.futures.as_completed(future_to_name, timeout=global_timeout):
                name = future_to_name[future]
                elapsed = time.monotonic() - t0
                try:
                    results[name] = future.result()
                    r = results[name]
                    status = "✓" if r.success else "✗"
                    print(f"[dispatch]   {status} {name} ({r.model}, {r.duration_s:.1f}s, {elapsed:.0f}s elapsed)")
                except Exception as e:
                    results[name] = DispatchResult(False, None, "", "unknown", name, 0.0, str(e))
                    print(f"[dispatch]   ✗ {name} EXCEPTION: {str(e)[:80]}")
        except concurrent.futures.TimeoutError:
            print(f"[dispatch] WARNING: Global timeout ({global_timeout}s) reached", file=sys.stderr)
        finally:
            for future, name in future_to_name.items():
                if name not in results:
                    future.cancel()
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

        for future, name in future_to_name.items():
            if name not in results:
                results[name] = DispatchResult(
                    False, None, "", "unknown", name, 0.0,
                    f"Global timeout ({global_timeout}s) exceeded"
                )
        return results

    else:
        # Single backend
        for backend_name in backends_list:
            if config.preflight_done() and not config.is_backend_available(backend_name):
                continue
            backend = _get_backend(config, backend_name)
            if backend and backend.check_available():
                model_cfg = config.get_backend_config(backend_name)
                model_name = model_cfg.get("default_model", backend_name)
                print(f"[dispatch] {step_name} → {backend_name} ({model_name}, timeout={timeout}s)")
                t0 = time.monotonic()
                result = backend.dispatch(prompt, output_schema, cwd, timeout)
                elapsed = time.monotonic() - t0
                status = "✓" if result.success else "✗"
                print(f"[dispatch]   {status} {step_name} done ({result.model}, {result.duration_s:.1f}s, {elapsed:.0f}s wall)")
                if not result.success and result.raw_output:
                    recovered = _try_recover_json(result.raw_output, result.error)
                    if recovered is not None:
                        result = DispatchResult(
                            success=True, output=recovered, raw_output=result.raw_output,
                            model=result.model, backend=result.backend, duration_s=result.duration_s,
                        )
                return result

        return DispatchResult(
            False, None, "", "none", "none", 0.0,
            f"No routable backends for {step_name}: tried {backends_list}"
        )


# ── Escalation (deprecated, gated by flag) ────────────────────


def _should_escalate(config: EngineConfig, step_name: str, result: DispatchResult) -> bool:
    """v1: Check escalation conditions. Deprecated in v2."""
    if not config.escalation_enabled:
        return False
    esc = config.get_escalation_config(step_name)
    if not esc:
        return False
    condition = esc.get("escalate_condition", "")
    if condition == "on_failure":
        return not result.success
    return False


def dispatch_with_escalation(
    config: EngineConfig,
    step_name: str,
    prompt: str,
    output_schema: Path | None = None,
    cwd: Path | None = None,
) -> DispatchResult:
    """Dispatch step with optional escalation. Deprecated in v2."""
    result = dispatch_step(config, step_name, prompt, output_schema, cwd)
    if isinstance(result, dict):
        return result

    if _should_escalate(config, step_name, result):
        esc = config.get_escalation_config(step_name)
        escalate_to = esc["escalate_to"]
        print(f"[dispatcher] Escalating {step_name} to {escalate_to}", file=sys.stderr)
        backend = _get_backend(config, escalate_to)
        if backend and backend.check_available():
            timeout = _get_timeout(config, step_name)
            return backend.dispatch(prompt, output_schema, cwd, timeout)
        print(f"[dispatcher] Escalation backend {escalate_to} not available", file=sys.stderr)

    return result
