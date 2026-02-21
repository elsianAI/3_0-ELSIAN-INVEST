"""Diagnostics helpers for failure reporting and optional artifact persistence."""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

FAILURE_BLOCK_WIDTH = 78

__all__ = [
    "format_failure_block",
    "compact_failure_ctx",
    "save_failure_artifact",
    "get_failure_artifact_path",
]


def _truncate_text(text: str, max_chars: int) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[:max_chars - 3]}..."


def _compact_payload(value: Any, budget: int, depth: int = 0) -> tuple[Any, int]:
    """Compact arbitrarily nested payload recursively under a char budget."""
    if budget <= 0:
        return None, 0
    if depth > 6:
        value = _truncate_text(str(value), max(0, budget))
        return value, max(0, budget - len(value))

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        remaining = budget
        used = 0
        for key in sorted(value.keys(), key=lambda x: str(x)):
            if remaining <= 0:
                break
            compact_key = str(key)
            key_cost = len(compact_key) + 2
            if key_cost >= remaining:
                break
            compacted, remaining = _compact_payload(value[key], remaining - key_cost, depth + 1)
            out[compact_key] = compacted
            remaining -= key_cost
            used += key_cost
        if remaining < budget:
            out = dict(out)
        return out, max(0, remaining)

    if isinstance(value, (list, tuple)):
        out_list: list[Any] = []
        remaining = budget
        for item in list(value):
            if remaining <= 0:
                break
            compacted, remaining = _compact_payload(item, remaining, depth + 1)
            out_list.append(compacted)
        return out_list, max(0, remaining)

    if isinstance(value, str):
        truncated = _truncate_text(value, min(len(value), budget))
        return truncated, max(0, budget - len(truncated))

    if isinstance(value, (int, float, bool)) or value is None:
        text = str(value)
        return value, max(0, budget - len(text))

    text = str(value)
    truncated = _truncate_text(text, min(len(text), budget))
    return truncated, max(0, budget - len(truncated))


def compact_failure_ctx(payload: Any, max_chars: int = 1800) -> dict[str, Any]:
    """Return compact structured payload (dict), bounded in size.

    The function truncates long strings and limits nesting depth to avoid bloating
    _estado.json while preserving top-level diagnostics.
    """
    if payload is None:
        return {}
    compact, _ = _compact_payload(payload, max_chars)
    if not isinstance(compact, dict):
        compact = {"value": compact}
    compact = _prune_large_text_fields(compact, max_chars // 2)
    return compact


def _prune_large_text_fields(payload: Any, budget: int) -> dict[str, Any]:
    if budget <= 0:
        return {}
    if not isinstance(payload, dict):
        return {"value": _truncate_text(payload, budget)}

    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"raw_output", "attempt", "output"} and isinstance(value, str):
            out[key] = _truncate_text(value, 320)
        else:
            out[key] = value
    compact, _ = _compact_payload(out, budget)
    if isinstance(compact, dict):
        return compact
    return {"value": compact}


def format_failure_block(
    step_name: str,
    failure_ctx: dict[str, Any] | None,
    result_error: str | None,
) -> str:
    """Render a compact diagnostic block for CLI output."""
    ctx = failure_ctx or {}
    model_profile = ctx.get("model_profile")
    backend = ctx.get("backend") or ctx.get("transport") or "unknown"
    transport = ctx.get("transport") or backend
    attempts = ctx.get("attempts") or []
    last_error = ctx.get("last_error") or result_error or "(sin mensaje de error)"
    decision_log = ctx.get("decision_log") or []
    step_context = ctx.get("step_context") or {}
    model_ctx = ctx.get("model") or "unknown"
    context_bits: list[str] = []
    if isinstance(step_context, dict):
        if step_context.get("model"):
            context_bits.append(f"model={step_context['model']}")
        if step_context.get("transport"):
            context_bits.append(f"transport={step_context['transport']}")
        if step_context.get("backend"):
            context_bits.append(f"backend={step_context['backend']}")
        if step_context.get("attempts_total"):
            context_bits.append(f"intentos={step_context['attempts_total']}")

    block: list[str] = []
    line = "─" * FAILURE_BLOCK_WIDTH
    block.append(line)
    block.append(f"[FALLO] Step: {step_name}")
    block.append(f"Estado del fallo: {last_error}")
    block.append(f"modelo={model_profile or model_ctx or 'n/a'}  backend={backend}  transport={transport}")
    if context_bits:
        block.append("Contexto: " + " | ".join(context_bits))

    if attempts:
        block.append(f"Intentos ({len(attempts)}):")
        for attempt in attempts[:6]:
            if isinstance(attempt, dict):
                phase = attempt.get("phase", "?")
                attempt_no = attempt.get("attempt", "?")
                model_id = attempt.get("model_id", "n/a")
                dur = attempt.get("duration_s")
                timeout = attempt.get("timeout")
                exit_code = attempt.get("exit_code")
                err = attempt.get("error") or "(sin error)"
                block.append(
                    f"  - #{attempt_no} {phase} | model_id={model_id} "
                    f"| timeout={timeout}s | exit={exit_code} | dur={_fmt_duration(dur)}"
                )
                if err:
                    block.append(f"    error: {_truncate_text(str(err), 240)}")
        if len(attempts) > 6:
            block.append(f"  ... and {len(attempts) - 6} additional attempt(s)")

    if decision_log:
        block.append("Decisiones:")
        block.append("  " + " | ".join(map(str, decision_log[:6])))
        if len(decision_log) > 6:
            block.append(f"  ... and {len(decision_log) - 6} more")

    common_error = ctx.get("common_error")
    if common_error:
        block.append(f"Error común: {common_error}")

    sample_failures = ctx.get("sample_failures")
    if sample_failures:
        block.append("Muestras:")
        for sample in sample_failures[:3]:
            if not isinstance(sample, dict):
                continue
            idx = sample.get("index")
            reason = sample.get("error") or "(sin detalle)"
            model_id = sample.get("model_profile") or sample.get("model") or model_profile
            block.append(f"  - idx={idx} model={model_id}: { _truncate_text(str(reason), 220)}")

    duration_series = []
    for attempt in attempts:
        if isinstance(attempt, dict) and isinstance(attempt.get("duration_s"), (int, float)):
            duration_series.append(float(attempt["duration_s"]))
    if duration_series:
        block.append(
            f"Duración total aproximada: {_fmt_duration(sum(duration_series))} "
            f"(media={_fmt_duration(statistics.mean(duration_series))})"
        )

    block.append(line)
    return "\n".join(block)


def _fmt_duration(value: Any) -> str:
    if value is None:
        return "n/a"
    if not isinstance(value, (int, float)):
        return str(value)
    if value < 1:
        return f"{value:.2f}s"
    return f"{value:.1f}s"


def get_failure_artifact_path(case_dir: Path, step_name: str) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_step = step_name.replace(os_sep := "/", "_")
    safe_step = safe_step.replace(" ", "_")
    return case_dir / "_diagnostics" / "failures" / f"{safe_step}.{ts}.json"


def save_failure_artifact(
    case_dir: Path,
    step_name: str,
    payload: dict[str, Any],
    include_raw: bool = False,
) -> str | None:
    """Persist a compact failure payload and return written path.

    If include_raw is False, tries to trim payload raw_output fields so artifacts stay
    compact while preserving structured context.
    """
    path = get_failure_artifact_path(case_dir, step_name)
    artifact_dir = path.parent
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        normalized = dict(payload)
        if not include_raw:
            normalized.pop("raw_output", None)
            normalized.pop("raw_output_truncated", None)
            normalized = compact_failure_ctx(normalized, max_chars=50000)

        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2))
        return str(path)
    except Exception:
        return None
