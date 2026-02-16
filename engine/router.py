"""DAG del pipeline — decide flujo de ejecución.

Implements §3.5 of PLAN COMPLETO.
"""

from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

from .config import EngineConfig, get_step_config
from .state import (
    load_state, save_state, mark_step_done, mark_step_failed,
    mark_step_in_progress, mark_pipeline_status, update_decision_fields,
    get_next_step, init_state,
    PIPELINE_STEPS, SUB_STEPS,
)
from .dispatcher import (
    dispatch_step, dispatch_multi_and_fuse, dispatch_parallel_filings,
    dispatch_with_escalation,
)
from .prompt_builder import build_prompt
from .validator import validate_artifact, validate_file, validate_inter_step, validate_partial_truthpack
from .changelog import append_entry
from .dashboard import generate_dashboard
from .quality_voting import maybe_vote_step

# DAG de dependencias entre steps principales
PIPELINE_DAG = {
    "SOURCES":    {"depends_on": [],                           "parallel_with": []},
    "TRUTH_PACK": {"depends_on": ["SOURCES"],                  "parallel_with": []},
    "IMPLIED":    {"depends_on": ["TRUTH_PACK"],               "parallel_with": []},
    "CATALYST":   {"depends_on": ["IMPLIED"],                  "parallel_with": ["FORENSIC"]},
    "FORENSIC":   {"depends_on": ["IMPLIED"],                  "parallel_with": ["CATALYST"]},
    "BULL":       {"depends_on": ["CATALYST", "FORENSIC"],     "parallel_with": []},
    "RED_TEAM":   {"depends_on": ["BULL"],                     "parallel_with": []},
    "ARBITRO":    {"depends_on": ["RED_TEAM"],                 "parallel_with": []},
}

# Map steps to their input artifacts
STEP_INPUT_ARTIFACTS = {
    "SOURCES_COMPILER": ["_sec_fetcher_output", "_market_data_output", "_transcript_finder_output"],
    "TP_EXTRACTOR_FILING": ["SourcesPack_v1"],
    "IMPLIED": ["TruthPack_v1"],
    "CATALYST_DETECTION": ["TruthPack_v1", "ImpliedExpectations_v1"],
    "CATALYST_SCORING": ["TruthPack_v1", "ImpliedExpectations_v1"],
    "FORENSIC_DETECTION": ["TruthPack_v1", "ImpliedExpectations_v1"],
    "FORENSIC_SCORING": ["TruthPack_v1", "ImpliedExpectations_v1"],
    "BULL": ["TruthPack_v1", "ImpliedExpectations_v1", "AgentReport_v1_CATALYST", "AgentReport_v1_FORENSIC"],
    "RED_TEAM": ["TruthPack_v1", "AgentReport_v1_BULL"],
    "ARBITRO": ["TruthPack_v1", "AgentReport_v1_BULL", "AgentReport_v1_REDTEAM",
                "AgentReport_v1_CATALYST", "AgentReport_v1_FORENSIC", "ImpliedExpectations_v1"],
}


def execute_pipeline(config: EngineConfig, case_dir: Path, ticker: str, date_str: str) -> dict:
    """
    Ejecuta pipeline completo para un caso.
    Supports parallel execution of CATALYST||FORENSIC.
    """
    # 1. Init state
    state = init_state(case_dir, ticker, date_str)
    mark_pipeline_status(case_dir, "EN_PROGRESO")
    print(f"[pipeline] Initialized case: {state['caso_id']}")

    results = {}

    # 2. Execute steps in DAG order, with parallel groups
    i = 0
    while i < len(PIPELINE_STEPS):
        step_name = PIPELINE_STEPS[i]

        if not is_step_ready(case_dir, step_name):
            print(f"[pipeline] Skipping {step_name} — dependencies not met")
            i += 1
            continue

        # Check for parallel group
        parallel_group = get_parallel_group(step_name)
        ready_parallels = [
            s for s in parallel_group
            if s != step_name and is_step_ready(case_dir, s)
        ]

        if ready_parallels:
            # Execute parallel group (e.g., CATALYST & FORENSIC)
            group = [step_name] + ready_parallels
            print(f"\n[pipeline] ═══ Executing parallel: {' || '.join(group)} ═══")

            parallel_results = _execute_parallel_steps(config, case_dir, group, ticker)

            all_ok = True
            for s, res in parallel_results.items():
                results[s] = res
                if res.get("success"):
                    mark_step_done(case_dir, s, model=res.get("model", "unknown"))
                    print(f"[pipeline] ✓ {s} completed")
                else:
                    mark_step_failed(case_dir, s, res.get("error", "unknown"))
                    print(f"[pipeline] ✗ {s} failed: {res.get('error')}")
                    all_ok = False

            if not all_ok and config.execution.get("fail_fast", True):
                print("[pipeline] fail_fast=true — stopping pipeline")
                break

            # Skip past parallel steps
            i += len(group)
            continue

        print(f"\n[pipeline] ═══ Executing: {step_name} ═══")

        try:
            step_result = execute_step(config, case_dir, step_name, ticker)
            results[step_name] = step_result

            if step_result.get("success"):
                mark_step_done(case_dir, step_name, model=step_result.get("model", "unknown"))
                print(f"[pipeline] ✓ {step_name} completed")
                # Extract decision fields from ARBITRO
                if step_name == "ARBITRO":
                    _extract_decision_fields(case_dir, step_result)
            else:
                mark_step_failed(case_dir, step_name, step_result.get("error", "unknown"))
                print(f"[pipeline] ✗ {step_name} failed: {step_result.get('error')}")
                if config.execution.get("fail_fast", True):
                    print("[pipeline] fail_fast=true — stopping pipeline")
                    break
        except Exception as e:
            print(f"[pipeline] ✗ {step_name} exception: {e}", file=sys.stderr)
            mark_step_failed(case_dir, step_name, str(e))
            if config.execution.get("fail_fast", True):
                break

        i += 1

    # 3. Quality audit
    try:
        _run_quality_audit(config, case_dir)
    except Exception as e:
        print(f"[pipeline] Quality audit failed: {e}", file=sys.stderr)

    # 4. Final state
    final_state = load_state(case_dir)
    all_done = all(
        final_state.get("pipeline", {}).get(s, {}).get("estado") == "DONE"
        for s in PIPELINE_STEPS
    )
    if all_done:
        mark_pipeline_status(case_dir, "COMPLETO")
    elif any(
        final_state.get("_errors", {}).get(s) for s in PIPELINE_STEPS
    ):
        mark_pipeline_status(case_dir, "FALLIDO")

    final_state = load_state(case_dir)
    print(f"\n[pipeline] Final status: {final_state['estado_pipeline']}")
    return {"state": final_state, "step_results": results}


def execute_step(config: EngineConfig, case_dir: Path, step_name: str, ticker: str) -> dict:
    """Ejecuta un step individual (principal o sub-step group)."""
    # Check if step has sub-steps
    if step_name in SUB_STEPS:
        return _execute_step_group(config, case_dir, step_name, ticker)

    return _execute_single_step(config, case_dir, step_name, ticker)


def _execute_step_group(config: EngineConfig, case_dir: Path, group_name: str, ticker: str) -> dict:
    """Execute a group of sub-steps (e.g., SOURCES → PREFETCH + SOURCES_COMPILER).

    Skips sub-steps that are already DONE (for continue/retry scenarios).
    """
    sub_steps = SUB_STEPS[group_name]
    results = {}
    state = load_state(case_dir)

    for sub_step in sub_steps:
        # Skip already-done sub-steps
        ss_status = state.get("sub_steps", {}).get(sub_step, {}).get("status", "PENDING")
        if ss_status == "DONE":
            print(f"[pipeline]   → Sub-step: {sub_step} (already DONE, skipping)")
            continue

        print(f"[pipeline]   → Sub-step: {sub_step}")
        mark_step_in_progress(case_dir, sub_step)

        try:
            result = _execute_single_step(config, case_dir, sub_step, ticker)
            results[sub_step] = result

            if result.get("success"):
                mark_step_done(case_dir, sub_step, model=result.get("model", "python"))
                append_entry(
                    config.get_path("changelog"),
                    ticker, "PIPELINE", sub_step,
                    result.get("model", "python"),
                )

                # Gate post-TP_VALIDATOR: verificar data_quality del TruthPack
                if sub_step == "TP_VALIDATOR":
                    dq_result = _check_truthpack_quality(case_dir, ticker)
                    if dq_result == "FAIL":
                        mark_step_failed(case_dir, sub_step, "TruthPack data_quality: FAIL")
                        if config.execution.get("fail_fast", True):
                            return {"success": False, "error": "TruthPack data_quality FAIL", "results": results}
                    elif dq_result == "PARTIAL":
                        print(f"[pipeline]   ⚠ TruthPack data_quality: PARTIAL — pipeline continúa", file=sys.stderr)
                    elif dq_result is None:
                        gate_missing = config.execution.get("tp_quality_gate_missing", "fail")
                        if gate_missing == "warn":
                            print(f"[pipeline]   ⚠ No se pudo leer data_quality del TruthPack — gate inactivo (tp_quality_gate_missing=warn)", file=sys.stderr)
                        else:
                            mark_step_failed(case_dir, sub_step, "TruthPack data_quality: no disponible")
                            if config.execution.get("fail_fast", True):
                                return {"success": False, "error": "TruthPack data_quality no disponible — gate fail-closed", "results": results}
            else:
                mark_step_failed(case_dir, sub_step, result.get("error", "unknown"))
                if config.execution.get("fail_fast", True):
                    return {"success": False, "error": f"Sub-step {sub_step} failed", "results": results}
        except Exception as e:
            mark_step_failed(case_dir, sub_step, str(e))
            if config.execution.get("fail_fast", True):
                return {"success": False, "error": str(e), "results": results}

    return {"success": True, "results": results}


def _execute_single_step(config: EngineConfig, case_dir: Path, step_name: str, ticker: str) -> dict:
    """Execute a single step (either Python runner or LLM dispatch)."""
    step_cfg = get_step_config(config, step_name)
    backends = step_cfg.get("backends", [])
    is_multi = step_cfg.get("multi", False)
    parallel_by = step_cfg.get("parallel_by")

    # Inter-step validation (solo para steps con checks configurados)
    input_artifacts = _resolve_input_artifacts(case_dir, step_name)
    loaded_artifacts = {}
    for art_name, art_path in input_artifacts.items():
        try:
            loaded_artifacts[art_name] = json.loads(art_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    if loaded_artifacts:
        passed, errors, warnings = validate_inter_step(step_name, loaded_artifacts)
        for w in warnings:
            print(f"[router] ⚠ inter-step warning ({step_name}): {w}", file=sys.stderr)
        if not passed:
            return {"success": False, "error": f"Inter-step validation failed: {'; '.join(errors)}"}

    # Python runner — execute directly
    if "python" in backends:
        return _run_python_step(config, case_dir, step_name, ticker)

    # Parallel by filing
    if parallel_by == "filing":
        return _run_parallel_filing_step(config, case_dir, step_name, ticker)

    # Build prompt
    instrucciones_dir = config.get_path("instrucciones")
    schemas_dir = config.get_path("schemas")
    input_artifacts = _resolve_input_artifacts(case_dir, step_name)

    prompt = build_prompt(
        step_name=step_name,
        ticker=ticker,
        case_dir=case_dir,
        instrucciones_dir=instrucciones_dir,
        schemas_dir=schemas_dir,
        input_artifacts=input_artifacts,
    )

    # Multi-model dispatch + fusion
    if is_multi:
        result = dispatch_multi_and_fuse(
            config, step_name, prompt, instrucciones_dir,
            cwd=case_dir,
        )
    elif config.get_escalation_config(step_name):
        # Use escalation-aware dispatch
        result = dispatch_with_escalation(config, step_name, prompt, cwd=case_dir)
    else:
        result = dispatch_step(config, step_name, prompt, cwd=case_dir)
        if isinstance(result, dict):
            result = list(result.values())[0]

    # Process result
    if result.success and result.output:
        # Save artifact
        artifact_name = _get_artifact_filename(step_name, ticker, case_dir)
        artifact_path = case_dir / artifact_name
        artifact_path.write_text(
            json.dumps(result.output, indent=2, ensure_ascii=False)
        )

        # Validate
        schemas_dir = config.get_path("schemas")
        schema_name = _infer_schema_for_step(step_name)
        if schema_name:
            is_valid, errors = validate_artifact(result.output, schema_name, schemas_dir)
            if not is_valid:
                print(f"[router] WARNING: Artifact validation failed: {errors}", file=sys.stderr)

        # Quality voting (report-only): nunca bloquear pipeline por fallos de voting
        try:
            maybe_vote_step(
                config=config,
                case_dir=case_dir,
                step_name=step_name,
                artifact_payload=result.output,
                artifact_path=artifact_path,
                model=result.model,
                backend=result.backend,
            )
        except Exception as exc:
            print(f"[router] WARNING: quality voting failed for {step_name}: {exc}", file=sys.stderr)

        return {
            "success": True,
            "model": result.model,
            "backend": result.backend,
            "duration_s": result.duration_s,
            "artifact": artifact_name,
        }
    else:
        return {
            "success": False,
            "error": result.error or "No output",
            "model": result.model,
            "backend": result.backend,
        }


def _run_python_step(config: EngineConfig, case_dir: Path, step_name: str, ticker: str) -> dict:
    """Execute a Python-only runner step."""
    runner_map = {
        "PREFETCH": "scripts/runners/prefetch_runner.py",
        "SOURCES_COMPILER": "scripts/runners/sources_compiler_runner.py",
        "TP_CALCULATOR": "scripts/runners/tp_calculator.py",
        "TP_VALIDATOR": "scripts/runners/tp_validator.py",
        "TP_EXTRACTOR_MERGER": "scripts/runners/tp_extractor_merger.py",
    }

    runner_path = runner_map.get(step_name)
    if not runner_path:
        return {"success": False, "error": f"No runner mapped for {step_name}"}

    full_runner_path = config.workspace / runner_path
    if not full_runner_path.exists():
        return {"success": False, "error": f"Runner not found: {full_runner_path}"}

    # Build args based on step
    args = _build_runner_args(step_name, case_dir, ticker, config)

    cmd = [sys.executable, str(full_runner_path)] + args

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(config.workspace),
        )

        if proc.returncode == 0:
            return {"success": True, "model": "python", "output": proc.stdout[:1000]}
        else:
            return {
                "success": False,
                "error": f"Runner exit code {proc.returncode}: {proc.stderr[:500]}",
                "model": "python",
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Runner timeout", "model": "python"}
    except Exception as e:
        return {"success": False, "error": str(e), "model": "python"}


def _select_filings(filings: list[dict], config: EngineConfig) -> list[dict]:
    """Filter and prioritize filings to reduce unnecessary LLM calls.

    Uses tp_extractor_max_per_type from config to cap filings per type.
    Within each type, keeps the most recent by fecha_publicacion.
    """
    max_per_type = config.raw.get("tp_extractor_max_per_type", {})
    if not max_per_type:
        return filings  # no limits configured — pass all through

    default_max = max_per_type.get("_default", 999)

    # Group by type
    by_type: dict[str, list[dict]] = {}
    for f in filings:
        ftype = f.get("tipo", f.get("type", "UNKNOWN"))
        by_type.setdefault(ftype, []).append(f)

    selected = []
    skipped_count = 0

    for ftype, group in by_type.items():
        limit = max_per_type.get(ftype, default_max)

        # Sort by fecha_publicacion descending (most recent first)
        group.sort(key=lambda x: x.get("fecha_publicacion", "0000-00-00"), reverse=True)

        selected.extend(group[:limit])
        skipped_count += max(0, len(group) - limit)

    if skipped_count:
        print(f"[router] Filing selection: {len(selected)} selected, {skipped_count} skipped "
              f"(from {len(filings)} total)")
        for ftype, group in sorted(by_type.items()):
            limit = max_per_type.get(ftype, default_max)
            if len(group) > limit:
                print(f"[router]   {ftype}: {limit}/{len(group)} (skipped {len(group) - limit} oldest)")
            else:
                print(f"[router]   {ftype}: {len(group)}/{len(group)}")

    return selected


def _run_parallel_filing_step(config: EngineConfig, case_dir: Path, step_name: str, ticker: str) -> dict:
    """Execute TP_EXTRACTOR with parallel filing dispatch."""
    instrucciones_dir = config.get_path("instrucciones")

    # Load SourcesPack to get filings
    sources_pack = _find_artifact(case_dir, "SourcesPack_v1")
    if not sources_pack:
        return {"success": False, "error": "SourcesPack not found for parallel filing extraction"}

    with open(sources_pack) as f:
        sp = json.load(f)

    # Extract filing entries from SourcesPack
    all_filings = []
    for source in sp.get("fuentes", sp.get("fuentes_usadas", sp.get("sources", []))):
        local_path = source.get("local_path")
        if local_path:
            source["ticker"] = ticker
            all_filings.append(source)

    if not all_filings:
        return {"success": False, "error": "No filings with local_path found in SourcesPack"}

    # Apply filing selection filter
    filings = _select_filings(all_filings, config)

    # Clean stale partials from previous runs to avoid merger contamination
    for old_partial in case_dir.glob("_tmp_tp_filing_*.json"):
        old_partial.unlink()

    # Dispatch in parallel
    results = dispatch_parallel_filings(config, filings, instrucciones_dir, case_dir)

    # Save partial results and validate
    successful = 0
    filing_records = []
    for i, result in enumerate(results):
        if result.success and result.output:
            tmp_path = case_dir / f"_tmp_tp_filing_{i:03d}.json"
            tmp_path.write_text(json.dumps(result.output, indent=2, ensure_ascii=False))
            successful += 1

            # Validar parcial
            is_valid, val_errors = validate_partial_truthpack(result.output)
            filing_records.append({
                "index": i,
                "output": result.output,
                "valid": is_valid,
                "errors": val_errors,
            })
            if not is_valid:
                print(f"[router] WARNING: Partial TP filing {i:03d} inválido: {val_errors}", file=sys.stderr)

    if successful == 0:
        return {"success": False, "error": "All filing extractions failed"}

    # Quality voting (report-only): nunca bloquear pipeline por fallos de voting
    try:
        first_ok = next((r for r in results if r.success), None)
        maybe_vote_step(
            config=config,
            case_dir=case_dir,
            step_name=step_name,
            model=first_ok.model if first_ok else None,
            backend=first_ok.backend if first_ok else None,
            filing_records=filing_records,
        )
    except Exception as exc:
        print(f"[router] WARNING: quality voting failed for {step_name}: {exc}", file=sys.stderr)

    return {
        "success": True,
        "model": first_ok.model if first_ok else "unknown",
        "filings_processed": successful,
        "filings_total": len(filings),
    }


def is_step_ready(case_dir: Path, step_name: str) -> bool:
    """Verifica que todas las dependencias del step están DONE."""
    try:
        state = load_state(case_dir)
    except FileNotFoundError:
        return False

    dag_entry = PIPELINE_DAG.get(step_name, {})
    deps = dag_entry.get("depends_on", [])

    pipeline = state.get("pipeline", {})
    for dep in deps:
        if pipeline.get(dep, {}).get("estado") != "DONE":
            return False

    # Also check if step itself is already done
    if pipeline.get(step_name, {}).get("estado") == "DONE":
        return False  # Already done

    return True


def _check_truthpack_quality(case_dir: Path, ticker: str) -> str | None:
    """Lee data_quality del TruthPack generado por TP_VALIDATOR.

    Resolución determinista del artefacto:
    1. Nombre exacto: TruthPack_v1_{ticker}.json
    2. Fallback: TruthPack_v1_*.json con mtime más reciente

    Retorna: "PASS", "PARTIAL", "FAIL", o None si no se puede leer.
    """
    # 1. Nombre exacto (es lo que _build_runner_args genera para TP_VALIDATOR)
    tp_path = case_dir / f"TruthPack_v1_{ticker}.json"

    if not tp_path.exists():
        # 2. Fallback: buscar por glob, mtime más reciente
        candidates = sorted(
            case_dir.glob("TruthPack_v1_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            tp_path = candidates[0]
        else:
            print(
                f"[router] ERROR: No se encontró TruthPack_v1 tras TP_VALIDATOR "
                f"(step=TP_VALIDATOR, ticker={ticker}, case_dir={case_dir})",
                file=sys.stderr,
            )
            return None

    try:
        tp = json.loads(tp_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[router] ERROR: No se pudo leer {tp_path}: {e}", file=sys.stderr)
        return None

    dq = tp.get("data_quality", {})
    # Dual-key fallback: status → overall_status
    status = dq.get("status") or dq.get("overall_status")
    if status:
        print(f"[router] TruthPack data_quality: {status} (confidence: {dq.get('confidence_score', '?')}%)")
    return status


def get_parallel_group(step_name: str) -> list[str]:
    """Retorna steps que pueden ejecutarse en paralelo con step_name."""
    dag_entry = PIPELINE_DAG.get(step_name, {})
    return dag_entry.get("parallel_with", [])


def _resolve_input_artifacts(case_dir: Path, step_name: str) -> dict[str, Path]:
    """Find input artifact files for a given step."""
    artifact_names = STEP_INPUT_ARTIFACTS.get(step_name, [])
    artifacts = {}

    for name in artifact_names:
        found = _find_artifact(case_dir, name)
        if found:
            artifacts[name] = found

    return artifacts


def _find_artifact(case_dir: Path, pattern: str) -> Path | None:
    """Find an artifact file in case_dir matching the pattern.

    Deterministic: returns the most recently modified match.
    """
    matches = [
        f for f in case_dir.iterdir()
        if f.is_file() and f.name.startswith(pattern) and f.suffix == ".json"
    ]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _get_artifact_filename(step_name: str, ticker: str, case_dir: Path) -> str:
    """Generate artifact filename for a step."""
    # Extract date and model from case_dir name
    dir_name = case_dir.name  # e.g., "2026-02-15_Codex"
    parts = dir_name.split("_", 1)
    date_str = parts[0].replace("-", "") if parts else "00000000"
    model_str = parts[1] if len(parts) > 1 else "Engine"

    artifact_map = {
        "PREFETCH": f"_prefetch_output_{ticker}.json",
        "SOURCES_COMPILER": f"SourcesPack_v1_{ticker}_{date_str}_{model_str}.json",
        "TP_EXTRACTOR_FILING": f"_tp_extractor_raw_{ticker}.json",
        "TP_CALCULATOR": f"_tp_calculated_{ticker}.json",
        "TP_VALIDATOR": f"TruthPack_v1_{ticker}_{date_str}_{model_str}.json",
        "IMPLIED": f"ImpliedExpectations_v1_{ticker}_{date_str}_{model_str}.json",
        "CATALYST_DETECTION": f"_catalyst_detection_{ticker}.json",
        "CATALYST_SCORING": f"AgentReport_v1_CATALYST_{ticker}_{date_str}_{model_str}.json",
        "FORENSIC_DETECTION": f"_forensic_detection_{ticker}.json",
        "FORENSIC_SCORING": f"AgentReport_v1_FORENSIC_{ticker}_{date_str}_{model_str}.json",
        "BULL": f"AgentReport_v1_BULL_{ticker}_{date_str}_{model_str}.json",
        "RED_TEAM": f"AgentReport_v1_REDTEAM_{ticker}_{date_str}_{model_str}.json",
        "ARBITRO": f"DecisionPacket_v2_{ticker}_{date_str}_{model_str}.json",
        "MONITOR": f"MonitoringUpdate_v1_{ticker}_{date_str}_{model_str}.json",
        "SCANNER": f"ScannerReport_v1_{date_str}.json",
    }

    return artifact_map.get(step_name, f"_{step_name.lower()}_output.json")


def _infer_schema_for_step(step_name: str) -> str | None:
    """Map step to expected output schema name."""
    schema_map = {
        "SOURCES_COMPILER": "SourcesPack_v1",
        "TP_VALIDATOR": "TruthPack_v1",
        "IMPLIED": "ImpliedExpectations_v1",
        "CATALYST_SCORING": "AgentReport_v1",
        "FORENSIC_SCORING": "AgentReport_v1",
        "BULL": "AgentReport_v1",
        "RED_TEAM": "AgentReport_v1",
        "ARBITRO": "DecisionPacket_v2",
        "MONITOR": "MonitoringUpdate_v1",
        "SCANNER": "ScannerReport_v1",
    }
    return schema_map.get(step_name)


def _build_runner_args(step_name: str, case_dir: Path, ticker: str, config: EngineConfig) -> list[str]:
    """Build CLI arguments for a Python runner."""
    if step_name == "PREFETCH":
        return ["--ticker", ticker, "--case-dir", str(case_dir)]
    elif step_name == "SOURCES_COMPILER":
        return [ticker, str(case_dir)]
    elif step_name == "TP_CALCULATOR":
        # Find partial TP and market data
        partial = _find_artifact(case_dir, "_tp_extractor") or _find_artifact(case_dir, "_tmp_tp_merged")
        market = _find_artifact(case_dir, "_market_data")
        output = case_dir / f"_tp_calculated_{ticker}.json"
        args = []
        if partial:
            args.append(str(partial))
        if market:
            args.append(str(market))
        args.append(str(output))
        return args
    elif step_name == "TP_VALIDATOR":
        calculated = _find_artifact(case_dir, "_tp_calculated")
        output = case_dir / f"TruthPack_v1_{ticker}.json"
        args = []
        if calculated:
            args.append(str(calculated))
        args.append(str(output))
        return args
    elif step_name == "TP_EXTRACTOR_MERGER":
        return [str(case_dir), str(case_dir / f"_tmp_tp_merged_{ticker}.json")]
    else:
        return ["--case-dir", str(case_dir), "--ticker", ticker]


def _run_quality_audit(config: EngineConfig, case_dir: Path) -> None:
    """Run case_quality_audit.py on the completed case."""
    audit_script = config.workspace / "scripts" / "case_quality_audit.py"
    if audit_script.exists():
        try:
            subprocess.run(
                [sys.executable, str(audit_script), str(case_dir)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(config.workspace),
            )
        except Exception as e:
            print(f"[router] Quality audit error: {e}", file=sys.stderr)


def _execute_parallel_steps(
    config: EngineConfig,
    case_dir: Path,
    steps: list[str],
    ticker: str,
) -> dict[str, dict]:
    """Execute multiple steps in parallel using ThreadPoolExecutor."""
    max_workers = config.execution.get("max_parallel_backends", 3)
    results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_step = {
            executor.submit(execute_step, config, case_dir, step, ticker): step
            for step in steps
        }
        for future in concurrent.futures.as_completed(future_to_step):
            step = future_to_step[future]
            try:
                results[step] = future.result()
            except Exception as e:
                results[step] = {"success": False, "error": str(e)}
                mark_step_failed(case_dir, step, str(e))

    return results


def _extract_decision_fields(case_dir: Path, step_result: dict) -> None:
    """Extract decision/score/confianza from ARBITRO result and update state.

    Handles both formats:
    - Legacy (flat): data.decision, data.score, data.confianza
    - DecisionPacket_v2: data.resumen_ejecutivo.decision, .confianza_global_0_1
    """
    artifact_name = step_result.get("artifact")
    if not artifact_name:
        return

    artifact_path = case_dir / artifact_name
    if not artifact_path.exists():
        return

    try:
        with open(artifact_path) as f:
            data = json.load(f)

        # Try flat format first (legacy / DecisionPacket_v1)
        decision = data.get("decision", data.get("Decision"))
        score = data.get("score", data.get("Score"))
        confianza = data.get("confianza", data.get("Confianza", ""))
        probabilistica = data.get("probabilistica")

        # Fall back to DecisionPacket_v2 nested format
        # Handle both top-level resumen and decision_packet wrapper
        resumen = data.get("resumen_ejecutivo", {})
        if not resumen and isinstance(data.get("decision_packet"), dict):
            resumen = data["decision_packet"].get("resumen_ejecutivo", {})
        if isinstance(resumen, dict):
            if decision is None:
                decision = resumen.get("decision")
            if score is None:
                score = resumen.get("score_global", resumen.get("score"))
            if not confianza:
                confianza = resumen.get("confianza_global_0_1", resumen.get("confianza", ""))

        if decision is not None:
            update_decision_fields(
                case_dir,
                decision=str(decision),
                score=float(score) if score is not None else 0.0,
                confianza=str(confianza),
                probabilistica=probabilistica,
            )
    except (json.JSONDecodeError, OSError, ValueError):
        pass
