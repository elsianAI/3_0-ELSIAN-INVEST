"""Carga engine_config.json, resuelve binarios, valida versiones.

Soporta config v1 (legacy) y v2 (model-centric).
"""

from __future__ import annotations

import json
import subprocess
import shutil
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ResolvedBinary:
    name: str
    path: str | None
    version: str | None
    available: bool
    error: str | None = None


@dataclass
class ModelTransport:
    """A specific way to invoke a model (e.g., via codex CLI, claude CLI, copilot CLI)."""
    transport_name: str        # "codex", "claude", "gemini", "copilot"
    binary: str                # resolved binary path
    model_id: str              # model ID to pass to CLI (e.g., "gpt-5.3-codex-spark", "opus")
    timeout_seconds: int
    flags: list[str] = field(default_factory=list)
    command_suffix: list[str] = field(default_factory=list)
    output_file_flag: str | None = None
    output_schema_flag: str | None = None
    version_flag: str = "--version"
    reasoning_effort: str | None = None
    preflight_disable_yolo: bool = False


@dataclass
class ModelSpec:
    """Everything about a model: identity + available transports."""
    name: str                           # canonical name, e.g., "gpt-5.3-codex"
    transports: list[ModelTransport]    # ordered: primary first, copilot last

    @property
    def primary_transport(self) -> ModelTransport | None:
        for t in self.transports:
            if t.transport_name != "copilot":
                return t
        return self.transports[0] if self.transports else None

    @property
    def copilot_transport(self) -> ModelTransport | None:
        for t in self.transports:
            if t.transport_name == "copilot":
                return t
        return None


@dataclass
class EngineConfig:
    raw: dict
    workspace: Path
    # v2: model catalog (populated for v2 configs)
    model_catalog: dict[str, ModelSpec] = field(default_factory=dict)
    copilot_binary: ResolvedBinary | None = None
    # v1 compat: binary resolution (populated for v1 configs)
    binaries: dict[str, ResolvedBinary] = field(default_factory=dict)
    _resolved_paths: dict[str, Path] = field(default_factory=dict)
    _backend_availability: dict[str, bool] = field(default_factory=dict)

    # ── Config version ────────────────────────────────────────

    @property
    def config_version(self) -> str:
        return self.raw.get("version", "1.0.0")

    @property
    def is_v2(self) -> bool:
        return self.config_version.startswith("2.")

    # ── v2 core accessors ─────────────────────────────────────

    @property
    def pipeline_models(self) -> list[str]:
        """The 3 base model profile IDs for multi-model steps."""
        if self.is_v2:
            return self.raw.get("pipeline_models", [])
        # v1 compat: map old backend names to model profile IDs
        defaults = self.raw.get("multi_model_tasks", {}).get("_defaults", {})
        return defaults.get("models", [self.raw.get("default_model", "codex")])

    @property
    def fusion_model(self) -> str:
        """Model profile ID for the integrator/fusion step."""
        if self.is_v2:
            return self.raw.get("fusion_model", self.pipeline_models[0] if self.pipeline_models else "")
        # v1 compat
        defaults = self.raw.get("multi_model_tasks", {}).get("_defaults", {})
        return defaults.get("fusion_model", self.raw.get("default_model", "codex"))

    @property
    def default_single_model(self) -> str:
        """Model profile ID for single-model (non-multi) steps."""
        if self.is_v2:
            return self.raw.get("default_single_model", self.pipeline_models[0] if self.pipeline_models else "")
        return self.raw.get("default_model", "codex")

    @property
    def retry_config(self) -> dict:
        if self.is_v2:
            return self.raw.get("retry", {"max_attempts": 2, "backoff_seconds": 5})
        return {"max_attempts": self.raw.get("execution", {}).get("retry_on_failure", 1), "backoff_seconds": 5}

    @property
    def copilot_transport_fallback(self) -> bool:
        if self.is_v2:
            return self.raw.get("copilot_transport_fallback", True)
        return self.raw.get("copilot_fallback", {}).get("enabled", True)

    @property
    def escalation_enabled(self) -> bool:
        if self.is_v2:
            return self.raw.get("escalation", {}).get("enabled", False)
        return True  # v1: escalation always enabled

    # ── Step resolution (v2) ──────────────────────────────────

    def get_models_for_step(self, step_name: str) -> list[str]:
        """Return list of model profile IDs for a step.

        Resolution order:
        1. step_overrides[step].models → explicit override
        2. is multi-model step? → pipeline_models
        3. else → [default_single_model]
        """
        if self.is_v2:
            override = self.raw.get("step_overrides", {}).get(step_name, {})
            if "models" in override:
                return override["models"]
            if self.is_step_multi(step_name):
                return self.pipeline_models
            return [self.default_single_model]
        # v1 compat
        return self._v1_get_backends_for_step(step_name)

    def is_step_multi(self, step_name: str) -> bool:
        """True if step runs with multiple models + fusion.

        Resolution:
        1. step_overrides[step].multi → explicit override
        2. step listed in multi_model_steps.steps → True
        3. else → False
        """
        if self.is_v2:
            override = self.raw.get("step_overrides", {}).get(step_name, {})
            if "multi" in override:
                return override["multi"]
            steps = self.raw.get("multi_model_steps", {}).get("steps", {})
            return step_name in steps
        # v1 compat
        return self.get_multi_model_config(step_name) is not None

    def get_fusion_model_for_step(self, step_name: str) -> str:
        """Which model does fusion for this step."""
        if self.is_v2:
            override = self.raw.get("step_overrides", {}).get(step_name, {})
            return override.get("fusion_model", self.fusion_model)
        # v1 compat
        defaults = self.raw.get("multi_model_tasks", {}).get("_defaults", {})
        return defaults.get("fusion_model", self.raw.get("default_model", "codex"))

    def get_min_backends(self, step_name: str) -> int:
        """Minimum backends needed for multi-model quorum."""
        if self.is_v2:
            steps = self.raw.get("multi_model_steps", {}).get("steps", {})
            step_cfg = steps.get(step_name, {})
            if "min_backends" in step_cfg:
                return step_cfg["min_backends"]
            return self.raw.get("multi_model_steps", {}).get("min_backends", len(self.pipeline_models))
        # v1 compat
        multi_cfg = self.get_multi_model_config(step_name)
        if multi_cfg:
            return multi_cfg.get("min_backends", len(multi_cfg.get("models", [])))
        return 1

    def snapshot_pipeline_model_plan(self, step_names: list[str] | None = None):
        """Return a runtime plan snapshot for selected pipeline keys."""
        from .model_plan import build_step_plan
        return build_step_plan(self, step_names)

    def effective_model_set(self, step_names: list[str] | None = None) -> set[str]:
        """Union of model profiles used by effective step plan."""
        from .model_plan import build_step_plan, build_effective_model_set
        return build_effective_model_set(build_step_plan(self, step_names))

    def with_step_model_overrides(self, step_overrides: dict[str, dict]) -> "EngineConfig":
        """Return a runtime-only EngineConfig with patched step_overrides.

        Keeps model catalog and binary caches intact (no re-resolution).
        """
        import copy

        new_raw = copy.deepcopy(self.raw)
        existing = new_raw.setdefault("step_overrides", {})
        for step_name, override in step_overrides.items():
            existing.setdefault(step_name, {}).update(override)

        return EngineConfig(
            raw=new_raw,
            workspace=self.workspace,
            model_catalog=self.model_catalog,
            copilot_binary=self.copilot_binary,
            binaries=self.binaries,
            _resolved_paths=dict(self._resolved_paths),
            _backend_availability=dict(self._backend_availability),
        )

    def get_fusion_instruction(self, step_name: str) -> str | None:
        """Fusion instruction filename for this step."""
        if self.is_v2:
            steps = self.raw.get("multi_model_steps", {}).get("steps", {})
            step_cfg = steps.get(step_name, {})
            return step_cfg.get("fusion_instruction")
        # v1 compat
        multi_cfg = self.get_multi_model_config(step_name)
        if multi_cfg:
            return multi_cfg.get("fusion_instruction")
        return None

    def get_model_spec(self, model_name: str) -> ModelSpec | None:
        """Lookup a model in the catalog (v2 only)."""
        return self.model_catalog.get(model_name)

    def resolve_transport_name(self, model_name: str) -> str:
        """Return short transport name for primary transport of a model.

        E.g., "gpt-5.3-codex" → "codex", "claude-opus-4.6" → "claude"
        """
        spec = self.model_catalog.get(model_name)
        if spec and spec.primary_transport:
            return spec.primary_transport.transport_name
        # v1 compat: model_name IS the backend name
        return model_name

    # ── v1 compat properties ──────────────────────────────────

    @property
    def models(self) -> dict:
        return self.raw.get("models", {})

    @property
    def task_routing(self) -> dict:
        return self.raw.get("task_routing", {})

    @property
    def multi_model_tasks(self) -> dict:
        return self.raw.get("multi_model_tasks", {})

    @property
    def pipeline_dag(self) -> dict:
        return self.raw.get("pipeline_dag", {})

    @property
    def prefetch_validation(self) -> dict:
        return self.raw.get("prefetch_validation", {})

    @property
    def execution(self) -> dict:
        return self.raw.get("execution", {})

    @property
    def naming(self) -> dict:
        return self.raw.get("naming", {})

    @property
    def step_routing(self) -> dict:
        return self.task_routing

    @property
    def default_models(self) -> dict:
        return {name: cfg.get("default_model", "") for name, cfg in self.models.items()}

    @property
    def timeouts(self) -> dict:
        t = {}
        for name, cfg in self.models.items():
            t[f"{name}_default"] = cfg.get("timeout_seconds", 3600)
        t["tp_extractor_per_filing"] = self.execution.get("tp_extractor_per_filing_timeout", 300)
        t["scanner"] = 900
        return t

    # ── Path resolution ───────────────────────────────────────

    def get_path(self, key: str) -> Path:
        if key in self._resolved_paths:
            return self._resolved_paths[key]
        raw_path = self.raw.get("paths", {}).get(key, key)
        resolved = self.workspace / raw_path
        self._resolved_paths[key] = resolved
        return resolved

    # ── v1 task/model helpers (deprecated but preserved) ──────

    def get_model_for_task(self, task_name: str) -> str:
        """Retorna nombre del modelo (ej: 'codex'). v1 only."""
        routing = self.task_routing.get(task_name, {})
        return routing.get("model", self.raw.get("default_model", "codex"))

    def get_multi_model_config(self, task_name: str) -> dict | None:
        """v1 multi-model config. Returns merged defaults + per-task overrides."""
        if task_name.startswith("_"):
            return None
        mmt = self.multi_model_tasks.get(task_name)
        if mmt is None:
            return None
        defaults = {
            k: v
            for k, v in self.multi_model_tasks.get("_defaults", {}).items()
            if not k.startswith("_")
        }
        merged = {**defaults, **mmt}
        if merged.get("enabled"):
            return merged
        return None

    def get_escalation_config(self, task_name: str) -> dict | None:
        """v1 escalation config. Deprecated in v2."""
        if not self.escalation_enabled:
            return None
        routing = self.task_routing.get(task_name, {})
        if "escalate_to" in routing:
            return {
                "escalate_to": routing["escalate_to"],
                "escalate_condition": routing.get("escalate_condition", ""),
            }
        return None

    def get_dag(self, operation: str) -> list[dict]:
        return self.pipeline_dag.get(operation, [])

    def get_backend_config(self, model_name: str) -> dict:
        """v1: returns full backend config dict. v2: returns transport config from catalog."""
        if self.is_v2:
            spec = self.model_catalog.get(model_name)
            if spec and spec.primary_transport:
                t = spec.primary_transport
                return {
                    "binary": t.binary,
                    "default_model": t.model_id,
                    "model_reasoning_effort": t.reasoning_effort,
                    "timeout_seconds": t.timeout_seconds,
                    "flags": t.flags,
                    "command_suffix": t.command_suffix,
                    "output_file_flag": t.output_file_flag,
                    "output_schema_flag": t.output_schema_flag,
                    "preflight_disable_yolo": t.preflight_disable_yolo,
                }
            return {}
        return self.models.get(model_name, {})

    # ── v1 helper for step backend resolution ─────────────────

    def _v1_get_backends_for_step(self, step_name: str) -> list[str]:
        """v1: resolve backends list for a step."""
        routing = self.task_routing.get(step_name, {})
        model = routing.get("model", self.raw.get("default_model", "codex"))
        multi_cfg = self.get_multi_model_config(step_name)
        if multi_cfg:
            return multi_cfg.get("models", [model])
        return [model]

    # ── Preflight helpers ─────────────────────────────────────

    def preflight_done(self) -> bool:
        return bool(self._backend_availability)

    def is_backend_available(self, name: str) -> bool:
        if not self._backend_availability:
            return True
        return self._backend_availability.get(name, False)

    # ── Naming helpers ────────────────────────────────────────

    def generate_caso_id(self, ticker: str, fecha: str) -> str:
        d_id = fecha.replace("-", "")
        return f"CASE_{d_id}_{ticker}"

    def generate_artefacto_name(self, schema: str, ticker: str, fecha: str) -> str:
        return f"{schema}_{ticker}_{fecha}.json"

    def generate_directory(self, ticker: str, fecha: str) -> Path:
        return self.get_path("casos") / ticker / fecha


# ── Config loading ─────────────────────────────────────────

def load_config(config_path: Path | None = None) -> EngineConfig:
    """Load engine config. Supports v1 (legacy) and v2 (model-centric)."""
    if config_path is None:
        config_path = Path.cwd() / "engine_config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path) as f:
        raw = json.load(f)

    workspace = config_path.parent
    version = raw.get("version", "1.0.0")

    if version.startswith("2."):
        return _load_config_v2(raw, workspace)
    else:
        return _load_config_v1(raw, workspace)


def _load_config_v1(raw: dict, workspace: Path) -> EngineConfig:
    """Load v1 config (legacy backend-centric format)."""
    print("[config] Loading v1 config (legacy). Consider migrating to v2.", file=sys.stderr)
    binaries = {}
    for name, model_cfg in raw.get("models", {}).items():
        spec = {
            "default": model_cfg.get("binary"),
            "fallback": model_cfg.get("binary_fallback"),
            "min_version": model_cfg.get("min_version", "0.0.0"),
        }
        binaries[name] = _resolve_binary(name, spec)

    _validate_paths(raw, workspace)
    return EngineConfig(raw=raw, binaries=binaries, workspace=workspace)


def _load_config_v2(raw: dict, workspace: Path) -> EngineConfig:
    """Load v2 config (model-centric format with transport resolution)."""
    # Resolve copilot transport binary (shared across all models)
    copilot_cfg = raw.get("copilot_transport", {})
    copilot_binary = None
    if copilot_cfg.get("binary"):
        copilot_binary = _resolve_binary("copilot", {
            "default": copilot_cfg.get("binary"),
            "fallback": None,
            "min_version": copilot_cfg.get("min_version", "0.0.0"),
        })

    # Build model catalog
    model_catalog: dict[str, ModelSpec] = {}
    # Also build v1-compat binaries dict for any code still using it
    binaries: dict[str, ResolvedBinary] = {}

    for model_name, model_cfg in raw.get("model_catalog", {}).items():
        transports: list[ModelTransport] = []
        transport_list = model_cfg.get("transports", [])

        for transport_name in transport_list:
            if transport_name == "copilot":
                if copilot_binary and copilot_binary.available:
                    cop_cfg = model_cfg.get("copilot", {})
                    transports.append(ModelTransport(
                        transport_name="copilot",
                        binary=copilot_binary.path,
                        model_id=cop_cfg.get("model_id", model_name),
                        timeout_seconds=copilot_cfg.get("timeout_seconds", 300),
                    ))
            else:
                t_cfg = model_cfg.get(transport_name, {})
                binary_info = _resolve_binary(transport_name, {
                    "default": t_cfg.get("binary"),
                    "fallback": t_cfg.get("binary_fallback"),
                    "min_version": t_cfg.get("min_version", "0.0.0"),
                })
                if binary_info.available:
                    transports.append(ModelTransport(
                        transport_name=transport_name,
                        binary=binary_info.path,
                        model_id=t_cfg.get("model_id", model_name),
                        timeout_seconds=t_cfg.get("timeout_seconds", 3600),
                        flags=t_cfg.get("flags", []),
                        command_suffix=t_cfg.get("command_suffix", []),
                        output_file_flag=t_cfg.get("output_file_flag"),
                        output_schema_flag=t_cfg.get("output_schema_flag"),
                        version_flag=t_cfg.get("version_flag", "--version"),
                        reasoning_effort=t_cfg.get("reasoning_effort"),
                        preflight_disable_yolo=t_cfg.get("preflight_disable_yolo", False),
                    ))
                # Register in v1-compat binaries dict (keyed by transport name)
                if transport_name not in binaries:
                    binaries[transport_name] = binary_info

        model_catalog[model_name] = ModelSpec(
            name=model_name,
            transports=transports,
        )

    if copilot_binary:
        binaries["copilot"] = copilot_binary

    _validate_paths(raw, workspace)
    return EngineConfig(
        raw=raw,
        workspace=workspace,
        model_catalog=model_catalog,
        copilot_binary=copilot_binary,
        binaries=binaries,
    )


def _validate_paths(raw: dict, workspace: Path) -> None:
    """Validate configured paths exist."""
    for key, rel_path in raw.get("paths", {}).items():
        full_path = workspace / rel_path
        if key == "tmp":
            full_path.mkdir(parents=True, exist_ok=True)
        elif key in ("changelog", "estado_repo", "fechas_clave"):
            pass
        elif not full_path.exists():
            print(f"[config] WARNING: path '{key}' -> {full_path} does not exist", file=sys.stderr)


def validate_backends(config: EngineConfig) -> dict[str, str]:
    """Validate that required models/backends are available.

    v2: checks all unique models in pipeline_models + fusion_model + default_single_model.
    v1: checks all backends in config.binaries.
    """
    resolved = {}

    if config.is_v2:
        # Collect unique models to check
        models_to_check = set(config.pipeline_models)
        models_to_check.add(config.fusion_model)
        models_to_check.add(config.default_single_model)

        for model_name in sorted(models_to_check):
            spec = config.get_model_spec(model_name)
            if spec is None:
                raise SystemExit(
                    f"❌ Model '{model_name}' referenced in config but not found in model_catalog"
                )
            primary = spec.primary_transport
            if primary is None:
                raise SystemExit(
                    f"❌ Model '{model_name}' has no available primary transport"
                )
            print(f"  ✓ {model_name}: {primary.transport_name} @ {primary.binary} "
                  f"(model_id={primary.model_id})")
            resolved[model_name] = primary.binary

            copilot = spec.copilot_transport
            if copilot:
                print(f"    ↳ copilot fallback: {copilot.binary} (model_id={copilot.model_id})")
            elif config.copilot_transport_fallback:
                print(f"    ⚠ No copilot transport available for {model_name}")
    else:
        # v1 logic
        default_model = config.raw.get("default_model", "codex")
        for name, binary in config.binaries.items():
            if binary.available:
                print(f"  ✓ {name}: {binary.path} (v{binary.version or '?'})")
                resolved[name] = binary.path
            else:
                if name == default_model:
                    raise SystemExit(
                        f"❌ Backend '{name}' no encontrado. "
                        f"Probé: {config.models[name].get('binary')}, "
                        f"{config.models[name].get('binary_fallback')}"
                    )
                print(f"  ⚠ Backend '{name}' no disponible (opcional)")

    return resolved


def _resolve_binary(name: str, spec: dict) -> ResolvedBinary:
    """Intenta default, luego fallback. shutil.which() para PATH."""
    min_version = spec.get("min_version", "0.0.0")

    for attempt in ("default", "fallback"):
        candidate = spec.get(attempt)
        if candidate is None:
            continue

        resolved_path = candidate
        if not Path(candidate).is_absolute():
            found = shutil.which(candidate)
            if found:
                resolved_path = found
            else:
                continue

        if not Path(resolved_path).exists():
            continue

        try:
            version = _check_version(resolved_path, min_version)
            return ResolvedBinary(
                name=name, path=resolved_path, version=version, available=True,
            )
        except Exception as e:
            return ResolvedBinary(
                name=name, path=resolved_path, version=None, available=True,
                error=f"Version check failed: {e}",
            )

    return ResolvedBinary(
        name=name, path=None, version=None, available=False,
        error=f"No binary found for {name}",
    )


def _check_version(binary_path: str, min_version: str) -> str:
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.strip() + result.stderr.strip()
        match = re.search(r"(\d+\.\d+\.\d+)", output)
        if match:
            version = match.group(1)
            if _compare_semver(version, min_version) < 0:
                print(
                    f"[config] WARNING: {binary_path} version {version} < min {min_version}",
                    file=sys.stderr,
                )
            return version
        return output[:50]
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout checking version for {binary_path}")
    except Exception as e:
        raise RuntimeError(f"Error checking version: {e}")


def _compare_semver(v1: str, v2: str) -> int:
    def parse(v):
        parts = v.split(".")
        return tuple(int(p) for p in parts[:3])
    p1, p2 = parse(v1), parse(v2)
    if p1 < p2:
        return -1
    elif p1 > p2:
        return 1
    return 0


# Backward compat alias
def get_step_config(config: EngineConfig, step_name: str) -> dict:
    """Returns step config with dual-key format for compatibility.

    Returns dict with both "backends" and "models" keys:
    - "backends": list of backend/transport names (v1 compat)
    - "models": list of model profile IDs (v2)
    - "multi": bool
    """
    # 1. Check DAG first for python / llm_per_filing steps
    for dag_steps in config.pipeline_dag.values():
        for step_def in dag_steps:
            if step_def.get("step") == step_name:
                step_type = step_def.get("type", "llm")
                if step_type == "python":
                    return {"backends": ["python"], "models": ["python"], "multi": False}
                if step_type == "llm_per_filing":
                    if config.is_v2:
                        models = config.get_models_for_step(step_name)
                        backends = [config.resolve_transport_name(m) for m in models]
                        return {"backends": backends, "models": models, "multi": False, "parallel_by": "filing"}
                    else:
                        model = config.get_model_for_task(step_name)
                        return {"backends": [model], "models": [model], "multi": False, "parallel_by": "filing"}
                break

    # 2. Resolve via v2 or v1 accessors
    if config.is_v2:
        models = config.get_models_for_step(step_name)
        is_multi = config.is_step_multi(step_name)
        backends = [config.resolve_transport_name(m) for m in models]
        return {"backends": backends, "models": models, "multi": is_multi}
    else:
        routing = config.task_routing.get(step_name, {})
        model = routing.get("model", config.raw.get("default_model", "codex"))
        multi_cfg = config.get_multi_model_config(step_name)
        is_multi = multi_cfg is not None
        backends = multi_cfg["models"] if multi_cfg else [model]
        return {"backends": backends, "models": backends, "multi": is_multi}
