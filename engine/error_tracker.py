"""Registro centralizado de errores del pipeline.

Mantiene dos artefactos en _errors/ (raíz del workspace):
  - error_history.jsonl : log append-only de todos los errores (OPEN y RESOLVED)
  - open_errors.json    : snapshot de errores sin resolver para lectura rápida

Schema de cada registro: error_record_v1 (_schemas/error_record_v1.json).

Diseñado para ser consumido por agentes de código (Copilot, Claude, etc.) que
necesitan entender qué falló, en qué archivo del engine y con qué contexto exacto.
"""

from __future__ import annotations

import fcntl
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────────

ERROR_RECORD_VERSION = "error_record_v1"
OPEN_ERRORS_VERSION = "open_errors_v1"

# Directorio de errores relativo a la raíz del workspace
_ERRORS_DIR_NAME = "_errors"
_HISTORY_FILE = "error_history.jsonl"
_OPEN_FILE = "open_errors.json"

# Mapa de patrones de texto → error_type
# El orden importa: se evalúa el primero que coincida
_ERROR_TYPE_PATTERNS: list[tuple[str, str]] = [
    # timeout antes que llm_failure porque puede aparecer en el mismo msg
    (r"timeout|timed?\s?out|exceeded.*time|time.*exceeded", "TIMEOUT"),
    (r"schema.*valid|valid.*schema|validation.*fail|jsonschema|required.*field|missing.*field", "SCHEMA_VALIDATION"),
    (r"parse.*error|json.*decode|invalid.*json|unexpected.*token|malformed", "PARSE_ERROR"),
    (r"llm|backend|model|claude|codex|gemini|copilot|openai|anthropic|dispatch|all.*attempt|attempt.*fail", "LLM_FAILURE"),
    (r"pipeline|estado_pipeline|incompleto|estado.*json|state.*corrupt", "PIPELINE_STATE"),
]

# Map de step → módulo/archivo más probable en el engine
_STEP_SOURCE_MAP: dict[str, dict[str, str]] = {
    "SOURCES":    {"module": "engine.router",       "file": "engine/router.py"},
    "TRUTH_PACK": {"module": "engine.router",       "file": "engine/router.py"},
    "IMPLIED":    {"module": "engine.dispatcher",   "file": "engine/dispatcher.py"},
    "CATALYST":   {"module": "engine.dispatcher",   "file": "engine/dispatcher.py"},
    "FORENSIC":   {"module": "engine.dispatcher",   "file": "engine/dispatcher.py"},
    "BULL":       {"module": "engine.dispatcher",   "file": "engine/dispatcher.py"},
    "RED_TEAM":   {"module": "engine.dispatcher",   "file": "engine/dispatcher.py"},
    "ARBITRO":    {"module": "engine.dispatcher",   "file": "engine/dispatcher.py"},
}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _workspace_root() -> Path:
    """Devuelve la raíz del workspace (dos niveles arriba de este archivo)."""
    return Path(__file__).resolve().parent.parent


def _errors_dir() -> Path:
    return _workspace_root() / _ERRORS_DIR_NAME


def _history_path() -> Path:
    return _errors_dir() / _HISTORY_FILE


def _open_errors_path() -> Path:
    return _errors_dir() / _OPEN_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> str:
    """Timestamp compacto para usar en error_id: YYYYMMDDTHHMMSSZ."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _infer_error_type(error_msg: str, failure_meta: dict[str, Any] | None) -> str:
    """Clasifica el error en uno de los tipos del enum error_type.

    Evalúa los patrones sobre el mensaje de error y el last_error del meta.
    """
    combined = error_msg or ""
    if isinstance(failure_meta, dict):
        combined += " " + str(failure_meta.get("last_error") or "")
        combined += " " + str(failure_meta.get("common_error") or "")
    combined = combined.lower()

    for pattern, error_type in _ERROR_TYPE_PATTERNS:
        if re.search(pattern, combined):
            return error_type
    return "UNKNOWN"


def _extract_engine_context(failure_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Extrae backend, transport, model_profile y attempts del failure_meta."""
    if not isinstance(failure_meta, dict):
        return {"backend": None, "transport": None, "model_profile": None, "attempts": None}

    attempts_list = failure_meta.get("attempts") or []
    attempts_count = len(attempts_list) if isinstance(attempts_list, list) else None

    step_ctx = failure_meta.get("step_context") or {}
    if not isinstance(step_ctx, dict):
        step_ctx = {}

    return {
        "backend": failure_meta.get("backend") or step_ctx.get("backend"),
        "transport": failure_meta.get("transport") or step_ctx.get("transport"),
        "model_profile": failure_meta.get("model_profile") or step_ctx.get("model"),
        "attempts": attempts_count,
    }


def _extract_diagnostics(failure_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Extrae las rutas de diagnóstico del failure_meta si existen."""
    if not isinstance(failure_meta, dict):
        return {"compact_path": None, "full_path": None}
    nested = failure_meta.get("diagnostics") or {}
    if not isinstance(nested, dict):
        return {"compact_path": None, "full_path": None}
    return {
        "compact_path": nested.get("compact_path"),
        "full_path": nested.get("full_path"),
    }


def _extract_stack_trace(failure_meta: dict[str, Any] | None) -> str | None:
    """Extrae stack trace si está presente en el failure_meta."""
    if not isinstance(failure_meta, dict):
        return None
    for key in ("stack_trace", "traceback", "exc_info", "exception"):
        val = failure_meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _make_error_id(ticker: str, fecha_caso: str, step: str) -> str:
    """Genera un error_id único: ERR_{TICKER}_{YYYYMMDD}_{STEP}_{TS}."""
    date_compact = fecha_caso.replace("-", "")
    ts = _now_ts()
    return f"ERR_{ticker}_{date_compact}_{step}_{ts}"


def _load_open_errors() -> dict[str, Any]:
    """Lee open_errors.json de forma robusta (devuelve estructura vacía si falla)."""
    path = _open_errors_path()
    if not path.exists():
        return {"version": OPEN_ERRORS_VERSION, "updated_at": None, "errors": []}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "errors" not in data:
            return {"version": OPEN_ERRORS_VERSION, "updated_at": None, "errors": []}
        return data
    except Exception:
        return {"version": OPEN_ERRORS_VERSION, "updated_at": None, "errors": []}


def _save_open_errors(data: dict[str, Any]) -> None:
    """Persiste open_errors.json de forma atómica (write+rename)."""
    path = _open_errors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".open_errors_tmp_",
        suffix=".json",
        delete=False,
    )
    try:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _append_to_history(record: dict[str, Any]) -> None:
    """Añade una línea al JSONL de historial con flock para concurrencia."""
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(line)
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ── Public API ─────────────────────────────────────────────────────────────────

def append_error(
    case_dir: Path,
    ticker: str,
    step: str,
    error_msg: str,
    failure_meta: dict[str, Any] | None = None,
) -> str:
    """Registra un nuevo error OPEN en error_history.jsonl y open_errors.json.

    Args:
        case_dir: Path al directorio del caso (ej. casos/KAR/2026-02-22).
        ticker:   Ticker en mayúsculas.
        step:     Nombre del paso del pipeline que falló.
        error_msg: Mensaje de error normalizado.
        failure_meta: Payload de fallo de compact_failure_ctx (puede ser None).

    Returns:
        error_id generado.
    """
    # Infiere fecha_caso del directorio del caso
    try:
        fecha_caso = case_dir.name  # ej. "2026-02-22"
        # Valida formato básico
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", fecha_caso):
            fecha_caso = "unknown"
    except Exception:
        fecha_caso = "unknown"

    error_id = _make_error_id(ticker, fecha_caso, step)
    now = _now_iso()

    source_context = _STEP_SOURCE_MAP.get(step, {"module": None, "file": None})
    # Si el failure_meta tiene step_context con info más específica, úsala
    if isinstance(failure_meta, dict):
        sc = failure_meta.get("step_context") or {}
        if isinstance(sc, dict):
            if sc.get("module"):
                source_context = dict(source_context)
                source_context["module"] = sc["module"]
            if sc.get("file"):
                source_context = dict(source_context)
                source_context["file"] = sc["file"]

    record: dict[str, Any] = {
        "error_id": error_id,
        "version": ERROR_RECORD_VERSION,
        "timestamp_iso": now,
        "estado": "OPEN",
        "ticker": ticker,
        "fecha_caso": fecha_caso,
        "step": step,
        "error_type": _infer_error_type(error_msg, failure_meta),
        "error_msg": error_msg,
        "stack_trace": _extract_stack_trace(failure_meta),
        "source_context": source_context,
        "engine_context": _extract_engine_context(failure_meta),
        "diagnostics": _extract_diagnostics(failure_meta),
        "case_dir": str(case_dir),
        "resolved_at": None,
        "resolved_by": None,
    }

    # Append al historial JSONL
    _append_to_history(record)

    # Actualizar snapshot open_errors.json
    # Usa write atómico pero no necesita lock ya que es snapshot
    open_data = _load_open_errors()
    errors_list: list[dict] = open_data.get("errors", [])

    # Reemplaza entrada previa del mismo ticker+step+fecha si existe (reintento sobre mismo error)
    errors_list = [
        e for e in errors_list
        if not (e.get("ticker") == ticker and e.get("step") == step and e.get("fecha_caso") == fecha_caso)
    ]
    errors_list.append(record)
    open_data["errors"] = errors_list
    _save_open_errors(open_data)

    return error_id


def resolve_error(
    ticker: str,
    step: str,
    fecha_caso: str,
    resolved_by: str = "engine:mark_step_done",
) -> bool:
    """Marca como RESOLVED el error abierto de ticker+step+fecha.

    Añade una línea RESOLVED al JSONL y elimina la entrada de open_errors.json.

    Returns:
        True si había un error abierto y se resolvió, False si no había nada.
    """
    open_data = _load_open_errors()
    errors_list: list[dict] = open_data.get("errors", [])

    target = next(
        (
            e for e in errors_list
            if e.get("ticker") == ticker
            and e.get("step") == step
            and e.get("fecha_caso") == fecha_caso
        ),
        None,
    )

    if target is None:
        return False

    # Construir registro RESOLVED para el JSONL
    resolved_record = dict(target)
    resolved_record["estado"] = "RESOLVED"
    resolved_record["resolved_at"] = _now_iso()
    resolved_record["resolved_by"] = resolved_by

    _append_to_history(resolved_record)

    # Eliminar del snapshot
    open_data["errors"] = [
        e for e in errors_list
        if not (e.get("ticker") == ticker and e.get("step") == step and e.get("fecha_caso") == fecha_caso)
    ]
    _save_open_errors(open_data)

    return True


def list_open_errors(
    ticker: str | None = None,
    step: str | None = None,
    fecha_desde: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve lista de errores abiertos, opcionalmente filtrada.

    Args:
        ticker:      Filtra por ticker (ej. "KAR"). None = todos.
        step:        Filtra por paso (ej. "BULL"). None = todos.
        fecha_desde: Filtra por fecha_caso >= fecha_desde (YYYY-MM-DD). None = todos.

    Returns:
        Lista de registros error_record_v1 con estado=OPEN.
    """
    open_data = _load_open_errors()
    errors: list[dict] = open_data.get("errors", [])

    if ticker:
        errors = [e for e in errors if e.get("ticker") == ticker.upper()]
    if step:
        errors = [e for e in errors if e.get("step") == step.upper()]
    if fecha_desde:
        errors = [e for e in errors if (e.get("fecha_caso") or "") >= fecha_desde]

    return errors


def rebuild_open_errors(workspace_root: Path | None = None) -> int:
    """Reconstruye open_errors.json escaneando todos los _estado.json de casos/.

    Útil después de un crash o pérdida de open_errors.json.
    Lee _estado.json de cada caso y popula open_errors.json con los errores
    que siguen activos (pasos con estado=FAILED en el pipeline).

    Returns:
        Número de errores activos encontrados.
    """
    root = workspace_root or _workspace_root()
    casos_dir = root / "casos"

    open_errors: list[dict[str, Any]] = []

    for estado_path in sorted(casos_dir.glob("*/*/_estado.json")):
        try:
            with open(estado_path, encoding="utf-8") as fh:
                state = json.load(fh)
        except Exception:
            continue

        ticker = state.get("ticker", "UNKNOWN")
        fecha_caso = state.get("fecha_caso", "unknown")
        case_dir_rel = str(estado_path.parent.relative_to(root))

        # Recopilar errores de _errors del _estado.json
        for step, err_entry in (state.get("_errors") or {}).items():
            if not isinstance(err_entry, dict):
                continue
            error_msg = err_entry.get("error", "unknown error")
            failure_meta = err_entry.get("failure_meta")
            record: dict[str, Any] = {
                "error_id": _make_error_id(ticker, fecha_caso, step),
                "version": ERROR_RECORD_VERSION,
                "timestamp_iso": err_entry.get("timestamp", _now_iso()),
                "estado": "OPEN",
                "ticker": ticker,
                "fecha_caso": fecha_caso,
                "step": step,
                "error_type": _infer_error_type(error_msg, failure_meta),
                "error_msg": error_msg,
                "stack_trace": _extract_stack_trace(failure_meta),
                "source_context": _STEP_SOURCE_MAP.get(step, {"module": None, "file": None}),
                "engine_context": _extract_engine_context(failure_meta),
                "diagnostics": _extract_diagnostics(failure_meta),
                "case_dir": case_dir_rel,
                "resolved_at": None,
                "resolved_by": None,
            }
            open_errors.append(record)

    open_data = {
        "version": OPEN_ERRORS_VERSION,
        "updated_at": _now_iso(),
        "errors": open_errors,
    }
    _save_open_errors(open_data)
    return len(open_errors)


def stats_open_errors() -> dict[str, Any]:
    """Devuelve estadísticas de errores abiertos agrupadas por step y ticker."""
    errors = list_open_errors()

    by_step: dict[str, int] = {}
    by_ticker: dict[str, int] = {}
    by_type: dict[str, int] = {}

    for e in errors:
        step = e.get("step", "UNKNOWN")
        ticker = e.get("ticker", "UNKNOWN")
        etype = e.get("error_type", "UNKNOWN")
        by_step[step] = by_step.get(step, 0) + 1
        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
        by_type[etype] = by_type.get(etype, 0) + 1

    return {
        "total_open": len(errors),
        "by_step": dict(sorted(by_step.items(), key=lambda x: x[1], reverse=True)),
        "by_ticker": dict(sorted(by_ticker.items(), key=lambda x: x[1], reverse=True)),
        "by_error_type": dict(sorted(by_type.items(), key=lambda x: x[1], reverse=True)),
    }
