"""Lee/escribe _estado.json por caso. Schema: caso_estado_v1.

Implements §3.2 of PLAN COMPLETO.
"""

from __future__ import annotations

import fcntl
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from .diagnostics import compact_failure_ctx

PIPELINE_STEPS = [
    "SOURCES", "TRUTH_PACK", "IMPLIED",
    "CATALYST", "FORENSIC",
    "BULL", "RED_TEAM", "ARBITRO",
]

PIPELINE_STATUSES = ["INCOMPLETO", "EN_PROGRESO", "COMPLETO", "FALLIDO"]

SUB_STEPS = {
    "SOURCES": ["PREFETCH", "SOURCES_COMPILER"],
    "TRUTH_PACK": ["TP_EXTRACTOR_FILING", "TP_EXTRACTOR_MERGER", "TP_CALCULATOR", "TP_VALIDATOR"],
    "CATALYST": ["CATALYST_DETECTION", "CATALYST_SCORING"],
    "FORENSIC": ["FORENSIC_DETECTION", "FORENSIC_SCORING"],
}

# Map parent steps to sub-steps for status propagation
PARENT_OF_SUB = {}
for parent, subs in SUB_STEPS.items():
    for sub in subs:
        PARENT_OF_SUB[sub] = parent

_EMPRESA_HINT_KEYS = ("exchange", "country", "web_ir")


def _sanitize_hint(value: str | None) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _normalize_hints(hints: dict | None) -> dict[str, str]:
    raw = hints or {}
    return {k: _sanitize_hint(raw.get(k)) for k in _EMPRESA_HINT_KEYS}


def _state_lock_path(case_dir: Path) -> Path:
    """Return path for the per-case advisory lock file."""
    return case_dir / "_estado.lock"


def load_state(case_dir: Path) -> dict:
    """Lee _estado.json con shared lock, retorna dict.

    For read-only access. If you need read-modify-write, use
    read_modify_write() instead to hold an exclusive lock across the
    entire operation and avoid TOCTOU races.
    """
    state_file = case_dir / "_estado.json"
    if not state_file.exists():
        raise FileNotFoundError(f"No state file: {state_file}")
    lock_path = _state_lock_path(case_dir)
    lock_path.touch(exist_ok=True)
    with open(lock_path) as lf:
        fcntl.flock(lf, fcntl.LOCK_SH)
        try:
            with open(state_file) as f:
                return json.load(f)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def save_state(case_dir: Path, state: dict) -> None:
    """Escribe _estado.json atómicamente (write-tmp + rename) con exclusive lock."""
    state_file = case_dir / "_estado.json"
    state["_meta"] = state.get("_meta", {})
    state["_meta"]["ultima_actualizacion"] = datetime.now(timezone.utc).isoformat()

    lock_path = _state_lock_path(case_dir)
    lock_path.touch(exist_ok=True)
    with open(lock_path) as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            _write_state_unlocked(case_dir, state)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _write_state_unlocked(case_dir: Path, state: dict) -> None:
    """Write state file atomically. Caller MUST hold exclusive lock."""
    state_file = case_dir / "_estado.json"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(case_dir), suffix=".tmp", prefix="_estado_"
    )
    try:
        with open(fd, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        Path(tmp_path).replace(state_file)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def read_modify_write(case_dir: Path, modifier) -> dict:
    """Atomic read-modify-write under a single exclusive lock.

    ``modifier`` is called with the current state dict and should mutate
    it in place (return value is ignored).  The modified state is written
    back before the lock is released, preventing TOCTOU races when two
    concurrent processes try to update different fields.

    Returns the final state dict.
    """
    state_file = case_dir / "_estado.json"
    if not state_file.exists():
        raise FileNotFoundError(f"No state file: {state_file}")
    lock_path = _state_lock_path(case_dir)
    lock_path.touch(exist_ok=True)
    with open(lock_path) as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            with open(state_file) as f:
                state = json.load(f)
            modifier(state)
            state["_meta"] = state.get("_meta", {})
            state["_meta"]["ultima_actualizacion"] = datetime.now(timezone.utc).isoformat()
            _write_state_unlocked(case_dir, state)
            return state
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def mark_step_done(
    case_dir: Path,
    step_name: str,
    model: str = "python",
    artefacto: str | None = None,
    model_profile: str | None = None,
) -> None:
    """Marca step como DONE en _estado.json, actualiza timestamp.

    Uses read_modify_write() to hold an exclusive lock for the entire
    read-modify-write cycle, preventing TOCTOU races when parallel
    steps (e.g. CATALYST || FORENSIC) complete at the same time.

    Also clears any stale _errors entry for this step (or its parent)
    so that previous failures don't pollute auditing after a successful re-run.
    """
    now = datetime.now(timezone.utc).isoformat()

    resolved_target_step: str | None = None

    def _modifier(state: dict) -> None:
        nonlocal resolved_target_step
        if step_name in PARENT_OF_SUB:
            parent = PARENT_OF_SUB[step_name]
            sub_steps = state.setdefault("sub_steps", {})
            entry = {
                "status": "DONE",
                "timestamp": now,
                "model": model,
            }
            if model_profile:
                entry["model_profile"] = model_profile
            sub_steps[step_name] = entry
            # Check if all sub-steps of parent are done
            all_done = all(
                sub_steps.get(s, {}).get("status") == "DONE"
                for s in SUB_STEPS[parent]
            )
            if all_done:
                state["pipeline"][parent] = {
                    "estado": "DONE",
                    "artefacto": artefacto,
                    "artefacto_previo": None,
                }
                if model_profile:
                    state["pipeline"][parent]["model_profile"] = model_profile
                # Clear stale parent error
                if "_errors" in state and parent in state["_errors"]:
                    del state["_errors"][parent]
                resolved_target_step = parent
        else:
            entry = {
                "estado": "DONE",
                "artefacto": artefacto,
                "artefacto_previo": None,
            }
            if model_profile:
                entry["model_profile"] = model_profile
            state["pipeline"][step_name] = entry
            # Clear stale error for this step
            if "_errors" in state and step_name in state["_errors"]:
                del state["_errors"][step_name]
            resolved_target_step = step_name

        # Update pipeline status
        all_pipeline_done = all(
            state["pipeline"].get(s, {}).get("estado") == "DONE"
            for s in PIPELINE_STEPS
        )
        if all_pipeline_done:
            state["estado_pipeline"] = "COMPLETO"

    read_modify_write(case_dir, _modifier)

    # Notify error_tracker only when the step (or fully-completed parent) resolved.
    if resolved_target_step:
        try:
            from .error_tracker import resolve_error  # local import to avoid circular
            ticker = case_dir.parent.name
            fecha_caso = case_dir.name
            resolve_error(
                ticker,
                resolved_target_step,
                fecha_caso,
                resolved_by="engine:mark_step_done",
            )
        except Exception:
            pass  # error_tracker is non-critical; never fail the pipeline


def mark_step_failed(case_dir: Path, step_name: str, error: str | None, failure_meta: dict | None = None) -> None:
    """Marca step como FAILED con motivo (atomic read-modify-write)."""
    now = datetime.now(timezone.utc).isoformat()
    normalized_error = (error or "").strip() if isinstance(error, str) else ""
    if not normalized_error and isinstance(failure_meta, dict):
        normalized_error = str(failure_meta.get("last_error") or "").strip()
    if not normalized_error:
        normalized_error = "unknown error"
    normalized_meta = compact_failure_ctx(failure_meta or {}, max_chars=2000) if failure_meta else None

    def _modifier(state: dict) -> None:
        if step_name in PARENT_OF_SUB:
            sub_steps = state.setdefault("sub_steps", {})
            entry = {
                "status": "FAILED",
                "timestamp": now,
                "error": normalized_error,
            }
            if normalized_meta:
                entry["failure_meta"] = normalized_meta
            sub_steps[step_name] = entry
        else:
            state["pipeline"][step_name] = {
                "estado": "FAILED",
                "artefacto": None,
                "artefacto_previo": None,
            }
            if normalized_meta:
                state["pipeline"][step_name]["failure_meta"] = normalized_meta

            failure_entry = {
                "error": normalized_error,
                "timestamp": now,
            }
            if normalized_meta:
                failure_entry["failure_meta"] = normalized_meta
            state.setdefault("_errors", {})[step_name] = failure_entry

    read_modify_write(case_dir, _modifier)

    # Persist error in central _errors/ registry (only for main pipeline steps)
    if step_name not in PARENT_OF_SUB:
        try:
            from .error_tracker import append_error  # local import to avoid circular
            ticker = case_dir.parent.name
            append_error(
                case_dir=case_dir,
                ticker=ticker,
                step=step_name,
                error_msg=normalized_error,
                failure_meta=normalized_meta,
            )
        except Exception:
            pass  # error_tracker is non-critical; never fail the pipeline


def mark_step_in_progress(case_dir: Path, step_name: str) -> None:
    """Marca step como IN_PROGRESS (atomic read-modify-write)."""
    now = datetime.now(timezone.utc).isoformat()

    def _modifier(state: dict) -> None:
        if step_name in PARENT_OF_SUB:
            sub_steps = state.setdefault("sub_steps", {})
            sub_steps[step_name] = {
                "status": "IN_PROGRESS",
                "timestamp": now,
            }
        else:
            state["pipeline"][step_name]["estado"] = "IN_PROGRESS"
        state.setdefault("_progress", {})[step_name] = {
            "started": now,
        }

    read_modify_write(case_dir, _modifier)


def get_next_step(case_dir: Path) -> str | None:
    """Devuelve primer step no-DONE según pipeline order, o None si completo.

    PENDING, FAILED, and IN_PROGRESS are all considered actionable.
    """
    state = load_state(case_dir)
    for step in PIPELINE_STEPS:
        step_state = state.get("pipeline", {}).get(step, {})
        if step_state.get("estado") != "DONE":
            return step
    return None


def init_state(
    case_dir: Path,
    ticker: str,
    date: str,
    exchange: str = "",
    country: str = "",
    web_ir: str = "",
) -> dict:
    """Crea _estado.json inicial con todos los steps PENDING."""
    caso_id = f"CASE_{date.replace('-', '')}_{ticker}"
    directorio = str(case_dir.relative_to(case_dir.parent.parent.parent))
    hints = _normalize_hints(
        {"exchange": exchange, "country": country, "web_ir": web_ir}
    )

    state = {
        "version_esquema": "caso_estado_v1",
        "caso_id": caso_id,
        "ticker": ticker,
        "bolsa": None,
        "fecha_caso": date,
        "directorio": directorio,
        "empresa_hints": {k: (v or None) for k, v in hints.items()},
        "pipeline": {
            step: {"estado": "PENDING", "artefacto": None, "artefacto_previo": None}
            for step in PIPELINE_STEPS
        },
        "estado_pipeline": "INCOMPLETO",
        "decision": None,
        "score": None,
        "confianza": None,
        "probabilistica": None,
        "next_step": None,
        "proxima_revision": None,
        "monitoring": [],
        "notas": None,
        "sub_steps": {
            sub: {"status": "PENDING"}
            for subs in SUB_STEPS.values()
            for sub in subs
        },
        "_meta": {
            "ultima_actualizacion": datetime.now(timezone.utc).isoformat(),
            "actualizado_por": f"engine:3_0",
        },
    }

    case_dir.mkdir(parents=True, exist_ok=True)
    save_state(case_dir, state)
    return state


def init_or_load_state(
    case_dir: Path,
    ticker: str,
    date: str,
    *,
    reset: bool = False,
    exchange: str = "",
    country: str = "",
    web_ir: str = "",
) -> dict:
    """Load existing state or create fresh — V5.1 B1.

    If ``reset=False`` and ``_estado.json`` exists, loads the existing state
    and updates empresa_hints (CLI > saved).  Otherwise creates from scratch.
    """
    if not reset and (case_dir / "_estado.json").exists():
        state = load_state(case_dir)
        # Update hints: CLI values take precedence over saved
        hints = _normalize_hints(
            {"exchange": exchange, "country": country, "web_ir": web_ir}
        )
        saved = _normalize_hints(state.get("empresa_hints", {}))
        merged_hints = {k: hints[k] or saved[k] or "" for k in _EMPRESA_HINT_KEYS}
        state["empresa_hints"] = {k: (v or None) for k, v in merged_hints.items()}
        state["_meta"]["ultima_actualizacion"] = datetime.now(timezone.utc).isoformat()
        save_state(case_dir, state)
        return state
    return init_state(case_dir, ticker, date, exchange=exchange, country=country, web_ir=web_ir)


def resolve_empresa_hints(
    case_dir: Path,
    exchange: str = "",
    country: str = "",
    web_ir: str = "",
) -> dict[str, str]:
    """Resolve empresa hints with precedence CLI > saved state > empty."""
    cli = _normalize_hints(
        {"exchange": exchange, "country": country, "web_ir": web_ir}
    )

    saved = {k: "" for k in _EMPRESA_HINT_KEYS}
    try:
        state = load_state(case_dir)
        saved = _normalize_hints(state.get("empresa_hints", {}))
    except FileNotFoundError:
        pass

    return {k: cli[k] or saved[k] or "" for k in _EMPRESA_HINT_KEYS}


def persist_empresa_hints(case_dir: Path, hints: dict | None) -> None:
    """Persist resolved empresa hints back to state."""
    normalized = _normalize_hints(hints)

    def _modifier(state: dict) -> None:
        state["empresa_hints"] = {k: (v or None) for k, v in normalized.items()}

    read_modify_write(case_dir, _modifier)


# ── Pipeline-level status (§3.2) ──────────────────────────

def mark_pipeline_status(case_dir: Path, status: str) -> None:
    """Set estado_pipeline to one of PIPELINE_STATUSES (atomic)."""
    if status not in PIPELINE_STATUSES:
        raise ValueError(f"Invalid pipeline status: {status}. Must be one of {PIPELINE_STATUSES}")

    def _modifier(state: dict) -> None:
        state["estado_pipeline"] = status

    read_modify_write(case_dir, _modifier)


def update_decision_fields(
    case_dir: Path,
    decision: str,
    score: int,
    confianza: float | None,
    probabilistica: dict | None = None,
    sizing: float | None = None,
    modelo_principal: str | None = None,
    next_step: str | None = None,
    proxima_revision: str | None = None,
    estado_caso: str | None = None,
    monitor_input: str | None = None,
) -> None:
    """Update decision/score/confianza(+extras) after ARBITRO (atomic).

    Also persists monitor-related fields extracted from the DecisionPacket:
    next_step, proxima_revision, estado_caso, monitor_input.
    """

    def _modifier(state: dict) -> None:
        state["decision"] = decision
        state["score"] = score
        state["confianza"] = confianza
        if probabilistica is not None:
            state["probabilistica"] = probabilistica
        if sizing is not None:
            state["sizing"] = sizing
        if modelo_principal is not None:
            state["modelo_principal"] = modelo_principal
        if next_step is not None:
            state["next_step"] = next_step
        if proxima_revision is not None:
            state["proxima_revision"] = proxima_revision
        if estado_caso is not None:
            state["estado_caso"] = estado_caso
        if monitor_input is not None:
            state["monitor_input"] = monitor_input

    read_modify_write(case_dir, _modifier)


# ── Bulk & ESTADO_REPO (§3.2) ──────────────────────────────

def load_all_case_states(casos_dir: Path) -> list[dict]:
    """Itera todos los subdirectorios de casos/, carga _estado.json de cada uno."""
    results = []
    if not casos_dir.exists():
        return results
    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            state_file = case_dir / "_estado.json"
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        results.append(json.load(f))
                except (json.JSONDecodeError, OSError):
                    pass
    return results


def update_meta_review_fields(
    case_dir: Path,
    estado: str,
    artefacto: str | None = None,
    veredicto: str | None = None,
    meta_decision: str | None = None,
    prompt_timestamp: str | None = None,
    dp_hash: str | None = None,
    dp_ref: str | None = None,
) -> None:
    """Update meta_review fields in _estado.json (atomic read-modify-write).

    Follows the same pattern as update_decision_fields().
    """

    def _modifier(state: dict) -> None:
        mr = state.setdefault("meta_review", {})
        mr["estado"] = estado
        if artefacto is not None:
            mr["artefacto"] = artefacto
        if veredicto is not None:
            mr["veredicto"] = veredicto
        if meta_decision is not None:
            mr["meta_decision"] = meta_decision
        if prompt_timestamp is not None:
            mr["prompt_timestamp"] = prompt_timestamp
        if dp_hash is not None:
            mr["dp_hash"] = dp_hash
        if dp_ref is not None:
            mr["dp_ref"] = dp_ref
        mr["timestamp"] = datetime.now(timezone.utc).isoformat()

    read_modify_write(case_dir, _modifier)


def load_estado_repo(workspace: Path) -> dict:
    """Lee ESTADO_REPO.json del workspace."""
    repo_file = workspace / "ESTADO_REPO.json"
    if not repo_file.exists():
        return {"version": "estado_repo_v1", "casos": []}
    with open(repo_file) as f:
        return json.load(f)


def save_estado_repo(workspace: Path, data: dict) -> None:
    """Escribe ESTADO_REPO.json atómicamente."""
    repo_file = workspace / "ESTADO_REPO.json"
    fd, tmp_path = tempfile.mkstemp(
        dir=str(workspace), suffix=".tmp", prefix="estado_repo_"
    )
    try:
        with open(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp_path).rename(repo_file)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
