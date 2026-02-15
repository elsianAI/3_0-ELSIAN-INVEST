"""Despacha sub-tareas a backends según task_routing config.

Implements §3.9 of PLAN COMPLETO.
"""

from __future__ import annotations

import concurrent.futures
import json
import sys
from pathlib import Path

from .config import EngineConfig, get_step_config
from .prompt_builder import build_prompt, build_fusion_prompt, build_filing_prompt
from .validator import validate_artifact
from .backends.base import DispatchResult, LLMBackend
from .backends.codex import CodexBackend
from .backends.gemini import GeminiBackend
from .backends.claude import ClaudeBackend

BACKEND_CLASSES = {
    "codex": CodexBackend,
    "gemini": GeminiBackend,
    "claude": ClaudeBackend,
}


def dispatch_step(
    config: EngineConfig,
    step_name: str,
    prompt: str,
    output_schema: Path | None = None,
    cwd: Path | None = None,
) -> DispatchResult | dict[str, DispatchResult]:
    """
    Mira step_routing[step_name]:
    - Si multi=false: usa primer backend disponible, retorna DispatchResult
    - Si multi=true: ejecuta en TODOS los backends, retorna {backend: DispatchResult}
    - Si backend="python": raise ValueError (runner lo maneja directamente)
    """
    step_cfg = get_step_config(config, step_name)
    backends_list = step_cfg.get("backends", [])
    is_multi = step_cfg.get("multi", False)

    if "python" in backends_list:
        raise ValueError(
            f"Step {step_name} uses 'python' backend — "
            "should be executed as a runner, not dispatched to LLM."
        )

    # Get timeout for this step
    timeout = _get_timeout(config, step_name)

    if is_multi:
        # Dispatch to ALL available backends in parallel
        results = {}
        available_backends = []
        for backend_name in backends_list:
            backend = _get_backend(config, backend_name)
            if backend and backend.check_available():
                available_backends.append((backend_name, backend))
            else:
                print(
                    f"[dispatcher] WARNING: Backend {backend_name} not available for {step_name}",
                    file=sys.stderr,
                )

        if not available_backends:
            return DispatchResult(
                False, None, "", "none", "none", 0.0,
                f"No available backends for {step_name}"
            )

        max_workers = config.execution.get("max_parallel_backends", 3)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_name = {
                executor.submit(
                    backend.dispatch, prompt, output_schema, cwd, timeout
                ): name
                for name, backend in available_backends
            }
            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    results[name] = future.result()
                except Exception as e:
                    results[name] = DispatchResult(
                        False, None, "", "unknown", name, 0.0, str(e)
                    )

        return results

    else:
        # Use first available backend
        for backend_name in backends_list:
            backend = _get_backend(config, backend_name)
            if backend and backend.check_available():
                return backend.dispatch(prompt, output_schema, cwd, timeout)

        return DispatchResult(
            False, None, "", "none", "none", 0.0,
            f"No available backends for {step_name}: tried {backends_list}"
        )


def dispatch_multi_and_fuse(
    config: EngineConfig,
    step_name: str,
    prompt: str,
    instrucciones_dir: Path,
    output_schema: Path | None = None,
    cwd: Path | None = None,
) -> DispatchResult:
    """
    1. Despacha a N backends en paralelo
    2. Recoge resultados {backend: output_json}
    3. Construye fusion prompt
    4. Despacha fusion prompt al backend de FUSION
    5. Retorna resultado fusionado
    """
    # Step 1: Dispatch to all backends
    multi_results = dispatch_step(config, step_name, prompt, output_schema, cwd)

    if isinstance(multi_results, DispatchResult):
        # Single result (shouldn't happen for multi, but handle gracefully)
        return multi_results

    # Step 2: Collect successful outputs
    successful_outputs = {}
    for backend_name, result in multi_results.items():
        if result.success and result.output:
            successful_outputs[backend_name] = result.output
        else:
            print(
                f"[dispatcher] WARNING: Backend {backend_name} failed for {step_name}: "
                f"{result.error}",
                file=sys.stderr,
            )

    if not successful_outputs:
        return DispatchResult(
            False, None, "", "none", "fusion", 0.0,
            f"All backends failed for {step_name}"
        )

    if len(successful_outputs) == 1:
        # Only one succeeded — no fusion needed
        backend_name = list(successful_outputs.keys())[0]
        return multi_results[backend_name]

    # Step 3: Build fusion prompt
    fusion_prompt = build_fusion_prompt(successful_outputs, step_name, instrucciones_dir)

    # Step 4: Dispatch fusion
    fusion_result = dispatch_step(config, "FUSION", fusion_prompt, output_schema, cwd)

    if isinstance(fusion_result, dict):
        # Shouldn't happen for FUSION (multi=false), take first
        fusion_result = list(fusion_result.values())[0]

    return fusion_result


def dispatch_parallel_filings(
    config: EngineConfig,
    filings: list[dict],
    instrucciones_dir: Path,
    case_dir: Path,
) -> list[DispatchResult]:
    """
    Para TP_EXTRACTOR con parallel_by="filing":
    1. Por cada filing → build_filing_prompt()
    2. Despacha en paralelo (max_parallel_filings del config)
    3. Retorna lista de DispatchResult por filing
    """
    max_parallel = config.execution.get("max_parallel_filings", 4)
    timeout = config.timeouts.get("tp_extractor_per_filing", 180)

    # Get the backend for TP_EXTRACTOR_FILING
    step_cfg = get_step_config(config, "TP_EXTRACTOR_FILING")
    backend_name = step_cfg["backends"][0]
    backend = _get_backend(config, backend_name)

    if not backend or not backend.check_available():
        return [
            DispatchResult(
                False, None, "", "none", "none", 0.0,
                f"Backend {backend_name} not available for TP_EXTRACTOR_FILING"
            )
        ]

    def _process_filing(filing_entry: dict) -> DispatchResult:
        local_path = filing_entry.get("local_path")
        if local_path:
            filing_path = case_dir.parent.parent.parent / local_path
        else:
            filing_path = Path("/dev/null")  # Will be handled by prompt builder

        prompt = build_filing_prompt(
            filing_path=filing_path,
            source_entry=filing_entry,
            ticker=filing_entry.get("ticker", "UNKNOWN"),
            instrucciones_dir=instrucciones_dir,
        )
        return backend.dispatch(prompt, cwd=case_dir, timeout=timeout)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
        future_to_idx = {
            executor.submit(_process_filing, filing): i
            for i, filing in enumerate(filings)
        }
        # Collect in order
        result_map = {}
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result_map[idx] = future.result()
            except Exception as e:
                result_map[idx] = DispatchResult(
                    False, None, "", "unknown", "unknown", 0.0, str(e)
                )

        results = [result_map[i] for i in range(len(filings))]

    return results


def _get_backend(config: EngineConfig, backend_name: str) -> LLMBackend | None:
    """Instancia backend con binary_path y model resueltos del config."""
    cls = BACKEND_CLASSES.get(backend_name)
    if cls is None:
        return None

    binary_info = config.binaries.get(backend_name)
    if binary_info is None or not binary_info.available:
        return None

    model_cfg = config.get_backend_config(backend_name)
    model = model_cfg.get("default_model", "")
    return cls(
        binary_path=binary_info.path,
        model=model,
        config=config.raw,
    )


def _get_timeout(config: EngineConfig, step_name: str) -> int:
    """Get appropriate timeout for a step."""
    # Check task_routing for per-task timeout
    routing = config.task_routing.get(step_name, {})
    if "timeout" in routing:
        return routing["timeout"]

    # Check backend config timeout
    model_name = config.get_model_for_task(step_name)
    model_cfg = config.get_backend_config(model_name)
    if model_cfg and "timeout_seconds" in model_cfg:
        return model_cfg["timeout_seconds"]

    return 600  # Global fallback


def _should_escalate(config: EngineConfig, step_name: str, result: DispatchResult) -> bool:
    """Determina si se debe escalar a otro modelo basándose en la escalation config."""
    esc = config.get_escalation_config(step_name)
    if not esc:
        return False

    condition = esc.get("escalate_condition", "")

    if condition == "score < 5":
        if result.success and result.output:
            try:
                data = result.output if isinstance(result.output, dict) else json.loads(result.output)
                score = data.get("score", data.get("Score", 10))
                return float(score) < 5
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

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
    """Dispatch step, then check escalation conditions and retry if needed."""
    result = dispatch_step(config, step_name, prompt, output_schema, cwd)
    if isinstance(result, dict):
        # Multi-model result — escalation not applicable
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
