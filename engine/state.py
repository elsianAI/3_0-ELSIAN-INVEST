"""Lee/escribe _estado.json por caso. Schema: caso_estado_v1.

Implements §3.2 of PLAN COMPLETO.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

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


def load_state(case_dir: Path) -> dict:
    """Lee _estado.json, retorna dict."""
    state_file = case_dir / "_estado.json"
    if not state_file.exists():
        raise FileNotFoundError(f"No state file: {state_file}")
    with open(state_file) as f:
        return json.load(f)


def save_state(case_dir: Path, state: dict) -> None:
    """Escribe _estado.json atómicamente (write-tmp + rename)."""
    state_file = case_dir / "_estado.json"
    state["_meta"] = state.get("_meta", {})
    state["_meta"]["ultima_actualizacion"] = datetime.now(timezone.utc).isoformat()

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(
        dir=str(case_dir), suffix=".tmp", prefix="_estado_"
    )
    try:
        with open(fd, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        Path(tmp_path).rename(state_file)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def mark_step_done(case_dir: Path, step_name: str, model: str = "python", artefacto: str | None = None) -> None:
    """Marca step como DONE en _estado.json, actualiza timestamp."""
    state = load_state(case_dir)
    now = datetime.now(timezone.utc).isoformat()

    # Check if it's a sub-step
    if step_name in PARENT_OF_SUB:
        parent = PARENT_OF_SUB[step_name]
        sub_steps = state.setdefault("sub_steps", {})
        sub_steps[step_name] = {
            "status": "DONE",
            "timestamp": now,
            "model": model,
        }
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
    else:
        state["pipeline"][step_name] = {
            "estado": "DONE",
            "artefacto": artefacto,
            "artefacto_previo": None,
        }

    # Update pipeline status
    all_pipeline_done = all(
        state["pipeline"].get(s, {}).get("estado") == "DONE"
        for s in PIPELINE_STEPS
    )
    if all_pipeline_done:
        state["estado_pipeline"] = "COMPLETO"

    save_state(case_dir, state)


def mark_step_failed(case_dir: Path, step_name: str, error: str) -> None:
    """Marca step como FAILED con motivo."""
    state = load_state(case_dir)
    now = datetime.now(timezone.utc).isoformat()

    if step_name in PARENT_OF_SUB:
        sub_steps = state.setdefault("sub_steps", {})
        sub_steps[step_name] = {
            "status": "FAILED",
            "timestamp": now,
            "error": error,
        }
    else:
        state["pipeline"][step_name] = {
            "estado": "PENDING",
            "artefacto": None,
            "artefacto_previo": None,
        }
        state.setdefault("_errors", {})[step_name] = {
            "error": error,
            "timestamp": now,
        }

    save_state(case_dir, state)


def mark_step_in_progress(case_dir: Path, step_name: str) -> None:
    """Marca step como IN_PROGRESS."""
    state = load_state(case_dir)
    now = datetime.now(timezone.utc).isoformat()

    if step_name in PARENT_OF_SUB:
        sub_steps = state.setdefault("sub_steps", {})
        sub_steps[step_name] = {
            "status": "IN_PROGRESS",
            "timestamp": now,
        }
    # For main steps, we don't change estado (schema only allows DONE/PENDING)
    # but we track in _meta
    state.setdefault("_progress", {})[step_name] = {
        "started": now,
    }

    save_state(case_dir, state)


def get_next_step(case_dir: Path) -> str | None:
    """Devuelve primer step PENDING según pipeline order, o None si completo."""
    state = load_state(case_dir)
    for step in PIPELINE_STEPS:
        step_state = state.get("pipeline", {}).get(step, {})
        if step_state.get("estado") != "DONE":
            return step
    return None


def init_state(case_dir: Path, ticker: str, date: str) -> dict:
    """Crea _estado.json inicial con todos los steps PENDING."""
    caso_id = f"CASE_{date.replace('-', '')}_{ticker}"
    directorio = str(case_dir.relative_to(case_dir.parent.parent.parent))

    state = {
        "version_esquema": "caso_estado_v1",
        "caso_id": caso_id,
        "ticker": ticker,
        "bolsa": None,
        "fecha_caso": date,
        "directorio": directorio,
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


# ── Pipeline-level status (§3.2) ──────────────────────────

def mark_pipeline_status(case_dir: Path, status: str) -> None:
    """Set estado_pipeline to one of PIPELINE_STATUSES."""
    if status not in PIPELINE_STATUSES:
        raise ValueError(f"Invalid pipeline status: {status}. Must be one of {PIPELINE_STATUSES}")
    state = load_state(case_dir)
    state["estado_pipeline"] = status
    save_state(case_dir, state)


def update_decision_fields(case_dir: Path, decision: str, score: float,
                           confianza: str, probabilistica: dict | None = None) -> None:
    """Update decision/score/confianza/probabilistica after ARBITRO."""
    state = load_state(case_dir)
    state["decision"] = decision
    state["score"] = score
    state["confianza"] = confianza
    if probabilistica is not None:
        state["probabilistica"] = probabilistica
    save_state(case_dir, state)


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
