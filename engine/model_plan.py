"""Utilities to build and display the runtime model plan for a pipeline execution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .config import EngineConfig


@dataclass
class StepPlanEntry:
    step_name: str
    step_type: str
    models: list[str]
    transports: list[str]
    is_multi: bool
    fusion_model: str | None
    min_backends: int | None
    requires: list[str] | None = None


def build_step_plan(
    config: "EngineConfig",
    step_names: list[str] | None = None,
    operation: str = "PIPELINE",
) -> list[StepPlanEntry]:
    """Build the execution plan for a pipeline segment.

    If step_names is provided, it is interpreted as a list of pipeline_key values.
    ``operation`` selects which DAG section to read (PIPELINE, SCANNER, etc.).
    """
    allowed_keys = None
    if step_names is not None:
        allowed_keys = set(step_names)

    plan: list[StepPlanEntry] = []
    for step_def in config.get_dag(operation):
        step_name = step_def.get("step")
        if not isinstance(step_name, str):
            continue

        step_type = step_def.get("type", "llm")
        if step_type not in {"llm", "llm_per_filing", "python"}:
            continue

        pipeline_key = step_def.get("pipeline_key")
        if allowed_keys is not None and pipeline_key not in allowed_keys:
            continue

        if step_type == "python":
            plan.append(
                StepPlanEntry(
                    step_name=step_name,
                    step_type="python",
                    models=["python"],
                    transports=["python"],
                    is_multi=False,
                    fusion_model=None,
                    min_backends=None,
                    requires=step_def.get("requires"),
                )
            )
            continue

        models = config.get_models_for_step(step_name)
        transports = [config.resolve_transport_name(model_name) for model_name in models]
        is_multi = config.is_step_multi(step_name)
        fusion_model = config.get_fusion_model_for_step(step_name) if is_multi else None
        min_backends = config.get_min_backends(step_name) if is_multi else None

        plan.append(
            StepPlanEntry(
                step_name=step_name,
                step_type=step_type,
                models=models,
                transports=transports,
                is_multi=is_multi,
                fusion_model=fusion_model,
                min_backends=min_backends,
                requires=step_def.get("requires"),
            )
        )

    return plan


def build_effective_model_set(plan: list[StepPlanEntry]) -> set[str]:
    """Return all model profiles used by a plan including fusion identities."""
    models: set[str] = set()
    for entry in plan:
        if entry.step_type == "python":
            continue
        models.update(entry.models)
        if entry.fusion_model:
            models.add(entry.fusion_model)
    return models


def resolve_model_list(
    raw_input: str,
    available_profiles: list[str],
) -> tuple[list[str], list[str]]:
    """Resolve model tokens into an ordered list of profile IDs.

    Supported tokens:
    - profile name (e.g. "claude-opus-4.6")
    - index (e.g. "2", "3")
    - range (e.g. "1-3")
    - "all"
    """
    normalized = raw_input.strip()
    if not normalized:
        return [], ["No se proporcionó ninguna selección de perfiles."]

    if not available_profiles:
        return [], ["No hay perfiles disponibles en el catálogo."]

    profiles = list(dict.fromkeys(available_profiles))
    profile_set = set(profiles)
    by_index: dict[int, str] = {
        idx: profile for idx, profile in enumerate(profiles, start=1)
    }

    result: list[str] = []
    seen: set[str] = set()
    errors: list[str] = []

    tokens = [token.strip() for token in re.split(r"[,\s]+", normalized) if token.strip()]
    for token in tokens:
        if token.lower() == "all":
            for profile in profiles:
                if profile not in seen:
                    result.append(profile)
                    seen.add(profile)
            continue

        if re.fullmatch(r"\d+\-\d+", token):
            parts = token.split("-", 1)
            if len(parts) != 2:
                errors.append(f"Rango inválido: {token}")
                continue

            start = int(parts[0])
            end = int(parts[1])
            if start > end:
                errors.append(f"Rango inválido (inicio > fin): {token}")
                continue
            if start < 1 or end > len(profiles):
                errors.append(f"Índice fuera de rango: {token}")
                continue

            for idx in range(start, end + 1):
                profile = by_index[idx]
                if profile not in seen:
                    result.append(profile)
                    seen.add(profile)
            continue

        if token.isdigit():
            idx = int(token)
            if idx < 1 or idx > len(profiles):
                errors.append(f"Índice inválido: {idx}")
                continue
            profile = by_index[idx]
        else:
            profile = token

        if profile not in profile_set:
            errors.append(f"Perfil desconocido: {profile}")
            continue
        if profile not in seen:
            result.append(profile)
            seen.add(profile)

    if errors:
        return result, errors
    if not result:
        return [], ["No se seleccionaron perfiles válidos."]
    return result, []


def render_plan_table(
    plan: list[StepPlanEntry],
    availability: dict[str, bool | tuple[bool, str | None]],
    width: int = 120,
) -> str:
    """Render a compact ASCII table showing plans and availability."""
    headers = ["Step", "Tipo", "Modelos", "Transports", "Req", "Fusión", "Estado", "Notas"]
    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for idx, entry in enumerate(plan, start=1):
        # --- capability requirement indicators ---
        req_icons: list[str] = []
        if entry.requires:
            if "tools" in entry.requires:
                req_icons.append("🔧")
            if "web_access" in entry.requires:
                req_icons.append("🌐")
        req_text = " ".join(req_icons) if req_icons else "—"

        if entry.step_type == "python":
            models_text = "—"
            transports_text = "—"
            status_text = "—"
            notes = "Python step (no modelo LLM)"
            rows.append((
                f"{idx:>3}. {entry.step_name}",
                "python",
                models_text,
                transports_text,
                req_text,
                "—",
                status_text,
                notes,
            ))
            continue

        model_icons: list[str] = []
        for model_name in entry.models:
            if model_name in availability:
                state = availability[model_name]
                is_copilot_fallback = (
                    isinstance(state, tuple)
                    and len(state) >= 3
                    and state[2] == "copilot_fallback"
                )
                if isinstance(state, tuple):
                    state = state[0]
                if state:
                    model_icons.append("✓")
                elif is_copilot_fallback:
                    model_icons.append("↻")
                else:
                    model_icons.append("✗")
            else:
                model_icons.append("—")
        status_text = " ".join(model_icons) if model_icons else "—"

        fusion_model = entry.fusion_model or "—"
        if entry.fusion_model:
            if entry.fusion_model in availability:
                state = availability[entry.fusion_model]
                if isinstance(state, tuple):
                    state = state[0]
                fusion_model = f"{entry.fusion_model} ({'✓' if state else '✗'})"
        else:
            fusion_model = "—"

        notes = ""
        if entry.is_multi and entry.min_backends is not None and len(entry.models) < entry.min_backends:
            notes = f"⚠ requires ≥ {entry.min_backends} backends"

        rows.append((
            f"{idx:>3}. {entry.step_name}",
            f"{entry.step_type} ({'multi' if entry.is_multi else 'single'})",
            ", ".join(entry.models) if entry.models else "—",
            "/".join(entry.transports) if entry.transports else "—",
            req_text,
            fusion_model,
            status_text,
            notes,
        ))

    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            if len(value) > col_widths[idx]:
                col_widths[idx] = len(value)

    # Keep readable output bounded; don't enforce strict truncation per-column.
    line = "-" * width
    out = [line]
    header_line = " | ".join(
        h.ljust(col_widths[i]) for i, h in enumerate(headers)
    )
    out.append(header_line)
    out.append("-" * min(width, sum(col_widths) + 3 * (len(headers) - 1)))
    for row in rows:
        out.append(" | ".join(
            str(value).ljust(col_widths[i]) for i, value in enumerate(row)
        ))
    out.append(line)
    return "\n".join(out)


def parse_step_overrides(
    raw_input: str,
    model_catalog: set[str],
    plan: list[StepPlanEntry],
) -> tuple[dict[str, dict], list[str]]:
    """Parse step overrides from user input.

    Supported formats:
      - BULL=claude-opus-4.6,gemini-3-flash,fusion:claude-opus-4.6
      - BULL=fusion:claude-opus-4.6
      - 3=claude-opus-4.6,fusion:claude-opus-4.6
    """
    normalized_input = raw_input.strip()
    if not normalized_input:
        return {}, ["No se proporcionó ningún override"]

    entries = [chunk.strip() for chunk in normalized_input.split(";") if chunk.strip()]
    if not entries:
        return {}, ["Formato de override inválido"]

    by_name = {entry.step_name: entry for entry in plan}
    by_index: dict[int, StepPlanEntry] = {idx: entry for idx, entry in enumerate(plan, start=1)}

    overrides: dict[str, dict] = {}
    errors: list[str] = []

    pattern = re.compile(r"^\s*([^=]+)\s*=\s*(.+)\s*$")
    for chunk in entries:
        match = pattern.match(chunk)
        if not match:
            errors.append(f"Formato inválido: '{chunk}' (usa STEP=perfil1,perfil2 o STEP=fusion:perfil)")
            continue

        left = match.group(1).strip()
        right = match.group(2).strip()
        if not right:
            errors.append(f"Sin modelos para '{left}'")
            continue

        model_tokens: list[str] = []
        fusion_model = None
        parse_error = False

        for token in right.split(","):
            token = token.strip()
            if not token:
                continue

            token_key, sep, token_value = token.partition(":")
            if sep and token_key.strip().lower() == "fusion":
                fusion_model = token_value.strip()
                if not fusion_model:
                    errors.append(f"Sin modelo de fusión para '{left}'")
                    parse_error = True
                    break
            else:
                model_tokens.append(token)

        if parse_error:
            continue

        resolved_models: list[str] = []
        if model_tokens:
            resolved_models, model_parse_errors = resolve_model_list(
                ",".join(model_tokens),
                sorted(model_catalog),
            )
            if model_parse_errors:
                errors.extend(f"{left}: {err}" for err in model_parse_errors)
                continue

        if not resolved_models and fusion_model is None:
            errors.append(f"Sin modelos para '{left}'")
            continue

        if left.isdigit():
            idx = int(left)
            if idx not in by_index:
                errors.append(f"Índice inválido: {idx}")
                continue
            if by_index[idx].step_type == "python":
                errors.append(f"El paso '{by_index[idx].step_name}' (índice {idx}) no acepta modelos (step python)")
                continue
            step_name = by_index[idx].step_name
            entry = by_index[idx]
        else:
            step_name = left.upper()
            if step_name not in by_name:
                errors.append(f"Paso inválido: {left}")
                continue

            if by_name[step_name].step_type == "python":
                errors.append(f"El paso '{step_name}' no acepta modelos (step python)")
                continue
            entry = by_name[step_name]

        if fusion_model is not None and fusion_model not in model_catalog:
            errors.append(f"{step_name}: perfil de fusión desconocido: {fusion_model}")
            continue

        if resolved_models:
            invalid_profiles = [p for p in resolved_models if p not in model_catalog]
            if invalid_profiles:
                errors.append(
                    f"{step_name}: perfil(es) desconocido(s): {', '.join(invalid_profiles)}"
                )
                continue

        if fusion_model is not None and not entry.is_multi:
            errors.append(
                f"{step_name}: no tiene fusión (fusion_model solo aplica a pasos multi)"
            )
            continue

        current = overrides.setdefault(step_name, {})
        if model_tokens:
            current["models"] = resolved_models
        if fusion_model is not None:
            current["fusion_model"] = fusion_model

    return overrides, errors
