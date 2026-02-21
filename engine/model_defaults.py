"""Persistent model defaults helpers for `engine defaults` commands."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import EngineConfig


def collect_persistent_defaults_snapshot(
    raw: dict,
    catalog: dict,
    config: EngineConfig,
) -> dict:
    """Collect the effective persisted defaults with only editable sections."""
    step_overrides = raw.get("step_overrides", {})
    if not isinstance(step_overrides, dict):
        step_overrides = {}

    snapshot = {
        "pipeline_models": raw.get("pipeline_models", []),
        "fusion_model": raw.get("fusion_model"),
        "default_single_model": raw.get("default_single_model"),
        "step_overrides": {},
    }

    plan = []
    try:
        plan = config.snapshot_pipeline_model_plan()
    except Exception:
        # Safe fallback if config is partially inconsistent.
        plan = []

    for entry in plan:
        if entry.step_type == "python":
            continue
        override = step_overrides.get(entry.step_name, {})
        if not isinstance(override, dict):
            continue
        step_payload = {}
        if "models" in override:
            raw_models = override.get("models")
            if isinstance(raw_models, list):
                step_payload["models"] = [m for m in raw_models if m in catalog]
            else:
                step_payload["models"] = []
        if "fusion_model" in override:
            fusion = override.get("fusion_model")
            if isinstance(fusion, str) and fusion in catalog:
                step_payload["fusion_model"] = fusion
        if step_payload:
            snapshot["step_overrides"][entry.step_name] = step_payload

    return snapshot


def format_defaults_snapshot(snapshot: dict) -> str:
    """Render snapshot into a compact human-readable block."""
    lines: list[str] = []
    lines.append("[defaults] Config file current values:")
    lines.append(
        f"  pipeline_models      : {', '.join(snapshot.get('pipeline_models', [])) or '(vacío)'}"
    )
    lines.append(
        f"  fusion_model         : {snapshot.get('fusion_model') or '(no configurado)'}"
    )
    lines.append(
        "  default_single_model : "
        f"{snapshot.get('default_single_model') or '(no configurado)'}"
    )

    overrides = snapshot.get("step_overrides", {})
    lines.append("[defaults] step_overrides (persistentes):")
    if not overrides:
        lines.append("  (none)")
        return "\n".join(lines)

    for step_name in sorted(overrides):
        payload = overrides.get(step_name, {})
        if not isinstance(payload, dict):
            continue
        models = payload.get("models")
        fusion_model = payload.get("fusion_model")
        lines.append(f"  - {step_name}:")
        if isinstance(models, list):
            lines.append(f"    models: {', '.join(models) if models else '(vacío)'}")
        if isinstance(fusion_model, str):
            lines.append(f"    fusion_model: {fusion_model}")

    return "\n".join(lines)


def coerce_profile_or_empty(raw_input: str | None) -> tuple[str | None, list[str]]:
    """Normalize profile deletion tokens used by interactive editor.

    Returns:
      - None + empty errors when the token means "clear this field" (`none`, `clear`, `-`, "").
      - profile string + errors if provided value is invalid.
    """
    if raw_input is None:
        return None, []

    value = raw_input.strip()
    if not value or value.lower() in {"none", "null", "clear", "-"}:
        return None, []

    return value, []


def load_config_raw(config_path: Path) -> tuple[dict, Path]:
    """Load raw JSON config and validate a minimal expected structure."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("engine_config.json must be a JSON object")

    version = raw.get("version")
    if not isinstance(version, str):
        raise ValueError("engine_config.json: missing or invalid 'version'")

    if "model_catalog" not in raw or not isinstance(raw.get("model_catalog"), dict):
        raise ValueError("engine_config.json: missing 'model_catalog'")
    if "pipeline_dag" not in raw or not isinstance(raw.get("pipeline_dag"), dict):
        raise ValueError("engine_config.json: missing 'pipeline_dag'")

    return raw, config_path


def ensure_v2(config: EngineConfig) -> None:
    """Raise a clear error when defaults command is used on v1 config."""
    if not config.is_v2:
        raise RuntimeError("defaults requires engine_config v2")


def resolve_model_list(raw_input: str, available_profiles: list[str]) -> tuple[list[str], list[str]]:
    """Alias for the shared profile resolver in model_plan."""
    if raw_input is None:
        return [], ["No se proporcionó ningún perfil."]

    from .model_plan import resolve_model_list as _resolve

    return _resolve(raw_input, available_profiles)


def _resolve_profile_set(raw: dict) -> set[str]:
    return set(raw.get("model_catalog", {}).keys())


def _find_step_def(raw: dict, step_name: str) -> dict | None:
    step_name = step_name.upper()
    for step_def in raw.get("pipeline_dag", {}).get("PIPELINE", []):
        if not isinstance(step_def, dict):
            continue
        if step_def.get("step") == step_name:
            return step_def
    return None


def build_global_updates(raw: dict, updates: dict) -> tuple[dict, list[str]]:
    """Apply global defaults updates and return (patched_raw, errors)."""
    new_raw = copy.deepcopy(raw)
    errors: list[str] = []
    catalog = _resolve_profile_set(raw)

    pipeline_models = updates.get("pipeline_models")
    if pipeline_models is not None:
        if not isinstance(pipeline_models, list):
            errors.append("pipeline-models debe ser una lista")
        elif not pipeline_models:
            errors.append("pipeline-models no puede estar vacío")
        else:
            invalid = [m for m in pipeline_models if m not in catalog]
            if invalid:
                errors.append("Perfiles inválidos en --pipeline-models: " + ", ".join(invalid))
            else:
                new_raw["pipeline_models"] = pipeline_models

    fusion_model = updates.get("fusion_model")
    if fusion_model is not None:
        if fusion_model not in catalog:
            errors.append(f"fusion-model desconocido: {fusion_model}")
        else:
            new_raw["fusion_model"] = fusion_model

    default_single_model = updates.get("default_single_model")
    if default_single_model is not None:
        if default_single_model not in catalog:
            errors.append(f"default_single_model desconocido: {default_single_model}")
        else:
            new_raw["default_single_model"] = default_single_model

    return new_raw, errors


def build_step_override_updates(
    raw: dict,
    step_name: str,
    models: list[str] | None,
    fusion_model: str | None,
    reset: bool,
    is_step_multi: Callable[[str], bool],
    clear_fusion_model: bool = False,
) -> tuple[dict, list[str]]:
    """Apply one-time step overrides to raw config and return (patched_raw, errors)."""
    new_raw = copy.deepcopy(raw)
    errors: list[str] = []
    step_name = step_name.upper()

    catalog = _resolve_profile_set(raw)
    step_def = _find_step_def(raw, step_name)
    if step_def is None:
        errors.append(f"Paso no encontrado en PIPELINE: {step_name}")
        return new_raw, errors

    step_type = str(step_def.get("type", "llm"))
    if step_type not in {"llm", "llm_per_filing"}:
        errors.append(f"{step_name} no admite modelos (tipo no LLM)")
        return new_raw, errors

    if reset:
        step_overrides = new_raw.get("step_overrides", {})
        step_overrides.pop(step_name, None)
        if step_overrides:
            new_raw["step_overrides"] = step_overrides
        else:
            new_raw.pop("step_overrides", None)
        return new_raw, errors

    if models is None and fusion_model is None and not clear_fusion_model:
        errors.append(f"Debes indicar --models o --fusion-model para {step_name}")
        return new_raw, errors

    if models is not None:
        if models:
            invalid = [m for m in models if m not in catalog]
            if invalid:
                errors.append(
                    f"{step_name}: perfiles inválidos: {', '.join(invalid)}"
                )
                return new_raw, errors
        override = new_raw.setdefault("step_overrides", {})
        override.setdefault(step_name, {})
        override[step_name]["models"] = models

    if clear_fusion_model:
        step_overrides = new_raw.setdefault("step_overrides", {})
        step_entry = step_overrides.get(step_name)
        if isinstance(step_entry, dict):
            step_entry.pop("fusion_model", None)
            if not step_entry:
                step_overrides.pop(step_name, None)
        if not step_overrides:
            new_raw.pop("step_overrides", None)
        return new_raw, errors

    if fusion_model is not None:
        if not is_step_multi(step_name):
            errors.append(f"{step_name}: fusion_model solo aplica a pasos multi")
        else:
            if fusion_model not in catalog:
                errors.append(f"{step_name}: perfil de fusión desconocido: {fusion_model}")
            else:
                override = new_raw.setdefault("step_overrides", {})
                override.setdefault(step_name, {})
                override[step_name]["fusion_model"] = fusion_model

    # Remove empty override dict to keep config tidy.
    step_overrides = new_raw.get("step_overrides")
    if isinstance(step_overrides, dict):
        entry = step_overrides.get(step_name)
        if isinstance(entry, dict) and not entry:
            step_overrides.pop(step_name, None)
        if not step_overrides:
            new_raw.pop("step_overrides", None)

    return new_raw, errors


def make_config_diff(old_raw: dict, new_raw: dict) -> str:
    """Return a compact diff for touched top-level keys."""
    keys = (
        "pipeline_models",
        "fusion_model",
        "default_single_model",
        "step_overrides",
    )
    lines: list[str] = []
    for key in keys:
        old_val = old_raw.get(key)
        new_val = new_raw.get(key)
        if old_val == new_val:
            continue
        if key != "step_overrides":
            lines.append(f"{key}:")
            lines.append(f"  - {json.dumps(old_val, ensure_ascii=False)}")
            lines.append(f"  + {json.dumps(new_val, ensure_ascii=False)}")
        else:
            # Step overrides may be large; only show sections that changed.
            old_overrides = old_raw.get(key, {})
            new_overrides = new_raw.get(key, {})
            if old_overrides != new_overrides:
                for step in sorted(set(old_overrides.keys()) | set(new_overrides.keys())):
                    old_step = old_overrides.get(step, {})
                    new_step = new_overrides.get(step, {})
                    if old_step == new_step:
                        continue
                    lines.append(f"step_overrides[{step}]:")
                    lines.append(f"  - {json.dumps(old_step, ensure_ascii=False)}")
                    lines.append(f"  + {json.dumps(new_step, ensure_ascii=False)}")

    if not lines:
        return "No hay cambios."
    return "\n".join(lines)


def write_engine_config_atomic(
    config_path: Path,
    new_raw: dict,
    make_backup: bool = True,
) -> str:
    """Write engine_config.json atomically and return backup path when created."""
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    handle, tmp_path = tempfile.mkstemp(prefix=config_path.name, suffix=".tmp", dir=str(config_path.parent))
    backup_path: Path | None = None
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(new_raw, f, ensure_ascii=False, indent=2)
            f.write("\n")

        if make_backup and config_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = config_path.with_suffix(
                config_path.suffix + f".bak.{timestamp}"
            )
            shutil.copy2(config_path, backup_path)

        os.replace(tmp_path, config_path)
        return str(backup_path) if backup_path else ""
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
