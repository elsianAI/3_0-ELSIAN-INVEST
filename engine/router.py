"""DAG del pipeline — decide flujo de ejecución.

Implements §3.5 of PLAN COMPLETO.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import EngineConfig, get_step_config
from .state import (
    load_state, save_state, mark_step_done, mark_step_failed,
    mark_step_in_progress, mark_pipeline_status, update_decision_fields,
    get_next_step, init_state, init_or_load_state,
    resolve_empresa_hints, persist_empresa_hints, read_modify_write,
    PIPELINE_STEPS, SUB_STEPS,
)
from .step_contracts import get_primary_schema
from .dispatcher import (
    dispatch_step, dispatch_multi_and_fuse, dispatch_parallel_filings,
    dispatch_with_escalation,
)
from .prompt_builder import build_prompt
from .validator import validate_artifact, validate_file, validate_inter_step, validate_partial_truthpack
from .changelog import append_entry
from .dashboard import generate_dashboard
from .quality_voting import maybe_vote_step

# Steps that need project-wide filesystem access (tools-enabled agentic mode).
# For these steps, dispatch cwd is set to workspace root instead of case_dir
# so the LLM can read candidatos/, casos/, _docs/, etc.
_PROJECT_SCOPED_STEPS = {
    "SCANNER", "SCOUT_PREFILTRO", "SCOUT_Q", "SCOUT_E",
    "MONITOR", "OUTCOME",
}

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
    "CATALYST_SCORING": ["TruthPack_v1", "ImpliedExpectations_v1", "CatalystDetection_v1"],
    "FORENSIC_DETECTION": ["TruthPack_v1", "ImpliedExpectations_v1"],
    "FORENSIC_SCORING": ["TruthPack_v1", "ImpliedExpectations_v1", "ForensicDetection_v1"],
    "BULL": ["TruthPack_v1", "ImpliedExpectations_v1", "AgentReport_v1_CATALYST", "AgentReport_v1_FORENSIC"],
    "RED_TEAM": ["TruthPack_v1", "AgentReport_v1_BULL"],
    "ARBITRO": ["TruthPack_v1", "AgentReport_v1_BULL", "AgentReport_v1_REDTEAM",
                "AgentReport_v1_CATALYST", "AgentReport_v1_FORENSIC", "ImpliedExpectations_v1"],
}

# ── V5.1 B2/B3/B4: Fingerprint + artifact reuse ─────────────────────

_REUSABLE_STEPS = {"RED_TEAM", "ARBITRO"}


def _compute_step_input_fingerprint(case_dir: Path, step_name: str) -> str:
    """Compute deterministic SHA256 fingerprint of step inputs.

    Includes:
    - step_name
    - target schema name
    - expected input artifact names (stable sorted order)
    - explicit missing markers per expected artifact
    - resolved filename + content bytes when artifact exists
    """
    h = hashlib.sha256()
    h.update(step_name.encode("utf-8"))
    schema_name = _infer_schema_for_step(step_name) or "NO_SCHEMA"
    h.update(f"SCHEMA:{schema_name}".encode("utf-8"))
    expected_inputs = sorted(STEP_INPUT_ARTIFACTS.get(step_name, []))
    for name in expected_inputs:
        h.update(f"INPUT:{name}".encode("utf-8"))
        p = _find_artifact(case_dir, name)
        if p is None:
            h.update(f"MISSING:{name}".encode("utf-8"))
            continue
        h.update(f"FILE:{p.name}".encode("utf-8"))
        try:
            h.update(p.read_bytes())
        except (OSError, IOError):
            h.update(f"MISSING:{name}".encode("utf-8"))
    return h.hexdigest()


def _persist_step_fingerprint(case_dir: Path, step_name: str, fingerprint: str) -> None:
    """Persist fingerprint to step state (V5.1 B2)."""
    def _mod(state: dict) -> None:
        pipeline = state.setdefault("pipeline", {})
        step_state = pipeline.setdefault(
            step_name,
            {"estado": "PENDING", "artefacto": None, "artefacto_previo": None},
        )
        step_state["input_fingerprint"] = fingerprint
    read_modify_write(case_dir, _mod)


def _recover_previous_artifact_if_valid(
    config: EngineConfig,
    case_dir: Path,
    step_name: str,
    error_msg: str,
    failure_ctx: dict | None = None,
) -> dict | None:
    """Attempt to reuse a previous valid artifact on transport/timeout failure (V5.1 B3).

    Returns a success-like result dict if recovery succeeded, None otherwise.
    Only active for steps in _REUSABLE_STEPS.
    """
    if step_name not in _REUSABLE_STEPS:
        return None

    # Import here to avoid circular dep
    from .dispatcher import _is_retryable_dispatch_error

    # Check error is transport/timeout (not quality)
    if not _is_retryable_dispatch_error(error_msg, failure_ctx.get("raw_output", "") if failure_ctx else ""):
        return None

    # Find previous artifact
    state = load_state(case_dir)
    step_state = state.get("pipeline", {}).get(step_name, {})
    artifact_path_str = step_state.get("artefacto") or step_state.get("artefacto_previo")
    artifact_path: Path | None = None
    if artifact_path_str:
        artifact_path = (
            case_dir / artifact_path_str
            if not Path(artifact_path_str).is_absolute()
            else Path(artifact_path_str)
        )
    else:
        # Fallback: legacy states may have no artifact pointer even when the
        # artifact exists on disk. Recover deterministically from canonical prefix.
        recover_pattern = None
        if step_name == "RED_TEAM":
            recover_pattern = "AgentReport_v1_REDTEAM"
        elif step_name == "ARBITRO":
            recover_pattern = "DecisionPacket_v2"
        if recover_pattern:
            found = _find_artifact(case_dir, recover_pattern)
            if found is not None:
                artifact_path = found
                artifact_path_str = found.name
                print(
                    f"[router] {step_name}: artifact pointer missing in state; "
                    f"recovered from disk: {found.name}"
                )
    if artifact_path is None:
        return None
    if not artifact_path.exists():
        return None

    # Validate artifact is valid JSON + schema
    try:
        with open(artifact_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    schema_name = _infer_schema_for_step(step_name)
    if not schema_name:
        print(
            f"[router] {step_name}: schema not configured — reuse blocked",
            file=sys.stderr,
        )
        return None
    is_valid, schema_errors = validate_artifact(payload, schema_name, config.get_path("schemas"))
    if not is_valid:
        print(
            f"[router] {step_name}: previous artifact schema invalid — reuse blocked: {schema_errors}",
            file=sys.stderr,
        )
        return None

    # Fingerprint check (V5.1 B2)
    current_fp = _compute_step_input_fingerprint(case_dir, step_name)
    saved_fp = step_state.get("input_fingerprint")

    bootstrap_legacy = False
    if saved_fp is None:
        # V5.1 B4 — Bootstrap legacy: no fingerprint persisted yet.
        # Allow reuse once and persist fingerprint for future enforcement.
        print(f"[router] {step_name}: bootstrap legacy — no fingerprint, allowing one-time reuse")
        bootstrap_legacy = True
    elif current_fp != saved_fp:
        # Inputs changed → reuse not safe
        print(
            f"[router] {step_name}: fingerprint mismatch "
            f"(saved={saved_fp[:12]}… current={current_fp[:12]}…) — reuse blocked"
        )
        return None

    # All checks passed — reuse the artifact
    print(
        f"[router] {step_name}: reusing previous artifact {artifact_path.name} "
        f"(transport/timeout failure, fingerprint OK)"
    )

    # Mark step DONE (NOT mark_step_failed — Codex Adj #1)
    mark_step_done(
        case_dir,
        step_name,
        artefacto=str(artifact_path_str),
    )

    # Persist fingerprint + reuse metadata after mark_step_done.
    def _mark_reuse(s: dict) -> None:
        step_s = s.setdefault("pipeline", {}).setdefault(
            step_name,
            {"estado": "DONE", "artefacto": str(artifact_path_str), "artefacto_previo": None},
        )
        step_s["input_fingerprint"] = current_fp
        step_s["reused_previous_artifact"] = True
        step_s["reuse_reason"] = "transport_or_timeout"
        step_s["reused_artifact_path"] = str(artifact_path_str)
        if bootstrap_legacy:
            step_s["reuse_bootstrap_legacy"] = True
    read_modify_write(case_dir, _mark_reuse)

    return {
        "success": True,
        "artifact": str(artifact_path_str),
        "reused_previous_artifact": True,
        "reuse_reason": "transport_or_timeout",
    }


def _resolve_python_step_timeout(config: EngineConfig, step_name: str) -> int:
    """Resolve timeout for python runner steps.

    Priority:
      1) task_routing[step].timeout
      2) execution.python_step_timeouts[step]
      3) fallback 300
    """
    routing = config.task_routing.get(step_name, {})
    if isinstance(routing, dict) and "timeout" in routing:
        try:
            return int(routing["timeout"])
        except (TypeError, ValueError):
            pass

    step_timeouts = config.execution.get("python_step_timeouts", {})
    if isinstance(step_timeouts, dict) and step_name in step_timeouts:
        try:
            return int(step_timeouts[step_name])
        except (TypeError, ValueError):
            pass

    return 300


def _cleanup_tp_filing_partials(config: EngineConfig, case_dir: Path) -> int:
    """Remove TP partial filing temp files unless explicitly preserved."""
    if bool(config.execution.get("keep_tp_filing_partials", False)):
        return 0

    removed = 0
    for old_partial in case_dir.glob("_tmp_tp_filing_*.json"):
        old_partial.unlink(missing_ok=True)
        removed += 1
    return removed


def _normalize_country_code(value: object) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "US"
    return raw


def _annual_non_extractable_bucket(source: dict) -> str:
    status = str(source.get("extraction_status") or "").upper()
    reason = str(source.get("extraction_reason") or "").upper()
    merged = f"{status} {reason}"
    if "LOW_TEXT_ANNUAL" in merged:
        return "LOW_TEXT_ANNUAL"
    if "LOW_SIGNAL_ANNUAL" in merged:
        return "LOW_SIGNAL_ANNUAL"
    if "LEGACY_PDF_PLACEHOLDER" in merged:
        return "LEGACY_PLACEHOLDER"
    if "NON_EXTRACTABLE" in merged:
        return "NON_EXTRACTABLE_OTHER"
    if "FETCH_ERROR" in merged:
        return "FETCH_ERROR"
    return "OTHER"


def _infer_exchange_from_text(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if "NASDAQ" in text or "NASD" in text:
        return "NASDAQ"
    if "NYSE" in text:
        return "NYSE"
    if "AMEX" in text:
        return "AMEX"
    return ""


def _load_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _backfill_us_empresa_hints_from_prefetch(case_dir: Path) -> dict[str, str]:
    """Best-effort US hint enrichment after PREFETCH when hints are missing.

    Keeps explicit hints untouched and only fills missing keys.
    """
    current = resolve_empresa_hints(case_dir)
    missing_country = not current.get("country")
    missing_exchange = not current.get("exchange")
    missing_web_ir = not current.get("web_ir")
    if not (missing_country or missing_exchange or missing_web_ir):
        return current

    inferred = {"exchange": "", "country": "", "web_ir": ""}

    sec = _load_json_file(case_dir / "_sec_fetcher_output.json")
    sec_empresa = sec.get("empresa", {}) if isinstance(sec.get("empresa"), dict) else {}
    sec_country = _normalize_country_code(sec_empresa.get("pais"))
    sec_exchange = _infer_exchange_from_text(sec_empresa.get("bolsa"))
    sec_web_ir = str(sec_empresa.get("web_ir") or "").strip()
    sec_cik = str(sec_empresa.get("cik") or "").strip()

    if missing_country:
        if sec_country:
            inferred["country"] = sec_country
        elif sec_cik:
            inferred["country"] = "US"
    if missing_exchange and sec_exchange:
        inferred["exchange"] = sec_exchange
    if missing_web_ir and sec_web_ir:
        inferred["web_ir"] = sec_web_ir

    market = _load_json_file(case_dir / "_market_data_output.json")
    market_empresa = market.get("empresa", {}) if isinstance(market.get("empresa"), dict) else {}
    market_country = _normalize_country_code(market_empresa.get("pais"))
    market_exchange = _infer_exchange_from_text(market_empresa.get("bolsa"))
    market_web_ir = str(market_empresa.get("web_ir") or "").strip()

    if missing_country and not inferred["country"] and market_country:
        inferred["country"] = market_country
    if missing_exchange and not inferred["exchange"] and market_exchange:
        inferred["exchange"] = market_exchange
    if missing_web_ir and not inferred["web_ir"] and market_web_ir:
        inferred["web_ir"] = market_web_ir

    merged = {
        "exchange": current.get("exchange") or inferred["exchange"] or "",
        "country": current.get("country") or inferred["country"] or "",
        "web_ir": current.get("web_ir") or inferred["web_ir"] or "",
    }
    if merged == current:
        return current

    persist_empresa_hints(case_dir, merged)
    print(
        "[router] Auto-inferred empresa_hints from PREFETCH outputs: "
        f"exchange={merged.get('exchange') or '-'}, "
        f"country={merged.get('country') or '-'}, "
        f"web_ir={'set' if merged.get('web_ir') else '-'}",
        file=sys.stderr,
    )
    return merged


def _stable_json_hash(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text())
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    except Exception:
        return None


def _quarantine_alias_artifacts(case_dir: Path, step_name: str, canonical_path: Path) -> int:
    """Move alias/phantom artifacts to _deprecated for forensic traceability."""
    alias_patterns = {
        "ARBITRO": ["AgentReport_v1_ARBITRO_*.json"],
        "RED_TEAM": ["AgentReport_v1_RED_TEAM_*.json"],
    }
    patterns = alias_patterns.get(step_name, [])
    if not patterns or not canonical_path.exists():
        return 0

    canonical_hash = _stable_json_hash(canonical_path)
    if not canonical_hash:
        return 0

    multi_hashes = set()
    for trace in case_dir.glob(f"_multi_{step_name}_*.json"):
        h = _stable_json_hash(trace)
        if h:
            multi_hashes.add(h)

    deprecated_dir = case_dir / "_deprecated"
    moved = 0
    for pattern in patterns:
        for candidate in sorted(case_dir.glob(pattern)):
            if candidate == canonical_path:
                continue
            candidate_hash = _stable_json_hash(candidate)
            if not candidate_hash:
                continue
            if candidate_hash != canonical_hash and candidate_hash not in multi_hashes:
                continue

            deprecated_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = deprecated_dir / f"{candidate.name}.{stamp}.json"
            idx = 1
            while target.exists():
                target = deprecated_dir / f"{candidate.name}.{stamp}.{idx}.json"
                idx += 1
            candidate.replace(target)
            moved += 1
            print(
                f"[router] WARNING: Quarantined alias artifact {candidate.name} -> "
                f"{target.relative_to(case_dir)}",
                file=sys.stderr,
            )

    return moved


def execute_pipeline(
    config: EngineConfig,
    case_dir: Path,
    ticker: str,
    date_str: str,
    exchange: str = "",
    country: str = "",
    web_ir: str = "",
    reset: bool = False,
) -> dict:
    """
    Ejecuta pipeline completo para un caso.
    Supports parallel execution of CATALYST||FORENSIC.

    V5.1 B1: If ``reset=False`` (default) and state already exists, resumes
    from current progress.  Use ``reset=True`` to start from scratch.
    """
    # 1. Resolve/persist company hints + init-or-load state (V5.1 B1)
    hints = resolve_empresa_hints(
        case_dir,
        exchange=exchange,
        country=country,
        web_ir=web_ir,
    )
    state = init_or_load_state(
        case_dir,
        ticker,
        date_str,
        reset=reset,
        exchange=hints["exchange"],
        country=hints["country"],
        web_ir=hints["web_ir"],
    )
    mark_pipeline_status(case_dir, "EN_PROGRESO")
    mode = "reset" if reset else ("resumed" if (case_dir / "_estado.json").exists() else "new")
    print(f"[pipeline] Initialized case: {state['caso_id']} (mode={mode})")

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

            parallel_results = _execute_parallel_steps(
                config, case_dir, group, ticker, hints=hints
            )

            all_ok = True
            for s, res in parallel_results.items():
                results[s] = res
                if res.get("success"):
                    mark_step_done(
                        case_dir,
                        s,
                        model=res.get("model", "unknown"),
                        artefacto=res.get("artifact"),
                        model_profile=res.get("model_profile"),
                    )
                    # V5.1 B2: Persist fingerprint on success
                    if s in _REUSABLE_STEPS:
                        fp = _compute_step_input_fingerprint(case_dir, s)
                        _persist_step_fingerprint(case_dir, s, fp)
                    print(f"[pipeline] ✓ {s} completed")
                else:
                    # V5.1 B3: Try artifact recovery before failing
                    recovery = _recover_previous_artifact_if_valid(
                        config,
                        case_dir, s,
                        res.get("error", "unknown"),
                        res.get("failure_ctx"),
                    )
                    if recovery:
                        results[s] = recovery
                        print(f"[pipeline] ⟳ {s} recovered via previous artifact")
                    else:
                        mark_step_failed(
                            case_dir,
                            s,
                            res.get("error", "unknown"),
                            failure_meta=res.get("failure_ctx"),
                        )
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
            step_result = execute_step(
                config, case_dir, step_name, ticker, hints=hints
            )
            results[step_name] = step_result

            if step_result.get("success"):
                mark_step_done(
                    case_dir,
                    step_name,
                    model=step_result.get("model", "unknown"),
                    artefacto=step_result.get("artifact"),
                    model_profile=step_result.get("model_profile"),
                )
                # V5.1 B2: Persist fingerprint on success for reusable steps
                if step_name in _REUSABLE_STEPS:
                    fp = _compute_step_input_fingerprint(case_dir, step_name)
                    _persist_step_fingerprint(case_dir, step_name, fp)
                print(f"[pipeline] ✓ {step_name} completed")
                # Extract decision fields from ARBITRO
                if step_name == "ARBITRO":
                    _extract_decision_fields(case_dir, step_result)
            else:
                # V5.1 B3: Try artifact recovery before failing
                recovery = _recover_previous_artifact_if_valid(
                    config,
                    case_dir, step_name,
                    step_result.get("error", "unknown"),
                    step_result.get("failure_ctx"),
                )
                if recovery:
                    results[step_name] = recovery
                    print(f"[pipeline] ⟳ {step_name} recovered via previous artifact")
                    if step_name == "ARBITRO":
                        _extract_decision_fields(case_dir, recovery)
                else:
                    mark_step_failed(
                        case_dir,
                        step_name,
                        step_result.get("error", "unknown"),
                        failure_meta=step_result.get("failure_ctx"),
                    )
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


def execute_step(
    config: EngineConfig,
    case_dir: Path,
    step_name: str,
    ticker: str,
    hints: dict[str, str] | None = None,
) -> dict:
    """Ejecuta un step individual (principal o sub-step group)."""
    # Check if step has sub-steps
    if step_name in SUB_STEPS:
        return _execute_step_group(config, case_dir, step_name, ticker, hints=hints)

    return _execute_single_step(config, case_dir, step_name, ticker, hints=hints)


def _execute_step_group(
    config: EngineConfig,
    case_dir: Path,
    group_name: str,
    ticker: str,
    hints: dict[str, str] | None = None,
) -> dict:
    """Execute a group of sub-steps (e.g., SOURCES → PREFETCH + SOURCES_COMPILER).

    Skips sub-steps that are already DONE (for continue/retry scenarios).
    """
    sub_steps = SUB_STEPS[group_name]
    results = {}
    state = load_state(case_dir)
    group_artifact = state.get("pipeline", {}).get(group_name, {}).get("artefacto")

    # ── If TRUTH_PACK previously FAILED, reset all sub-steps to PENDING ──
    # This ensures a full re-run (e.g., TP_EXTRACTOR_FILING) instead of
    # skipping sub-steps that were marked DONE in the failed attempt.
    # Scoped to TRUTH_PACK only: SOURCES re-runs are cheap and don't need
    # this; other LLM-heavy groups benefit from controlled re-extraction.
    group_estado = state.get("pipeline", {}).get(group_name, {}).get("estado")
    if group_estado == "FAILED" and group_name == "TRUTH_PACK":
        def _reset_subs(s: dict) -> None:
            for sub in sub_steps:
                if sub in s.get("sub_steps", {}):
                    s["sub_steps"][sub] = {"status": "PENDING"}
            s["pipeline"][group_name]["estado"] = "IN_PROGRESS"
        read_modify_write(case_dir, _reset_subs)
        state = load_state(case_dir)
        print(f"[pipeline] Reset sub-steps of {group_name} (was FAILED) → all PENDING",
              file=sys.stderr)

    for sub_step in sub_steps:
        # Skip already-done sub-steps
        ss_status = state.get("sub_steps", {}).get(sub_step, {}).get("status", "PENDING")
        if ss_status == "DONE":
            print(f"[pipeline]   → Sub-step: {sub_step} (already DONE, skipping)")
            continue

        print(f"[pipeline]   → Sub-step: {sub_step}")
        mark_step_in_progress(case_dir, sub_step)

        try:
            result = _execute_single_step(
                config, case_dir, sub_step, ticker, hints=hints
            )
            results[sub_step] = result

            if result.get("success"):
                sub_artifact = result.get("artifact")
                if sub_artifact:
                    group_artifact = sub_artifact
                mark_step_done(
                    case_dir,
                    sub_step,
                    model=result.get("model", "python"),
                    artefacto=sub_artifact,
                    model_profile=result.get("model_profile"),
                )
                append_entry(
                    config.get_path("changelog"),
                    ticker, "PIPELINE", sub_step,
                    result.get("model", "python"),
                )

                # Gate post-TP_VALIDATOR: verificar data_quality del TruthPack
                if sub_step == "TP_VALIDATOR":
                    dq_result = _check_truthpack_quality(case_dir, ticker)
                    if dq_result == "FAIL":
                        failure_ctx = {
                            "step_context": {
                                "step": sub_step,
                                "mode": "tp_quality_gate",
                            },
                            "last_error": "TruthPack data_quality: FAIL",
                        }
                        mark_step_failed(
                            case_dir,
                            sub_step,
                            "TruthPack data_quality: FAIL",
                            failure_meta=failure_ctx,
                        )
                        if config.execution.get("fail_fast", True):
                            return {
                                "success": False,
                                "error": "TruthPack data_quality FAIL",
                                "failure_ctx": failure_ctx,
                                "results": results,
                            }
                    elif dq_result == "PARTIAL":
                        print(f"[pipeline]   ⚠ TruthPack data_quality: PARTIAL — pipeline continúa", file=sys.stderr)
                    elif dq_result is None:
                        gate_missing = config.execution.get("tp_quality_gate_missing", "fail")
                        if gate_missing == "warn":
                            print(f"[pipeline]   ⚠ No se pudo leer data_quality del TruthPack — gate inactivo (tp_quality_gate_missing=warn)", file=sys.stderr)
                        else:
                            failure_ctx = {
                                "step_context": {
                                    "step": sub_step,
                                    "mode": "tp_quality_gate",
                                },
                                "last_error": "TruthPack data_quality: no disponible",
                            }
                            mark_step_failed(
                                case_dir,
                                sub_step,
                                "TruthPack data_quality: no disponible",
                                failure_meta=failure_ctx,
                            )
                            if config.execution.get("fail_fast", True):
                                return {
                                    "success": False,
                                    "error": "TruthPack data_quality no disponible — gate fail-closed",
                                    "failure_ctx": failure_ctx,
                                    "results": results,
                                }

                # Post-merge cleanup for partial filing temp files
                if sub_step == "TP_EXTRACTOR_MERGER":
                    removed = _cleanup_tp_filing_partials(config, case_dir)
                    if removed:
                        print(
                            f"[router] Cleaned {removed} TP partial files after TP_EXTRACTOR_MERGER",
                            file=sys.stderr,
                        )
                elif sub_step == "PREFETCH":
                    _backfill_us_empresa_hints_from_prefetch(case_dir)
            else:
                mark_step_failed(
                    case_dir,
                    sub_step,
                    result.get("error", "unknown"),
                    failure_meta=result.get("failure_ctx"),
                )
                if config.execution.get("fail_fast", True):
                    return {
                        "success": False,
                        "error": f"Sub-step {sub_step} failed",
                        "failure_ctx": result.get("failure_ctx"),
                        "results": results,
                    }
        except Exception as e:
            failure_ctx = {
                "step_context": {
                    "step": sub_step,
                    "mode": "sub_step_exception",
                },
                "last_error": str(e),
            }
            mark_step_failed(
                case_dir,
                sub_step,
                str(e),
                failure_meta=failure_ctx,
            )
            if config.execution.get("fail_fast", True):
                return {"success": False, "error": str(e), "failure_ctx": failure_ctx, "results": results}

    return {
        "success": True,
        "results": results,
        "artifact": group_artifact,
        "model": next((r.get("model") for r in reversed(list(results.values())) if isinstance(r, dict) and r.get("model")), "python"),
    }


def _execute_single_step(
    config: EngineConfig,
    case_dir: Path,
    step_name: str,
    ticker: str,
    hints: dict[str, str] | None = None,
) -> dict:
    """Execute a single step (either Python runner or LLM dispatch)."""
    step_cfg = get_step_config(config, step_name)
    backends = step_cfg.get("backends", [])
    is_multi = step_cfg.get("multi", False)
    parallel_by = step_cfg.get("parallel_by")

    # Inter-step validation (solo para steps con checks configurados)
    input_artifacts = _resolve_input_artifacts(case_dir, step_name)
    loaded_artifacts = {}
    load_failures = []
    for art_name, art_path in input_artifacts.items():
        try:
            loaded_artifacts[art_name] = json.loads(art_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            load_failures.append(f"{art_name}: {exc}")
            print(
                f"[router] ⚠ failed to load input artifact {art_name} for {step_name}: {exc}",
                file=sys.stderr,
            )
    if load_failures and not loaded_artifacts:
        # All input artifacts failed to load — block execution
        failure_ctx = {
            "step_context": {"step": step_name, "mode": "inter_step_validation"},
            "last_error": f"All input artifacts failed to load: {'; '.join(load_failures)}",
            "attempts": [],
        }
        return {
            "success": False,
            "error": failure_ctx["last_error"],
            "model": "validation",
            "backend": "python",
            "failure_ctx": failure_ctx,
        }
    if loaded_artifacts:
        passed, errors, warnings = validate_inter_step(step_name, loaded_artifacts)
        for w in warnings:
            print(f"[router] ⚠ inter-step warning ({step_name}): {w}", file=sys.stderr)
        if not passed:
            failure_ctx = {
                "step_context": {
                    "step": step_name,
                    "mode": "inter_step_validation",
                },
                "last_error": f"Inter-step validation failed: {'; '.join(errors)}",
                "attempts": [],
            }
            return {
                "success": False,
                "error": failure_ctx["last_error"],
                "model": "validation",
                "backend": "python",
                "failure_ctx": failure_ctx,
            }

    # Python runner — execute directly
    if "python" in backends:
        return _run_python_step(config, case_dir, step_name, ticker, hints=hints)

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

    # For project-scoped steps (SCANNER, SCOUT, etc.) the LLM needs access
    # to the full workspace tree, not just the output directory.
    dispatch_cwd = config.workspace if step_name in _PROJECT_SCOPED_STEPS else case_dir

    # Multi-model dispatch + fusion
    vote_group_id: str | None = None
    if is_multi:
        vote_group_id = str(uuid4())
        result = dispatch_multi_and_fuse(
            config, step_name, prompt, instrucciones_dir,
            cwd=dispatch_cwd,
        )
        # Per-model quality voting: vote each backend's individual output
        # This enables comparing per-model quality vs fusion quality.
        _vote_per_model(config, case_dir, step_name, vote_group_id=vote_group_id)
    elif config.get_escalation_config(step_name):
        # Use escalation-aware dispatch
        result = dispatch_with_escalation(config, step_name, prompt, cwd=dispatch_cwd)
    else:
        result = dispatch_step(config, step_name, prompt, cwd=dispatch_cwd)
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

        # Quarantine known alias/phantom artifacts that duplicate canonical output.
        _quarantine_alias_artifacts(case_dir, step_name, artifact_path)

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
                vote_group_id=vote_group_id,
            )
        except Exception as exc:
            print(f"[router] WARNING: quality voting failed for {step_name}: {exc}", file=sys.stderr)

        ret = {
            "success": True,
            "model": result.model,
            "backend": result.backend,
            "duration_s": result.duration_s,
            "artifact": artifact_name,
            "backends_used": result.backends_used,
        }
        if result.model_profile:
            ret["model_profile"] = result.model_profile
        if result.transport:
            ret["transport"] = result.transport
        return ret
    else:
        ret = {
            "success": False,
            "error": result.error or "No output",
            "model": result.model,
            "backend": result.backend,
        }
        if result.model_profile:
            ret["model_profile"] = result.model_profile
        if result.failure_ctx:
            ret["failure_ctx"] = result.failure_ctx
        if result.attempts:
            ret["attempts"] = result.attempts
        if result.transport:
            ret["transport"] = result.transport
        return ret


def _run_python_step(
    config: EngineConfig,
    case_dir: Path,
    step_name: str,
    ticker: str,
    hints: dict[str, str] | None = None,
) -> dict:
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
        return {
            "success": False,
            "error": f"No runner mapped for {step_name}",
            "model": "python",
            "failure_ctx": {
                "step_context": {
                    "step": step_name,
                    "mode": "python",
                },
                "backend": "python",
                "transport": "python",
                "model_profile": "python",
                "last_error": f"No runner mapped for {step_name}",
            },
            "attempts": [{"attempt": 1, "phase": "python_runner", "error": f"No runner mapped for {step_name}"}],
        }

    full_runner_path = config.workspace / runner_path
    if not full_runner_path.exists():
        return {
            "success": False,
            "error": f"Runner not found: {full_runner_path}",
            "model": "python",
            "failure_ctx": {
                "step_context": {
                    "step": step_name,
                    "mode": "python",
                },
                "backend": "python",
                "transport": "python",
                "model_profile": "python",
                "last_error": f"Runner not found: {full_runner_path}",
            },
            "attempts": [{"attempt": 1, "phase": "python_runner", "error": f"Runner not found: {full_runner_path}"}],
        }

    # Build args based on step
    args = _build_runner_args(step_name, case_dir, ticker, config, hints=hints)

    cmd = [sys.executable, str(full_runner_path)] + args
    timeout_s = _resolve_python_step_timeout(config, step_name)

    def _snip(text: str | None, limit: int = 1200) -> str:
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."

    def _failure_ctx(base_error: str, exit_code: int | None = None, stderr: str | None = None, stdout: str | None = None) -> dict[str, object]:
        return {
            "step_context": {
                "step": step_name,
                "mode": "python",
                "timeout_s": timeout_s,
            },
            "model_profile": "python",
            "backend": "python",
            "transport": "python",
            "last_error": base_error,
            "exit_code": exit_code,
            "stderr": stderr or "",
            "stdout_snippet": _snip(stdout),
            "attempts": [
                {
                    "attempt": 1,
                    "phase": "python_runner",
                    "model_profile": "python",
                    "model_id": "python",
                    "transport": "python",
                    "timeout": timeout_s,
                    "duration_s": None,
                    "exit_code": exit_code,
                    "error": base_error,
                    "recovered": False,
                }
            ],
        }

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(config.workspace),
        )

        if proc.returncode == 0:
            stderr_hints = ""
            if proc.stderr and proc.stderr.strip():
                stderr_hints = _snip(proc.stderr.strip(), limit=500)
                print(
                    f"[router] WARNING: python runner {step_name} emitted stderr: {stderr_hints}",
                    file=sys.stderr,
                )
            return {
                "success": True,
                "model": "python",
                "output": proc.stdout[:1000],
                "stderr_hints": stderr_hints,
                "artifact": _infer_python_step_artifact(case_dir, step_name, ticker),
            }
        error_message = f"Runner exit code {proc.returncode}: {proc.stderr[:500]}"
        return {
            "success": False,
            "error": error_message,
            "model": "python",
            "failure_ctx": _failure_ctx(
                error_message,
                exit_code=proc.returncode,
                stderr=proc.stderr,
                stdout=proc.stdout,
            ),
            "attempts": [{"attempt": 1, "phase": "python_runner", "exit_code": proc.returncode}],
        }
    except subprocess.TimeoutExpired:
        error_message = f"Runner timeout ({step_name}, {timeout_s}s)"
        return {
            "success": False,
            "error": error_message,
            "model": "python",
            "failure_ctx": _failure_ctx(
                error_message,
                exit_code=124,
                stderr="Process timed out",
            ),
            "attempts": [{"attempt": 1, "phase": "python_runner", "exit_code": 124}],
        }
    except Exception as e:
        error_message = str(e)
        return {
            "success": False,
            "error": error_message,
            "model": "python",
            "failure_ctx": _failure_ctx(
                error_message,
                exit_code=None,
                stderr="",
            ),
            "attempts": [{"attempt": 1, "phase": "python_runner", "exit_code": None, "error": error_message}],
        }


def _infer_python_step_artifact(case_dir: Path, step_name: str, ticker: str) -> str | None:
    """Infer artifact filename produced by Python runner steps."""
    pattern_map = {
        "SOURCES_COMPILER": "SourcesPack_v1",
        "TP_CALCULATOR": "_tp_calculated",
        "TP_VALIDATOR": "TruthPack_v1",
        "TP_EXTRACTOR_MERGER": "_tmp_tp_merged",
    }
    pattern = pattern_map.get(step_name)
    if not pattern:
        return None
    found = _find_artifact(case_dir, pattern)
    return found.name if found else None


def _resolve_source_local_path(local_path: str, case_dir: Path, workspace: Path) -> Path | None:
    lp = Path(local_path)
    candidates: list[Path] = []
    if lp.is_absolute():
        candidates.append(lp)
    else:
        candidates.append(case_dir / local_path)
        candidates.append(workspace / local_path)
        candidates.append(Path(local_path))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _source_has_legacy_pdf_placeholder(source: dict, case_dir: Path, workspace: Path) -> bool:
    local_path = source.get("local_path")
    if not isinstance(local_path, str) or not local_path.strip():
        return False
    resolved = _resolve_source_local_path(local_path, case_dir, workspace)
    if not resolved or resolved.suffix.lower() != ".txt":
        return False
    try:
        head = resolved.read_text(encoding="utf-8", errors="replace")[:300].strip().lower()
    except Exception:
        return False
    return (
        head.startswith("[pdf original descargado")
        or "extracción de texto no disponible en este runner" in head
        or "extraccion de texto no disponible en este runner" in head
    )


def _parse_filing_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if len(raw) >= 10:
        raw = raw[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _filing_doc_quality_rank(item: dict) -> int:
    local_path = str(item.get("local_path") or "").strip().lower()
    clean_status = str(item.get("clean_md_status") or "").strip().upper()
    if local_path.endswith(".clean.md") and clean_status == "GENERATED":
        return 0
    if local_path.endswith(".clean.md"):
        return 1
    if local_path.endswith(".txt"):
        return 2
    if local_path:
        return 3
    return 4


def _filing_sort_key(item: dict) -> tuple[int, int, int, float, str]:
    parsed = _parse_filing_date(item.get("fecha_publicacion"))
    estimated_raw = item.get("fecha_publicacion_estimated")
    if estimated_raw is None:
        estimated = parsed is None
    else:
        estimated = bool(estimated_raw)

    try:
        selection_score = float(item.get("selection_score") or 0.0)
    except Exception:
        selection_score = 0.0

    source_id = str(item.get("source_id") or "")
    date_ord = parsed.toordinal() if parsed else 0
    # Sort ascending by key:
    # 1) better document quality (.clean.md GENERATED first),
    # 2) non-estimated first,
    # 3) newer dates first,
    # 4) higher score first,
    # 5) stable source_id.
    return (_filing_doc_quality_rank(item), 1 if estimated else 0, -date_ord, -selection_score, source_id)


def _select_filings(filings: list[dict], config: EngineConfig) -> list[dict]:
    """Filter and prioritize filings to reduce unnecessary LLM calls.

    Uses tp_extractor_max_per_type from config to cap filings per type.
    Within each type, keeps the most recent by fecha_publicacion.
    """
    filtered_by_extraction = 0
    filtered: list[dict] = []
    for filing in filings:
        extraction_status = filing.get("extraction_status")
        if extraction_status is not None and str(extraction_status).upper() != "OK":
            filtered_by_extraction += 1
            continue
        filtered.append(filing)

    if filtered_by_extraction:
        print(
            f"[router] Filing selection: skipped {filtered_by_extraction} filings "
            "with extraction_status != OK"
        )

    filings = filtered
    dedup_hash_skipped = 0
    hash_kept: dict[str, dict] = {}
    no_hash: list[dict] = []
    for filing in filings:
        content_hash = filing.get("content_hash")
        ch = str(content_hash).strip().lower() if isinstance(content_hash, str) else ""
        if not ch:
            no_hash.append(filing)
            continue
        prev = hash_kept.get(ch)
        if prev is None:
            hash_kept[ch] = filing
            continue
        dedup_hash_skipped += 1
        if _filing_sort_key(filing) < _filing_sort_key(prev):
            hash_kept[ch] = filing

    if dedup_hash_skipped:
        print(
            f"[router] Filing selection: skipped {dedup_hash_skipped} duplicate filings by content_hash"
        )
    filings = no_hash + list(hash_kept.values())

    if not filings:
        return []

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

        group.sort(key=_filing_sort_key)

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
        # Pre-TP coverage gate: no filings to extract → fail fast with guidance
        print(
            "[router] Coverage gate (pre-TP): SourcesPack has 0 filings with local_path. "
            "Skipping TP_EXTRACTOR to avoid wasting LLM tokens.",
            file=sys.stderr,
        )
        return {
            "success": False,
            "error": "SourcesPack coverage gate: 0 filings with local_path. "
                     "For non-US companies, provide --exchange, --country, and/or --web-ir hints. "
                     "For US companies, verify ticker exists in SEC EDGAR.",
        }

    annual_types = {"10-K", "20-F", "40-F", "ANNUAL_REPORT"}
    annual_total_detected = 0
    annual_extractable = 0
    filtered_non_extractable = 0
    filtered_legacy_placeholder = 0
    filtered_transcript_issuer_mismatch = 0
    annual_non_extractable_counts: dict[str, int] = {}
    annual_non_extractable_samples: list[dict[str, str]] = []
    eligible_filings: list[dict] = []

    for source in all_filings:
        ftype = str(source.get("tipo", source.get("type", ""))).upper()
        is_annual = ftype in annual_types
        if is_annual:
            annual_total_detected += 1

        extraction_status = source.get("extraction_status")
        if extraction_status is not None:
            if str(extraction_status).upper() != "OK":
                filtered_non_extractable += 1
                if is_annual:
                    bucket = _annual_non_extractable_bucket(source)
                    annual_non_extractable_counts[bucket] = annual_non_extractable_counts.get(bucket, 0) + 1
                    if len(annual_non_extractable_samples) < 6:
                        annual_non_extractable_samples.append(
                            {
                                "source_id": str(source.get("source_id") or ""),
                                "tipo": ftype,
                                "status": str(source.get("extraction_status") or ""),
                                "reason": str(source.get("extraction_reason") or "")[:220],
                            }
                        )
                continue
        else:
            if _source_has_legacy_pdf_placeholder(source, case_dir, config.workspace):
                filtered_legacy_placeholder += 1
                if is_annual:
                    annual_non_extractable_counts["LEGACY_PLACEHOLDER"] = (
                        annual_non_extractable_counts.get("LEGACY_PLACEHOLDER", 0) + 1
                    )
                    if len(annual_non_extractable_samples) < 6:
                        annual_non_extractable_samples.append(
                            {
                                "source_id": str(source.get("source_id") or ""),
                                "tipo": ftype,
                                "status": "LEGACY_PDF_PLACEHOLDER",
                                "reason": "Legacy placeholder without extractable text.",
                            }
                        )
                continue

        if ftype == "EARNINGS_TRANSCRIPT":
            issuer_match = source.get("issuer_match")
            if issuer_match is not None and str(issuer_match).upper() != "MATCH":
                filtered_transcript_issuer_mismatch += 1
                continue

        eligible_filings.append(source)
        if is_annual:
            annual_extractable += 1

    if filtered_non_extractable or filtered_legacy_placeholder or filtered_transcript_issuer_mismatch:
        print(
            "[router] Filing pre-filter (extractable only): "
            f"kept={len(eligible_filings)}/{len(all_filings)}, "
            f"filtered_non_extractable={filtered_non_extractable}, "
            f"filtered_legacy_placeholder={filtered_legacy_placeholder}, "
            f"filtered_transcript_issuer_mismatch={filtered_transcript_issuer_mismatch}"
        )

    empresa = sp.get("empresa", {}) if isinstance(sp, dict) else {}
    bolsa = str(empresa.get("bolsa") or "").upper()
    pais = str(empresa.get("pais") or "").upper()
    is_non_us = (
        (pais not in {"", "US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"})
        or bolsa in {"SEHK", "HKEX", "ASX", "LSE", "AIM", "EPA", "TSX", "OTRA"}
    )
    if is_non_us and annual_total_detected == 0:
        print(
            "[router] Coverage warning (pre-TP): non-US issuer with 0 annual filings detected. "
            "TruthPack quality may degrade due to insufficient annual coverage.",
            file=sys.stderr,
        )

    if annual_total_detected > 0 and annual_extractable == 0:
        if annual_non_extractable_counts:
            print(
                "[router] Annual extractability gate details: "
                f"{annual_non_extractable_counts}",
                file=sys.stderr,
            )
        error = (
            "Coverage gate (pre-TP): Annual reports detected but none are extractable after quality "
            "filters. Review annual-report URL/source quality (local regulator or direct annual report "
            "document) before retrying TRUTH_PACK."
        )
        failure_ctx = {
            "step_context": {"step": step_name, "mode": "annual_extractable_gate"},
            "annual_total_detected": annual_total_detected,
            "annual_extractable": annual_extractable,
            "annual_non_extractable_counts": annual_non_extractable_counts,
            "annual_non_extractable_samples": annual_non_extractable_samples,
            "filings_total": len(all_filings),
            "filings_eligible": len(eligible_filings),
            "filtered_non_extractable": filtered_non_extractable,
            "filtered_legacy_placeholder": filtered_legacy_placeholder,
            "filtered_transcript_issuer_mismatch": filtered_transcript_issuer_mismatch,
            "last_error": error,
        }
        return {
            "success": False,
            "error": error,
            "failure_ctx": failure_ctx,
        }

    if not eligible_filings:
        error = (
            "Coverage gate (pre-TP): 0 extractable filings after filtering. "
            "Review source extraction quality and issuer matching."
        )
        failure_ctx = {
            "step_context": {"step": step_name, "mode": "extractable_filings_gate"},
            "filings_total": len(all_filings),
            "filings_eligible": 0,
            "filtered_non_extractable": filtered_non_extractable,
            "filtered_legacy_placeholder": filtered_legacy_placeholder,
            "filtered_transcript_issuer_mismatch": filtered_transcript_issuer_mismatch,
            "last_error": error,
        }
        return {
            "success": False,
            "error": error,
            "failure_ctx": failure_ctx,
        }

    # Apply filing selection filter
    filings = _select_filings(eligible_filings, config)
    if not filings:
        return {
            "success": False,
            "error": "Filing selection produced 0 entries after extraction-status filtering.",
            "failure_ctx": {
                "step_context": {"step": step_name, "mode": "filing_selection"},
                "filings_total": len(all_filings),
                "filings_eligible": len(eligible_filings),
                "filtered_transcript_issuer_mismatch": filtered_transcript_issuer_mismatch,
                "last_error": "No filings selected after extraction-status filtering.",
            },
        }

    # Clean stale partials from previous runs to avoid merger contamination
    for old_partial in case_dir.glob("_tmp_tp_filing_*.json"):
        old_partial.unlink()

    # Dispatch in parallel
    results = dispatch_parallel_filings(config, filings, instrucciones_dir, case_dir)

    # Save partial results and validate
    successful = 0
    filing_records = []
    filing_failures = []
    filing_attempts: list[dict] = []
    provenance_records: list[dict] = []
    field_provenance_records: list[dict] = []
    for i, result in enumerate(results):
        filing_entry = filings[i] if i < len(filings) else {}
        dispatch_meta = {}
        if isinstance(result.failure_ctx, dict):
            dispatch_meta = result.failure_ctx.get("filing_dispatch_meta", {}) or {}

        if result.success and result.output:
            # Inject filing_type from SourcesPack so merger can attribute fields
            if i < len(filings):
                ft = filings[i].get("tipo", filings[i].get("filing_type", ""))
                if ft:
                    result.output["filing_type"] = ft
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

            provenance_records.append(
                {
                    "index": i,
                    "source_id": filing_entry.get("source_id"),
                    "filing_type": filing_entry.get("tipo", filing_entry.get("filing_type")),
                    "local_path": filing_entry.get("local_path"),
                    "success": True,
                    "valid_partial": is_valid,
                    "model_profile": result.model_profile,
                    "model": result.model,
                    "backend": result.backend,
                    "transport": result.transport,
                    "dispatch_meta": dispatch_meta,
                    "artifact_path": str(tmp_path),
                }
            )
            raw_field_records = dispatch_meta.get("field_provenance", [])
            if isinstance(raw_field_records, list):
                for rec in raw_field_records:
                    if not isinstance(rec, dict):
                        continue
                    field_provenance_records.append(
                        {
                            "index": i,
                            "source_id": filing_entry.get("source_id"),
                            "filing_type": filing_entry.get("tipo", filing_entry.get("filing_type")),
                            "local_path": filing_entry.get("local_path"),
                            "field": rec.get("field"),
                            "selected_value": rec.get("selected_value"),
                            "currency_original": rec.get("currency_original"),
                            "unit_applied": rec.get("unit_applied"),
                            "selected_source": rec.get("selected_source"),
                            "selected_method": rec.get("selected_method"),
                            "selected_confidence": rec.get("selected_confidence"),
                            "recency": rec.get("recency"),
                            "status": rec.get("status"),
                            "diff_pct": rec.get("diff_pct"),
                            "diff_abs": rec.get("diff_abs"),
                            "material_conflict": rec.get("material_conflict"),
                            "deterministic": rec.get("deterministic"),
                            "llm": rec.get("llm"),
                        }
                    )
        else:
            filing_failures.append(
                {
                    "index": i,
                    "model_profile": result.model_profile,
                    "model": result.model,
                    "backend": result.backend,
                    "transport": result.transport,
                    "error": result.error or "No output",
                }
            )
            if result.failure_ctx:
                for attempt in result.failure_ctx.get("attempts", []) or []:
                    if isinstance(attempt, dict):
                        merged = dict(attempt)
                        merged.setdefault("model_profile", result.model_profile or result.model)
                        merged.setdefault("index", i)
                        filing_attempts.append(merged)

            provenance_records.append(
                {
                    "index": i,
                    "source_id": filing_entry.get("source_id"),
                    "filing_type": filing_entry.get("tipo", filing_entry.get("filing_type")),
                    "local_path": filing_entry.get("local_path"),
                    "success": False,
                    "model_profile": result.model_profile,
                    "model": result.model,
                    "backend": result.backend,
                    "transport": result.transport,
                    "error": result.error or "No output",
                    "dispatch_meta": dispatch_meta,
                }
            )

    if successful == 0:
        common_error = ""
        for failure in filing_failures:
            if failure.get("error"):
                common_error = str(failure["error"])
                break
        if not common_error:
            common_error = "All filing extractions failed"
        failure_ctx = {
            "step_context": {
                "step": step_name,
                "mode": "tp_extractor_filing",
                "total": len(filings),
                "successful": successful,
            },
            "filings_total": len(filings),
            "filings_successful": successful,
            "sample_failures": filing_failures[:3],
            "attempts": filing_attempts[:30],
            "common_error": common_error,
            "last_error": common_error,
        }
        return {
            "success": False,
            "error": common_error,
            "backend": filing_failures[0].get("backend") if filing_failures else "unknown",
            "model": filing_failures[0].get("model") if filing_failures else "unknown",
            "transport": filing_failures[0].get("transport") if filing_failures else None,
            "model_profile": filing_failures[0].get("model_profile") if filing_failures else None,
            "attempts": filing_attempts,
            "failure_ctx": failure_ctx,
        }

    # Phase 2 provenance: per-filing extraction chain of custody (best-effort).
    try:
        provenance_payload = {
            "version": "ExtractionProvenance_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "step": step_name,
            "filings_total": len(filings),
            "filings_successful": successful,
            "records": provenance_records,
            "field_records_count": len(field_provenance_records),
            "field_records": field_provenance_records,
        }
        (case_dir / "_extraction_provenance.json").write_text(
            json.dumps(provenance_payload, indent=2, ensure_ascii=False)
        )
    except Exception as exc:
        print(f"[router] WARNING: could not write _extraction_provenance.json: {exc}", file=sys.stderr)

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
        "model_profile": first_ok.model_profile if first_ok and first_ok.model_profile else None,
        "filings_processed": successful,
        "filings_total": len(filings),
    }


def _vote_per_model(
    config: EngineConfig,
    case_dir: Path,
    step_name: str,
    vote_group_id: str | None = None,
) -> None:
    """Vote each backend's individual output for a multi-model step.

    Reads _multi_{step}_{backend}.json traces and runs quality voting on each.
    This provides per-model quality scores alongside the fusion artifact vote,
    enabling comparison of individual vs fused quality.
    """
    import glob as _glob
    pattern = str(case_dir / f"_multi_{step_name}_*.json")
    traces = _glob.glob(pattern)
    # Exclude raw traces and non-backend files
    traces = [
        t for t in traces
        if "_multi_raw_" not in t and Path(t).name.startswith(f"_multi_{step_name}_")
    ]
    if not traces:
        return
    for trace_path_str in traces:
        trace_path = Path(trace_path_str)
        # Extract backend name from filename: _multi_{STEP}_{backend}.json
        fname = trace_path.stem  # e.g., _multi_BULL_claude
        parts = fname.split("_")
        # Find backend name (last segment after step_name segments)
        step_parts = step_name.split("_")
        # Skip "_multi_" prefix (2 parts) + step_name parts
        backend_name = "_".join(parts[2 + len(step_parts):])
        if not backend_name:
            continue
        try:
            payload = json.loads(trace_path.read_text())
            if not isinstance(payload, dict):
                continue
            maybe_vote_step(
                config=config,
                case_dir=case_dir,
                step_name=step_name,
                artifact_payload=payload,
                artifact_path=trace_path,
                model=backend_name,
                backend=backend_name,
                lookup_step_name=step_name,
                vote_step_name=f"{step_name}__model_{backend_name}",
                vote_group_id=vote_group_id,
            )
        except Exception as exc:
            print(
                f"[router] WARNING: per-model voting failed for {step_name}/{backend_name}: {exc}",
                file=sys.stderr,
            )


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
        # 2. Fallback: buscar por glob, deterministic (longest name, then lexicographic last)
        candidates = sorted(
            case_dir.glob("TruthPack_v1_*.json"),
            key=lambda p: (len(p.name), p.name),
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

    # Audit trail: log which specific files were resolved for this step
    if artifacts:
        resolved_log = {name: path.name for name, path in artifacts.items()}
        print(f"[router] {step_name} input artifacts resolved: {resolved_log}")

        # For ARBITRO: persist an audit trail file so we can verify which artifacts
        # were consumed (especially important for RED_TEAM naming ambiguity)
        if step_name == "ARBITRO":
            audit_path = case_dir / "_arbitro_input_audit.json"
            try:
                audit_data = {
                    "step": step_name,
                    "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "artifacts": {
                        name: {
                            "file": path.name,
                            "size_bytes": path.stat().st_size,
                        }
                        for name, path in artifacts.items()
                    },
                }
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(case_dir),
                    prefix="._tmp_arbitro_input_",
                    suffix=".json",
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(audit_data, handle, indent=2, ensure_ascii=False)
                    Path(tmp_path).replace(audit_path)
                except Exception:
                    Path(tmp_path).unlink(missing_ok=True)
                    raise
                print(f"[router] Saved ARBITRO input audit: {audit_path.name}")
            except Exception as exc:
                print(
                    f"[router] WARNING: Could not persist ARBITRO input audit "
                    f"{audit_path.name}: {exc}",
                    file=sys.stderr,
                )

    return artifacts


def _find_artifact(case_dir: Path, pattern: str) -> Path | None:
    """Find an artifact file in case_dir matching the pattern.

    Resolution order (deterministic, no mtime dependency):
      1. Exact name match: pattern + ".json"
      2. Among matches, prefer fusion artifacts (contain _meta.fusion) over non-fusion
      3. Longest filename among matches (more specific = better)
      4. Lexicographic last (latest date/model in name convention)

    Also handles alias resolution: REDTEAM ↔ RED_TEAM to avoid naming collisions
    from legacy runs or individual backend outputs.
    """
    # Collect matches for primary + alias patterns
    primary_matches = [
        f for f in case_dir.iterdir()
        if f.is_file() and f.name.startswith(pattern) and f.suffix == ".json"
    ]

    _ALIASES = {
        "AgentReport_v1_REDTEAM": "AgentReport_v1_RED_TEAM",
        "AgentReport_v1_RED_TEAM": "AgentReport_v1_REDTEAM",
        "CatalystDetection_v1": "_catalyst_detection",
        "_catalyst_detection": "CatalystDetection_v1",
        "ForensicDetection_v1": "_forensic_detection",
        "_forensic_detection": "ForensicDetection_v1",
    }
    alias = _ALIASES.get(pattern)
    alias_matches = []
    if alias:
        alias_matches = [
            f for f in case_dir.iterdir()
            if f.is_file() and f.name.startswith(alias) and f.suffix == ".json"
            and f not in primary_matches
        ]

    matches = primary_matches + alias_matches
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Prefer fusion artifacts first (across primary+alias)
    fusion_matches = []
    for candidate in matches:
        try:
            data = json.loads(candidate.read_text())
            if isinstance(data, dict) and data.get("_meta", {}).get("fusion"):
                fusion_matches.append(candidate)
        except Exception:
            pass
    if fusion_matches:
        matches = fusion_matches

    # Within filtered set, prefer primary prefix when available
    primary_filtered = [m for m in matches if m.name.startswith(pattern)]
    if primary_filtered:
        matches = primary_filtered

    # Prefer exact primary name if present
    exact = case_dir / f"{pattern}.json"
    if exact in matches:
        selected = exact
    else:
        # Deterministic fallback: most specific name, then lexicographic last
        selected = max(matches, key=lambda p: (len(p.name), p.name))

    if primary_matches and alias_matches:
        print(
            f"[router] WARNING: Found both '{pattern}*' and '{alias}*' artifacts. "
            f"Primary: {[m.name for m in primary_matches]}, Alias: {[m.name for m in alias_matches]}. "
            f"Selected: {selected.name}",
            file=sys.stderr,
        )

    return selected


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
        "CATALYST_DETECTION": f"CatalystDetection_v1_{ticker}_{date_str}_{model_str}.json",
        "CATALYST_SCORING": f"AgentReport_v1_CATALYST_{ticker}_{date_str}_{model_str}.json",
        "FORENSIC_DETECTION": f"ForensicDetection_v1_{ticker}_{date_str}_{model_str}.json",
        "FORENSIC_SCORING": f"AgentReport_v1_FORENSIC_{ticker}_{date_str}_{model_str}.json",
        "BULL": f"AgentReport_v1_BULL_{ticker}_{date_str}_{model_str}.json",
        "RED_TEAM": f"AgentReport_v1_REDTEAM_{ticker}_{date_str}_{model_str}.json",
        "ARBITRO": f"DecisionPacket_v2_{ticker}_{date_str}_{model_str}.json",
        "MONITOR": f"MonitoringUpdate_v1_{ticker}_{date_str}_{model_str}.json",
        "SCANNER": f"ScannerReport_v1_{date_str}.json",
        "SCOUT_PREFILTRO": f"ScoutPrefiltro_v1_{date_str}.json",
        "SCOUT_Q": f"ScoutQ_v1_{date_str}.json",
        "SCOUT_E": f"ScoutE_v1_{date_str}.json",
        "SCOUT_SELECTOR": f"ScoutSelector_v1_{date_str}.json",
    }

    return artifact_map.get(step_name, f"_{step_name.lower()}_output.json")


def _infer_schema_for_step(step_name: str) -> str | None:
    """Map step to expected output schema name."""
    return get_primary_schema(step_name)


def _build_runner_args(
    step_name: str,
    case_dir: Path,
    ticker: str,
    config: EngineConfig,
    hints: dict[str, str] | None = None,
) -> list[str]:
    """Build CLI arguments for a Python runner."""
    if step_name == "PREFETCH":
        args = ["--ticker", ticker, "--case-dir", str(case_dir)]
        h = hints or {}
        if h.get("exchange"):
            args.extend(["--exchange", h["exchange"]])
        if h.get("country"):
            args.extend(["--country", h["country"]])
        if h.get("web_ir"):
            args.extend(["--web-ir", h["web_ir"]])
        return args
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
    hints: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Execute multiple steps in parallel using ThreadPoolExecutor."""
    max_workers = config.execution.get("max_parallel_backends", 3)
    results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_step = {
            executor.submit(
                execute_step, config, case_dir, step, ticker, hints=hints
            ): step
            for step in steps
        }
        for future in concurrent.futures.as_completed(future_to_step):
            step = future_to_step[future]
            try:
                results[step] = future.result()
            except Exception as e:
                error = str(e)
                failure_ctx = {
                    "step_context": {
                        "step": step,
                        "mode": "parallel_execution",
                    },
                    "last_error": error,
                }
                results[step] = {
                    "success": False,
                    "error": error,
                    "failure_ctx": failure_ctx,
                }
                mark_step_failed(case_dir, step, error, failure_meta=failure_ctx)

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

        # Some ARBITRO outputs wrap everything in a "decision_packet" key;
        # others put fields at top level.  We search both layers.
        wrapper = data.get("decision_packet", {}) if isinstance(data.get("decision_packet"), dict) else {}

        def _to_float(value):
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                s = value.strip().replace(",", ".")
                if not s:
                    return None
                try:
                    return float(s)
                except ValueError:
                    return None
            return None

        def _clamp(value, low, high):
            return max(low, min(high, value))

        def _get(*keys):
            """Search key in data top-level first, then inside decision_packet wrapper."""
            for k in keys:
                val = data.get(k)
                if val is not None:
                    return val
            for k in keys:
                val = wrapper.get(k)
                if val is not None:
                    return val
            return None

        # Try flat format first (legacy / DecisionPacket_v1)
        decision = _get("decision", "Decision")
        score = _get("score", "Score")
        confianza = _get("confianza", "Confianza")
        probabilistica = _get("probabilistica")
        sizing = None
        modelo_principal = None

        # Fall back to DecisionPacket_v2 nested format — resumen_ejecutivo
        resumen = _get("resumen_ejecutivo") or {}
        if isinstance(resumen, dict):
            if decision is None:
                decision = resumen.get("decision")
            if score is None:
                score = resumen.get("score_global", resumen.get("score"))
            if confianza is None:
                confianza = resumen.get("confianza_global_0_1", resumen.get("confianza", ""))
            sizing = resumen.get("tamaño_recomendado_pct_cartera")

        # DecisionPacket_v2: score lives in scoring_preliminar.total_0_100
        if score is None:
            scoring = _get("scoring_preliminar") or {}
            if isinstance(scoring, dict):
                score = scoring.get("total_0_100", scoring.get("total"))

        # DecisionPacket_v2: probabilistica from decision_probabilistica
        if probabilistica is None:
            dp = _get("decision_probabilistica") or {}
            if isinstance(dp, dict) and dp:
                probabilistica = dp

        # Model provenance from v2 fusion metadata.
        meta = data.get("_meta", {}) if isinstance(data.get("_meta"), dict) else {}
        if not meta and isinstance(wrapper.get("_meta"), dict):
            meta = wrapper.get("_meta")
        fusion_meta = meta.get("fusion") or {}
        modelos = fusion_meta.get("modelos_usados") or fusion_meta.get("modelos_utilizados")
        if isinstance(modelos, list) and modelos:
            joined = "+".join(str(m) for m in modelos if m)
            if joined:
                modelo_principal = joined

        # ── Monitor fields from salida_para_siguiente_agente + control ──
        salida = _get("salida_para_siguiente_agente") or {}
        if not isinstance(salida, dict):
            salida = {}
        control = _get("control") or {}
        if not isinstance(control, dict):
            control = {}

        # next_step: prefer control.next_step, fallback to salida
        raw_next_step = control.get("next_step") or salida.get("next_step")
        next_step = str(raw_next_step).strip() if raw_next_step else None

        # proxima_revision_sugerida → proxima_revision (validate YYYY-MM-DD & future)
        raw_fecha = salida.get("proxima_revision_sugerida")
        proxima_revision = None
        if isinstance(raw_fecha, str) and raw_fecha.strip():
            try:
                parsed = datetime.strptime(raw_fecha.strip(), "%Y-%m-%d").date()
                # Sanity: must be in the future (or at least today)
                if parsed >= datetime.now(timezone.utc).date():
                    proxima_revision = parsed.isoformat()
            except ValueError:
                pass

        # estado_caso: ACTIVO | EN_ESPERA | CERRADO
        raw_estado_caso = salida.get("estado_caso")
        estado_caso = str(raw_estado_caso).strip() if raw_estado_caso else None

        # monitor_input_recomendado
        raw_monitor_input = salida.get("monitor_input_recomendado")
        monitor_input = str(raw_monitor_input).strip() if raw_monitor_input else None

        norm_score = _to_float(score)
        norm_score = int(round(_clamp(norm_score, 0.0, 100.0))) if norm_score is not None else 0
        norm_confianza = _to_float(confianza)
        if norm_confianza is not None:
            norm_confianza = _clamp(norm_confianza, 0.0, 1.0)
        norm_sizing = _to_float(sizing)
        if norm_sizing is not None:
            norm_sizing = _clamp(norm_sizing, 0.0, 100.0)

        if decision is not None:
            update_decision_fields(
                case_dir,
                decision=str(decision),
                score=norm_score,
                confianza=norm_confianza,
                probabilistica=probabilistica,
                sizing=norm_sizing,
                modelo_principal=modelo_principal,
                next_step=next_step,
                proxima_revision=proxima_revision,
                estado_caso=estado_caso,
                monitor_input=monitor_input,
            )
    except (json.JSONDecodeError, OSError, ValueError):
        pass
