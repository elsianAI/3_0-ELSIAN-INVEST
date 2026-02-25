"""Despacha sub-tareas a backends según config (v1 y v2).

v2: model-centric dispatch with retry + transport fallback.
v1: legacy backend-centric dispatch (preserved for backward compat).
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import datetime as dt
import json
import io
import sys
import threading
import time
from pathlib import Path

from .config import EngineConfig, get_step_config, ModelTransport
from .prompt_builder import build_prompt, build_fusion_prompt, build_filing_prompt, _normalize_backend_output
from .validator import validate_artifact, SCHEMA_MAP
from .step_contracts import get_allowed_schemas, get_primary_schema
from .backends.base import DispatchResult, LLMBackend, _try_recover_json_ex
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

_TRUNCATION_CONTINUATION_STEPS = {"ARBITRO"}
_PROMPT_EXCERPT_LOCK = threading.Lock()


def _append_prompt_excerpt_meta(case_dir: Path, payload: dict) -> None:
    try:
        diag_dir = case_dir / "_diagnostics" / "prompt_excerpt"
        diag_dir.mkdir(parents=True, exist_ok=True)
        target = diag_dir / "TP_EXTRACTOR_FILING_excerpt_meta.jsonl"
        line = json.dumps(payload, ensure_ascii=False)
        with _PROMPT_EXCERPT_LOCK:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception as exc:
        print(
            f"[dispatch] WARNING: could not persist prompt excerpt metadata: {exc}",
            file=sys.stderr,
        )


# ── Validation helpers (shared v1/v2) ────────────────────────


def _is_viable_recovered_artifact(payload: dict) -> bool:
    """Check if a recovered JSON looks like a viable artifact, not a sub-fragment.

    All pipeline artifacts have ``version_esquema``.  A recovered object that
    lacks this key (and has very few top-level keys) is almost certainly a
    sub-object fragment extracted by balanced_brace rather than a real artifact.
    """
    if not isinstance(payload, dict) or not payload:
        return False
    if "version_esquema" in payload:
        return True
    # Accept objects with enough structure to be plausible artifacts even
    # without version_esquema (e.g. legacy or ad-hoc outputs).
    return len(payload) >= 8


def _looks_like_transport_envelope(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if "version_esquema" in payload:
        return False
    if "result" in payload and ("modelUsage" in payload or "type" in payload):
        return True
    if "response" in payload and ("session_id" in payload or "stats" in payload):
        return True
    # Claude CLI envelope without "result" key (e.g. error_max_turns, permission_denials)
    if "session_id" in payload and "modelUsage" in payload:
        return True
    if "type" in payload and "subtype" in payload and "session_id" in payload:
        return True
    return False


def _unwrap_transport_envelope(payload: dict) -> tuple[dict | None, str | None]:
    """Try to extract artifact JSON from inside a transport envelope.

    Claude --output-format json wraps model output in ``{"result": ..., "type": ...}``.
    When the backend fails to parse the inner ``result`` (e.g. mixed text+JSON from
    agentic mode), the recovery layer sees only the outer envelope.  This helper
    dives into ``result`` and tries the same JSON recovery cascade on it.

    Returns ``(artifact_dict, recovery_method)`` or ``(None, None)``.
    """
    if not isinstance(payload, dict):
        return None, None

    result_val = payload.get("result")
    if result_val is None:
        # Try "response" key (alternate envelope shapes)
        result_val = payload.get("response")
    if result_val is None:
        return None, None

    # If result is already a dict with version_esquema, use it directly
    if isinstance(result_val, dict):
        if "version_esquema" in result_val:
            return result_val, "envelope_result_dict"
        return None, None

    if not isinstance(result_val, str) or not result_val.strip():
        return None, None

    # Apply full JSON recovery cascade on the inner text (no error filter)
    inner, method = _try_recover_json_ex(result_val, error=None)
    if inner is not None and not _looks_like_transport_envelope(inner):
        return inner, f"envelope_unwrap_{method or 'unknown'}"
    return None, None


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


def _resolve_expected_keys(
    config: EngineConfig, step_name: str | None,
) -> tuple[str | None, set[str] | None]:
    """Resolve expected top-level keys for a step from its canonical template."""
    if not step_name:
        return None, None
    schema_name = get_primary_schema(step_name)
    if not schema_name:
        return None, None
    schema_rel = SCHEMA_MAP.get(schema_name)
    if not schema_rel:
        return schema_name, None
    schema_path = config.get_path("schemas") / schema_rel
    if not schema_path.exists():
        return schema_name, None
    try:
        template = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        return schema_name, None
    if not isinstance(template, dict):
        return schema_name, None
    expected = {
        key for key in template.keys()
        if isinstance(key, str) and not key.startswith("_comment")
    }
    return schema_name, expected or None


def _attempt_truncation_continuation(
    config: EngineConfig,
    backend: LLMBackend,
    model_profile: str,
    step_name: str,
    prompt: str,
    failed_result: DispatchResult,
    output_schema: Path | None,
    cwd: Path | None,
    timeout: int,
) -> DispatchResult | None:
    """Try one continuation call for truncated Claude output.

    Returns:
      - None: continuation not attempted (preconditions unmet)
      - DispatchResult: continuation attempted (success/failure)
    """
    schema_name, expected_keys = _resolve_expected_keys(config, step_name)
    if not schema_name or not expected_keys:
        return None

    partial, source_recovery_method = _try_recover_json_ex(
        failed_result.raw_output or "",
        error=None,
    )
    if partial is None:
        return None
    if _looks_like_transport_envelope(partial):
        return None

    present_keys = {k for k in partial.keys() if isinstance(k, str)}
    missing_keys = sorted(expected_keys - present_keys)
    if not missing_keys:
        return None

    last_key = None
    for key in reversed(list(partial.keys())):
        if isinstance(key, str) and not key.startswith("_comment"):
            last_key = key
            break
    requested_keys = list(missing_keys)
    if last_key and last_key not in requested_keys:
        requested_keys.append(last_key)

    continuation_prompt = (
        f"{prompt}\n\n"
        "# CONTINUATION MODE\n\n"
        "Tu salida anterior quedó truncada. "
        "NO repitas el artefacto completo.\n"
        f"Campos ya presentes: {json.dumps(sorted(present_keys), ensure_ascii=False)}\n"
        f"Devuelve SOLO estas claves top-level: {json.dumps(requested_keys, ensure_ascii=False)}\n"
        "Responde únicamente con un objeto JSON, sin markdown ni texto adicional."
    )

    # Continuation requests a subset of fields; do not enforce full-schema output here.
    continuation_result = backend.dispatch(
        continuation_prompt, None, cwd, timeout, step_name=step_name
    )

    continuation_obj = (
        continuation_result.output
        if continuation_result.success and isinstance(continuation_result.output, dict)
        else None
    )
    if continuation_obj is None and continuation_result.raw_output:
        recovered, _ = _try_recover_json_ex(
            continuation_result.raw_output, continuation_result.error
        )
        if recovered is not None and not _looks_like_transport_envelope(recovered):
            continuation_obj = recovered

    merged = dict(partial)
    received_keys: list[str] = []
    continuation_applied = False

    if isinstance(continuation_obj, dict):
        for key in requested_keys:
            if key in continuation_obj:
                merged[key] = continuation_obj[key]
                received_keys.append(key)

        merged_keys = {k for k in merged.keys() if isinstance(k, str)}
        critical_blocks = ("resumen_ejecutivo", "decision_probabilistica", "gates")
        critical_ok = all(
            isinstance(merged.get(block), dict) and bool(merged.get(block))
            for block in critical_blocks
        )
        structure_ok = (
            merged.get("version_esquema") == "DecisionPacket_v2"
            and expected_keys.issubset(merged_keys)
            and critical_ok
        )
        if structure_ok:
            continuation_applied = True
            continuation_result.success = True
            continuation_result.output = merged
            continuation_result.error = None
        else:
            continuation_result.success = False
            missing_after = sorted(expected_keys - merged_keys)
            continuation_result.error = (
                "Truncation continuation did not produce a structurally valid "
                "DecisionPacket_v2; "
                f"missing_after={missing_after[:10]}"
            )
    else:
        continuation_result.success = False
        if not continuation_result.error:
            continuation_result.error = "Truncation continuation returned no JSON object"

    continuation_result.model_profile = model_profile
    continuation_result.failure_ctx = {
        **(failed_result.failure_ctx or {}),
        "truncation_detected": True,
        "continuation_applied": continuation_applied,
        "continuation_keys_requested": sorted(requested_keys),
        "continuation_keys_received": sorted(received_keys),
        "continuation_source_recovery_method": source_recovery_method,
    }
    return continuation_result


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
        # Gemini-specific quota errors
        "quota", "terminalquotaerror", "exhausted your capacity", "exhausted capacity",
    )
    return any(p in text for p in patterns)


def _is_quality_only_error(error: str | None) -> bool:
    """Returns True only when the error is clearly a model quality issue.

    Quality errors (bad JSON output, empty artifact) cannot be fixed by switching
    to a different CLI transport for the same model — copilot fallback is skipped.
    """
    if not error:
        return False
    text = error.lower()
    return any(p in text for p in (
        "json parse error",
        "could not parse json",
        "not json artifact",
        "artifact payload",
        "schema validation",
        "result is not json",
    ))


# ── v2: Core dispatch with retry + transport fallback ─────────


def _transport_satisfies_step(
    transport: "ModelTransport",
    step_requirements: set[str],
) -> bool:
    """Check if a transport's capabilities satisfy the step's requirements.

    Returns True when:
    - The step has no declared requirements (backward compat)
    - The transport's capabilities are a superset of the step's requirements
    Returns False when the transport lacks a required capability.
    """
    if not step_requirements:
        return True  # No requirements → anything goes
    caps = set(transport.capabilities)
    # "text_only" explicitly means no tools/web_access
    if "text_only" in caps:
        # text_only transport can only satisfy steps with no requirements
        return False
    return step_requirements.issubset(caps)


def _dispatch_model_with_retry(
    config: EngineConfig,
    model_profile: str,
    prompt: str,
    output_schema: Path | None = None,
    cwd: Path | None = None,
    timeout: int | None = None,
    step_name: str | None = None,
    skip_copilot_fallback: bool = False,
) -> DispatchResult:
    """Dispatch to a model with retry + copilot transport fallback.

    NEVER substitutes a different model. Only changes transport (CLI).

    Flow:
    1. Try primary transport with retries (same model, same CLI)
       - JSON recovery attempted between retries
    2. If all retries fail AND last error was a transport error AND
       copilot_transport_fallback=true AND skip_copilot_fallback=false
       → try same model via copilot CLI (Fix-B)
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
        result = backend.dispatch(
            prompt, output_schema, cwd, effective_timeout, step_name=step_name
        )
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
            recovered, recovery_method = _try_recover_json_ex(result.raw_output, result.error)
            if recovered is not None:
                method = recovery_method or "unknown_recovery"
                if _looks_like_transport_envelope(recovered):
                    # Try to unwrap the artifact from inside the envelope
                    unwrapped, unwrap_method = _unwrap_transport_envelope(recovered)
                    if unwrapped is not None and _is_viable_recovered_artifact(unwrapped):
                        print(
                            f"[dispatch] Artifact unwrapped from transport envelope for "
                            f"{model_profile} on attempt {attempt} (method={unwrap_method})",
                            file=sys.stderr,
                        )
                        result.success = True
                        result.output = unwrapped
                        result.attempts = attempts
                        attempts[-1]["recovered"] = unwrap_method
                        return result
                    result.success = False
                    result.output = None
                    result.error = (
                        f"Recovered output is transport envelope (method={method}); "
                        "not a valid artifact payload"
                    )
                    attempts[-1]["recovered"] = method
                    if method == "truncation_repair":
                        attempts[-1]["truncation_repaired"] = True
                        result.failure_ctx = {
                            **(result.failure_ctx or {}),
                            "truncation_repaired": True,
                            "recovery_method": method,
                            "model_profile": model_profile,
                            "backend": primary.transport_name,
                            "transport": primary.transport_name,
                            "attempts": attempts,
                            "decision_log": decision_log,
                            "last_error": result.error,
                        }
                    continue
                if not _is_viable_recovered_artifact(recovered):
                    print(
                        f"[dispatch] Recovered fragment rejected for {model_profile} "
                        f"(method={method}, keys={len(recovered)}): "
                        f"no version_esquema, likely sub-object",
                        file=sys.stderr,
                    )
                    attempts[-1]["recovered"] = f"{method}_rejected_fragment"
                    continue
                print(
                    f"[dispatch] JSON recovered for {model_profile} on attempt {attempt} "
                    f"(method={method})",
                    file=sys.stderr,
                )
                result.success = True
                result.output = recovered
                result.attempts = attempts
                attempts[-1]["recovered"] = method
                if method == "truncation_repair":
                    attempts[-1]["truncation_repaired"] = True
                    result.failure_ctx = {
                        **(result.failure_ctx or {}),
                        "truncation_repaired": True,
                        "recovery_method": method,
                        "model_profile": model_profile,
                        "backend": primary.transport_name,
                        "transport": primary.transport_name,
                        "attempts": attempts,
                        "decision_log": decision_log,
                        "last_error": result.error,
                    }
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

    # Phase 1.5: Truncation continuation for high-volume Claude steps.
    if (
        last_result is not None
        and step_name in _TRUNCATION_CONTINUATION_STEPS
        and backend.name == "claude"
        and isinstance(last_result.failure_ctx, dict)
        and last_result.failure_ctx.get("truncation_detected") is True
    ):
        continuation_result = _attempt_truncation_continuation(
            config=config,
            backend=backend,
            model_profile=model_profile,
            step_name=step_name,
            prompt=prompt,
            failed_result=last_result,
            output_schema=output_schema,
            cwd=cwd,
            timeout=effective_timeout,
        )
        if continuation_result is not None:
            continuation_result.transport = primary.transport_name
            continuation_result.attempt = len(attempts) + 1
            _record_attempt(
                "truncation_continuation",
                continuation_result.attempt,
                continuation_result,
                effective_timeout,
            )
            if attempts:
                attempts[-1]["continuation_applied"] = bool(
                    (continuation_result.failure_ctx or {}).get("continuation_applied")
                )
                attempts[-1]["continuation_keys_requested"] = (
                    (continuation_result.failure_ctx or {}).get("continuation_keys_requested", [])
                )
                attempts[-1]["continuation_keys_received"] = (
                    (continuation_result.failure_ctx or {}).get("continuation_keys_received", [])
                )

            if continuation_result.success:
                decision_log.append("truncation_continuation:success")
                continuation_result.attempts = attempts
                continuation_result.failure_ctx = {
                    **(continuation_result.failure_ctx or {}),
                    "model_profile": model_profile,
                    "backend": primary.transport_name,
                    "transport": primary.transport_name,
                    "attempts": attempts,
                    "decision_log": decision_log,
                    "last_error": None,
                }
                return continuation_result

            decision_log.append("truncation_continuation:failed")
            last_result = continuation_result

    # Fix-B: Phase 2 (copilot transport fallback) only for transport errors.
    # If the model produced bad JSON (quality failure), using the same model
    # via a different CLI won't help — skip copilot to avoid wasting tokens.
    #
    # A transport error is detected by either:
    #   a) text-pattern match in error/raw_output (rate limit, quota, timeout, etc.)
    #   b) non-zero exit_code that is NOT a model quality error (bad JSON, etc.)
    #      → any non-zero exit without a recognizable quality-error message is
    #        treated as an infrastructure/transport failure.
    last_is_transport_error = last_result is not None and (
        _is_retryable_dispatch_error(last_result.error, last_result.raw_output)
        or (
            last_result.exit_code not in (None, 0)
            and last_result.exit_code != 124  # 124 = timeout, already covered above
            and not _is_quality_only_error(last_result.error)
        )
    )

    # Mark this transport as unavailable so subsequent dispatch calls
    # (e.g., fusion) can skip it immediately instead of waiting for the
    # full timeout cycle again.
    if last_is_transport_error:
        config.mark_backend_unavailable(primary.transport_name)
        decision_log.append(f"transport_marked_unavailable:{primary.transport_name}")

    copilot_fallback_skipped = False
    # Automatic capability-aware gate: block copilot fallback when the step
    # requires capabilities that copilot cannot satisfy (e.g., tools, web_access).
    step_reqs = config.get_step_requirements(step_name) if step_name else set()
    if skip_copilot_fallback and config.copilot_transport_fallback and last_is_transport_error:
        decision_log.append("copilot_fallback:skipped_by_caller")
        copilot_fallback_skipped = True
    elif config.copilot_transport_fallback and last_is_transport_error and not skip_copilot_fallback:
        copilot = spec.copilot_transport
        if copilot and copilot.transport_name != primary.transport_name:
            # Check capabilities BEFORE attempting copilot dispatch
            if not _transport_satisfies_step(copilot, step_reqs):
                decision_log.append(
                    f"copilot_fallback:blocked_by_capabilities"
                    f"(requires={sorted(step_reqs)},caps={copilot.capabilities})"
                )
                copilot_fallback_skipped = True
                print(
                    f"[dispatch] Copilot fallback BLOCKED for {model_profile}/{step_name}: "
                    f"step requires {sorted(step_reqs)}, copilot only has {copilot.capabilities}",
                    file=sys.stderr,
                )
            else:
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
                        prompt, output_schema, cwd, effective_timeout, step_name=step_name
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
                        recovered, recovery_method = _try_recover_json_ex(
                            copilot_result.raw_output, copilot_result.error
                        )
                        if recovered is not None:
                            if _looks_like_transport_envelope(recovered):
                                # Try to unwrap artifact from inside the envelope
                                unwrapped, unwrap_method = _unwrap_transport_envelope(recovered)
                                if unwrapped is not None and _is_viable_recovered_artifact(unwrapped):
                                    print(
                                        f"[dispatch] Artifact unwrapped from transport envelope for "
                                        f"{model_profile} via copilot (method={unwrap_method})",
                                        file=sys.stderr,
                                    )
                                    copilot_result.success = True
                                    copilot_result.output = unwrapped
                                    if attempts:
                                        attempts[-1]["recovered"] = unwrap_method
                                    copilot_result.attempts = attempts
                                    return copilot_result
                                method = recovery_method or "unknown_recovery"
                                copilot_result.success = False
                                copilot_result.output = None
                                copilot_result.error = (
                                    f"Recovered output is transport envelope (method={method}); "
                                    "not a valid artifact payload"
                                )
                                if attempts:
                                    attempts[-1]["recovered"] = method
                                    if method == "truncation_repair":
                                        attempts[-1]["truncation_repaired"] = True
                                        copilot_result.failure_ctx = {
                                            **(copilot_result.failure_ctx or {}),
                                            "truncation_repaired": True,
                                            "recovery_method": method,
                                            "model_profile": model_profile,
                                            "backend": primary.transport_name,
                                            "transport": "copilot",
                                            "attempts": attempts,
                                            "decision_log": decision_log,
                                            "last_error": copilot_result.error,
                                        }
                                last_result = copilot_result
                            elif not _is_viable_recovered_artifact(recovered):
                                method = recovery_method or "unknown_recovery"
                                print(
                                    f"[dispatch] Recovered fragment rejected for {model_profile} via copilot "
                                    f"(method={method}, keys={len(recovered)}): "
                                    f"no version_esquema, likely sub-object",
                                    file=sys.stderr,
                                )
                                if attempts:
                                    attempts[-1]["recovered"] = f"{method}_rejected_fragment"
                                last_result = copilot_result
                            else:
                                method = recovery_method or "unknown_recovery"
                                print(
                                    f"[dispatch] JSON recovered for {model_profile} via copilot "
                                    f"(method={method})",
                                    file=sys.stderr,
                                )
                                copilot_result.success = True
                                copilot_result.output = recovered
                                if attempts:
                                    attempts[-1]["recovered"] = method
                                    if method == "truncation_repair":
                                        attempts[-1]["truncation_repaired"] = True
                                if method == "truncation_repair":
                                    copilot_result.failure_ctx = {
                                        **(copilot_result.failure_ctx or {}),
                                        "truncation_repaired": True,
                                        "recovery_method": method,
                                        "model_profile": model_profile,
                                        "backend": primary.transport_name,
                                        "transport": "copilot",
                                        "attempts": attempts,
                                        "decision_log": decision_log,
                                        "last_error": copilot_result.error,
                                    }
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
                **({"copilot_fallback_skipped": True} if copilot_fallback_skipped else {}),
            },
        )

    last_result.attempts = attempts
    if not isinstance(last_result.failure_ctx, dict):
        last_result.failure_ctx = {
            "model_profile": model_profile,
            "backend": primary.transport_name,
            "transport": last_result.transport or primary.transport_name,
            "attempts": attempts,
            "decision_log": decision_log,
            "last_error": last_result.error,
        }
    if copilot_fallback_skipped:
        last_result.failure_ctx["copilot_fallback_skipped"] = True
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
        return _dispatch_model_with_retry(
            config, fusion_model, prompt, output_schema, cwd, timeout,
            step_name=step_name,
            skip_copilot_fallback=True,
        )

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
                # If copilot_transport_fallback is enabled AND the model has a copilot
                # transport, don't filter it out here. _dispatch_model_with_retry() will
                # attempt the primary transport (which will return a 429/transport error),
                # detect it as retryable, and activate the copilot fallback automatically.
                has_copilot_path = False
                if config.copilot_transport_fallback and spec is not None:
                    copilot = spec.copilot_transport
                    if copilot and copilot.transport_name != transport_name:
                        has_copilot_path = True
                        print(
                            f"[dispatch] {model_profile} primary transport ({transport_name}) "
                            f"unavailable per preflight; copilot fallback path enabled — "
                            f"will attempt dispatch.",
                            file=sys.stderr,
                        )
                if not has_copilot_path:
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
                _dispatch_model_with_retry, config, model_profile, prompt, output_schema, cwd, timeout, step_name
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
        result = _dispatch_model_with_retry(
            config, model_profile, prompt, output_schema, cwd, timeout,
            step_name=step_name,
        )
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
    # model_profile -> candidate payload and original result
    successful_candidates: dict[str, dict] = {}
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
                successful_candidates[model_profile] = {
                    "model_profile": model_profile,
                    "backend_name": backend_name,
                    "output": normalized,
                    "result": result,
                }
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
            recovery_method = None
            if not config.is_v2 and result.raw_output:
                recovered, recovery_method = _try_recover_json_ex(result.raw_output, result.error)
            if recovered is not None:
                if not _is_viable_recovered_artifact(recovered):
                    method = recovery_method or "unknown_recovery"
                    print(
                        f"[dispatcher] Recovered fragment rejected for {backend_name} "
                        f"(method={method}, keys={len(recovered)}): "
                        f"no version_esquema, likely sub-object",
                        file=sys.stderr,
                    )
                    recovered = None
                    recovery_method = None
            if recovered is not None:
                if recovery_method and isinstance(result.failure_ctx, dict):
                    attempts_ctx = result.failure_ctx.get("attempts")
                    if isinstance(attempts_ctx, list) and attempts_ctx and isinstance(attempts_ctx[-1], dict):
                        attempts_ctx[-1]["recovered"] = recovery_method
                        if recovery_method == "truncation_repair":
                            attempts_ctx[-1]["truncation_repaired"] = True
                    result.failure_ctx.setdefault("recovery_method", recovery_method)
                    if recovery_method == "truncation_repair":
                        result.failure_ctx["truncation_repaired"] = True
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
                    successful_candidates[model_profile] = {
                        "model_profile": model_profile,
                        "backend_name": backend_name,
                        "output": normalized,
                        "result": result,
                    }
                else:
                    rejected_outputs[backend_name] = reason or "invalid artifact payload"
            else:
                print(
                    f"[dispatcher] WARNING: Backend {backend_name} (model_profile={model_profile}) "
                    f"failed for {step_name}: "
                    f"{result.error}",
                    file=sys.stderr,
                )
                # Save a failure trace so that diagnostic info is always available
                # (previously, failed dispatches left no trace file at all).
                if cwd:
                    fail_trace_path = cwd / f"_multi_{step_name}_{backend_name}_FAIL.json"
                    fail_trace = {
                        "model_profile": model_profile,
                        "backend": backend_name,
                        "step": step_name,
                        "success": False,
                        "error": result.error,
                        "exit_code": result.exit_code,
                        "duration_s": result.duration_s,
                        "transport": result.transport,
                        "routed_via": result.routed_via,
                        "failure_ctx": result.failure_ctx,
                    }
                    try:
                        fail_trace_path.write_text(json.dumps(fail_trace, indent=2, ensure_ascii=False, default=str))
                        print(f"[dispatcher] Saved failure trace: {fail_trace_path.name}")
                    except OSError:
                        pass

    if not successful_candidates:
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

    if len(successful_candidates) < min_backends:
        print(
            f"[dispatch] WARNING: {step_name} has only {len(successful_candidates)} valid output(s) "
            f"(min {min_backends}). Proceeding with available outputs.",
            file=sys.stderr,
        )

    used = sorted(successful_outputs.keys())

    def _pick_fallback_candidate() -> dict | None:
        priority_profiles: list[str] = []
        if config.is_v2:
            priority_profiles.extend(config.get_models_for_step(step_name))
        priority_profiles.extend(list(multi_results.keys()))

        seen: set[str] = set()
        for profile in priority_profiles:
            if profile in seen:
                continue
            seen.add(profile)
            candidate = successful_candidates.get(profile)
            if candidate is not None:
                return candidate

        return next(iter(successful_candidates.values()), None)

    if len(successful_candidates) == 1:
        single_candidate = next(iter(successful_candidates.values()))
        original = single_candidate.get("result")
        fallback_output = single_candidate.get("output")
        if original is None or fallback_output is None:
            return DispatchResult(
                False, None, "", "none", "fusion", 0.0,
                "Internal dispatch mapping inconsistency"
            )
        return DispatchResult(
            success=original.success,
            output=fallback_output,
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

    # Step 4: Dispatch fusion (with model cascade in v2)
    fusion_timeout = _get_timeout(config, "FUSION")
    if config.is_v2:
        # Optional cap to avoid very long fusion hangs (especially on transport fallback).
        cap_raw = (config.raw.get("execution", {}) or {}).get("fusion_timeout_cap_seconds")
        try:
            cap_val = int(cap_raw) if cap_raw is not None else None
        except (TypeError, ValueError):
            cap_val = None
        if cap_val and cap_val > 0:
            fusion_timeout = min(fusion_timeout, cap_val)

    # Step 4b: State shared across both v2 cascade and v1 single-shot paths.
    fusion_attempts_summary: list[dict] = []
    last_fusion_error: str | None = None
    had_invalid_fusion_payload = False
    last_fusion_result: DispatchResult | None = None

    def _evaluate_fusion_result(
        fmodel: str, fresult: DispatchResult
    ) -> DispatchResult | None:
        """Validate a fusion result and return it if valid, else None.

        Side-effects: updates fusion_attempts_summary, last_fusion_error,
        had_invalid_fusion_payload, last_fusion_result (via nonlocal).
        Returns the result if valid so the caller can do ``return``, else None.
        """
        nonlocal last_fusion_error, had_invalid_fusion_payload, last_fusion_result
        last_fusion_result = fresult
        fresult.backends_used = used

        attempt_item: dict[str, object] = {
            "model_profile": fmodel,
            "success": bool(fresult.success),
            "transport": fresult.transport,
            "routed_via": fresult.routed_via,
            "duration_s": fresult.duration_s,
            "error": fresult.error,
        }

        if fresult.success:
            fused_output = fresult.output if isinstance(fresult.output, dict) else None
            normalized_fused_output = _normalize_backend_output(fused_output) if fused_output else None
            is_valid_fused, fused_reason = _validate_multi_candidate(
                config, step_name, normalized_fused_output
            )
            if is_valid_fused:
                if fused_output is not None and normalized_fused_output is not None:
                    fresult.output = normalized_fused_output
                fusion_attempts_summary.append(attempt_item)
                base_ctx = fresult.failure_ctx if isinstance(fresult.failure_ctx, dict) else {}
                fresult.failure_ctx = {
                    **base_ctx,
                    "step_context": {
                        "step": step_name,
                        "mode": "multi_fusion",
                    },
                    "fusion_attempts": fusion_attempts_summary,
                }
                return fresult

            had_invalid_fusion_payload = True
            invalid_reason = fused_reason or "fusion_output_invalid"
            attempt_item["validation_error"] = invalid_reason
            last_fusion_error = f"Fusion output invalid via {fmodel}: {invalid_reason}"
            print(
                f"[dispatch] WARNING: Fusion output for {step_name} invalid via {fmodel} "
                f"({invalid_reason}). Trying next fusion candidate.",
                file=sys.stderr,
            )
        else:
            last_fusion_error = fresult.error or f"Fusion dispatch failed via {fmodel}"

        fusion_attempts_summary.append(attempt_item)
        return None

    if config.is_v2:
        fusion_models: list[str] = []
        primary_fusion = config.get_fusion_model_for_step(step_name)
        for candidate in [primary_fusion, *config.get_models_for_step(step_name)]:
            if candidate and candidate not in fusion_models:
                fusion_models.append(candidate)

        for idx, fusion_model in enumerate(fusion_models, start=1):
            # Early-skip: if this model's transport was marked unavailable during
            # the multi-model phase (e.g., Claude auth failed), skip it immediately
            # instead of waiting for the full timeout cycle.
            transport_name = config.resolve_transport_name(fusion_model)
            if config.preflight_done() and not config.is_backend_available(transport_name):
                print(
                    f"[dispatch] Skipping fusion via {fusion_model}: "
                    f"transport {transport_name} marked unavailable",
                    file=sys.stderr,
                )
                skipped = DispatchResult(
                    False, None, "", fusion_model, transport_name, 0.0,
                    f"Transport {transport_name} unavailable (skipped)",
                    model_profile=fusion_model,
                    transport=transport_name,
                )
                last_fusion_result = skipped
                last_fusion_error = skipped.error or f"Fusion dispatch failed via {fusion_model}"
                fusion_attempts_summary.append({
                    "model_profile": fusion_model,
                    "success": False,
                    "transport": transport_name,
                    "routed_via": None,
                    "duration_s": 0.0,
                    "error": skipped.error,
                })
                continue

            is_last = (idx == len(fusion_models))
            print(
                f"[dispatch] Fusion for {step_name} attempt {idx}/{len(fusion_models)} → {fusion_model}",
                file=sys.stderr,
            )
            fusion_result = _dispatch_model_with_retry(
                config, fusion_model, fusion_prompt, output_schema, cwd,
                fusion_timeout,
                step_name=step_name,
                # Allow copilot fallback only on the last fusion attempt as a
                # final rescue path (copilot backend now has prompt wrapping for
                # structured JSON output).
                skip_copilot_fallback=not is_last,
            )
            # Validate immediately — return on first valid result (true cascade).
            valid = _evaluate_fusion_result(fusion_model, fusion_result)
            if valid is not None:
                return valid
    else:
        fusion_result = dispatch_step(config, "FUSION", fusion_prompt, output_schema, cwd)
        if isinstance(fusion_result, dict):
            fusion_result = list(fusion_result.values())[0]
        valid = _evaluate_fusion_result("FUSION", fusion_result)
        if valid is not None:
            return valid

    # Fallback: fusion failed but we have valid per-model candidates.
    fallback_candidate = _pick_fallback_candidate()
    if fallback_candidate is not None:
        fallback_result = fallback_candidate.get("result")
        fallback_output = fallback_candidate.get("output")
        fallback_backend = fallback_candidate.get("backend_name")
        if fallback_result is not None and fallback_output is not None:
            fallback_reason = "fusion_output_invalid" if had_invalid_fusion_payload else "fusion_dispatch_failed"
            print(
                f"[dispatch] WARNING: Fusion failed for {step_name}; using validated candidate "
                f"from {fallback_backend} ({fallback_reason}).",
                file=sys.stderr,
            )
            return DispatchResult(
                True,
                fallback_output,
                fallback_result.raw_output or (last_fusion_result.raw_output if last_fusion_result else ""),
                fallback_result.model,
                fallback_result.backend,
                fallback_result.duration_s,
                None,
                backends_used=used,
                routed_via="multi_candidate_fallback",
                fallback_reason=fallback_reason,
                model_profile=fallback_result.model_profile,
                transport=fallback_result.transport,
                exit_code=fallback_result.exit_code,
                attempt=fallback_result.attempt,
                attempts=fallback_result.attempts,
                failure_ctx={
                    "step_context": {
                        "step": step_name,
                        "mode": "multi_fusion_fallback",
                        "source": "valid_candidate",
                    },
                    "fusion_fallback_backend": fallback_backend,
                    "fusion_last_error": last_fusion_error,
                    "fusion_attempts": fusion_attempts_summary,
                },
            )

    # Defensive fail-closed (should only happen if no valid candidates exist).
    return DispatchResult(
        False,
        None,
        last_fusion_result.raw_output if last_fusion_result else "",
        last_fusion_result.model if last_fusion_result else "none",
        last_fusion_result.backend if last_fusion_result else "fusion",
        last_fusion_result.duration_s if last_fusion_result else 0.0,
        last_fusion_error or f"Fusion failed for {step_name}",
        backends_used=used,
        model_profile=last_fusion_result.model_profile if last_fusion_result else None,
        transport=last_fusion_result.transport if last_fusion_result else None,
        failure_ctx={
            "step_context": {
                "step": step_name,
                "mode": "multi_fusion",
            },
            "fusion_attempts": fusion_attempts_summary,
            "last_error": last_fusion_error or f"Fusion failed for {step_name}",
        },
    )


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
        period = (filing.get("fecha_publicacion") or "?")[:10]
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

        prompt, excerpt_meta = build_filing_prompt(
            filing_path=filing_path,
            source_entry=filing_entry,
            ticker=filing_entry.get("ticker", "UNKNOWN"),
            instrucciones_dir=instrucciones_dir,
        )
        _append_prompt_excerpt_meta(
            case_dir,
            {
                "ts_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "step": "TP_EXTRACTOR_FILING",
                "source_id": filing_entry.get("source_id"),
                "ticker": filing_entry.get("ticker"),
                "filing_type": filing_entry.get("tipo", filing_entry.get("form_type")),
                "local_path": local_path,
                "excerpt_meta": excerpt_meta,
            },
        )

        if config.is_v2:
            # Fix-A: Delegate to the central orchestrator for retry + transport fallback.
            # _dispatch_model_with_retry handles: retry on transport errors, copilot
            # fallback (Fix-B gated), and JSON recovery — all in one consistent place.
            return _dispatch_model_with_retry(
                config, model_profile, prompt, cwd=case_dir, timeout=timeout,
                step_name="TP_EXTRACTOR_FILING",
            )
        else:
            # v1: Direct backend dispatch with simple retry loop
            attempts = 0
            while True:
                result = backend.dispatch(prompt, cwd=case_dir, timeout=timeout)
                if result.success:
                    return result
                if not result.success and result.raw_output:
                    recovered, recovery_method = _try_recover_json_ex(result.raw_output, result.error)
                    if recovered is not None:
                        result.success, result.output = True, recovered
                        if recovery_method:
                            if not isinstance(result.failure_ctx, dict):
                                result.failure_ctx = {}
                            result.failure_ctx["recovery_method"] = recovery_method
                            if recovery_method == "truncation_repair":
                                result.failure_ctx["truncation_repaired"] = True
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
                    recovered, recovery_method = _try_recover_json_ex(result.raw_output, result.error)
                    if recovered is not None:
                        recovery_ctx = None
                        if recovery_method:
                            recovery_ctx = {"recovery_method": recovery_method}
                            if recovery_method == "truncation_repair":
                                recovery_ctx["truncation_repaired"] = True
                        result = DispatchResult(
                            success=True, output=recovered, raw_output=result.raw_output,
                            model=result.model, backend=result.backend, duration_s=result.duration_s,
                            failure_ctx=recovery_ctx,
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
