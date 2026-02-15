"""Carga engine_config.json, resuelve binarios, valida versiones.

Implements §3.1 of PLAN COMPLETO.
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
class EngineConfig:
    raw: dict
    binaries: dict[str, ResolvedBinary]
    workspace: Path
    _resolved_paths: dict[str, Path] = field(default_factory=dict)

    # ── Properties ──────────────────────────────────────────

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

    # ── Backward compat (used by old code) ──────────────────

    @property
    def step_routing(self) -> dict:
        """Backward compat: maps task_routing to step_routing format."""
        return self.task_routing

    @property
    def default_models(self) -> dict:
        """Extract default_model from each model config."""
        return {name: cfg.get("default_model", "") for name, cfg in self.models.items()}

    @property
    def timeouts(self) -> dict:
        """Build timeouts dict from model configs."""
        t = {}
        for name, cfg in self.models.items():
            t[f"{name}_default"] = cfg.get("timeout_seconds", 3600)
        t["tp_extractor_per_filing"] = 180
        t["scanner"] = 900
        return t

    # ── Path resolution ─────────────────────────────────────

    def get_path(self, key: str) -> Path:
        if key in self._resolved_paths:
            return self._resolved_paths[key]
        raw_path = self.raw.get("paths", {}).get(key, key)
        resolved = self.workspace / raw_path
        self._resolved_paths[key] = resolved
        return resolved

    # ── Task/model helpers (§3.1) ───────────────────────────

    def get_model_for_task(self, task_name: str) -> str:
        """Retorna nombre del modelo (ej: 'codex'). Fallback a default_model."""
        routing = self.task_routing.get(task_name, {})
        return routing.get("model", self.raw.get("default_model", "codex"))

    def get_multi_model_config(self, task_name: str) -> dict | None:
        """Retorna config multi-modelo si enabled, else None."""
        mmt = self.multi_model_tasks.get(task_name)
        if mmt and mmt.get("enabled"):
            return mmt
        return None

    def get_escalation_config(self, task_name: str) -> dict | None:
        """Retorna {escalate_to, escalate_condition} si existe."""
        routing = self.task_routing.get(task_name, {})
        if "escalate_to" in routing:
            return {
                "escalate_to": routing["escalate_to"],
                "escalate_condition": routing.get("escalate_condition", ""),
            }
        return None

    def get_dag(self, operation: str) -> list[dict]:
        """Retorna lista de steps para una operación."""
        return self.pipeline_dag.get(operation, [])

    def get_backend_config(self, model_name: str) -> dict:
        """Retorna config completa del backend (binary, flags, etc)."""
        return self.models.get(model_name, {})

    # ── Naming helpers (§3.1) ───────────────────────────────

    def generate_caso_id(self, ticker: str, fecha: str) -> str:
        """CASE_20260215_CRCT"""
        d_id = fecha.replace("-", "")
        return f"CASE_{d_id}_{ticker}"

    def generate_artefacto_name(self, schema: str, ticker: str, fecha: str) -> str:
        """TruthPack_v1_CRCT_2026-02-15.json"""
        return f"{schema}_{ticker}_{fecha}.json"

    def generate_directory(self, ticker: str, fecha: str) -> Path:
        """casos/CRCT/2026-02-15"""
        return self.get_path("casos") / ticker / fecha


# ── Config loading ─────────────────────────────────────────

def load_config(config_path: Path | None = None) -> EngineConfig:
    """
    1. Lee engine_config.json
    2. Para cada model: resolve binary → default → fallback → unavailable
    3. Ejecuta --version, parsea semver
    4. Valida paths existen (crea tmp/ si falta)
    5. Retorna EngineConfig
    """
    if config_path is None:
        config_path = Path.cwd() / "engine_config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path) as f:
        raw = json.load(f)

    workspace = config_path.parent
    binaries = {}

    for name, model_cfg in raw.get("models", {}).items():
        spec = {
            "default": model_cfg.get("binary"),
            "fallback": model_cfg.get("binary_fallback"),
            "min_version": model_cfg.get("min_version", "0.0.0"),
        }
        binaries[name] = _resolve_binary(name, spec)

    # Validate paths exist
    for key, rel_path in raw.get("paths", {}).items():
        full_path = workspace / rel_path
        if key == "tmp":
            full_path.mkdir(parents=True, exist_ok=True)
        elif key in ("changelog", "estado_repo", "fechas_clave"):
            pass
        elif not full_path.exists():
            print(f"[config] WARNING: path '{key}' -> {full_path} does not exist", file=sys.stderr)

    config = EngineConfig(raw=raw, binaries=binaries, workspace=workspace)
    return config


def validate_backends(config: EngineConfig) -> dict[str, str]:
    """Resuelve binarios y verifica versiones. Retorna {name: resolved_path}.
    Raises SystemExit si default_model no disponible."""
    resolved = {}
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
    """Ejecuta --version, parsea, compara semver."""
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
    """Devuelve task_routing[step_name] or builds compat dict from old step_routing.

    Also checks the pipeline_dag for python / llm_per_filing steps so that
    sub-step names like PREFETCH and TP_EXTRACTOR_FILING are resolved.
    """
    # 1. Check DAG first — it has richer metadata (type, parallel_by, etc.)
    for dag_steps in config.pipeline_dag.values():
        for step_def in dag_steps:
            if step_def.get("step") == step_name:
                step_type = step_def.get("type", "llm")
                if step_type == "python":
                    return {"backends": ["python"], "multi": False}
                if step_type == "llm_per_filing":
                    model = config.get_model_for_task(step_name)
                    return {"backends": [model], "multi": False, "parallel_by": "filing"}
                # llm — fall through to task_routing lookup below
                break

    # 2. Check task_routing
    routing = config.task_routing.get(step_name)
    if routing is not None:
        model = routing.get("model", config.raw.get("default_model", "codex"))
        multi_cfg = config.get_multi_model_config(step_name)
        is_multi = multi_cfg is not None
        backends = multi_cfg["models"] if multi_cfg else [model]
        return {"backends": backends, "multi": is_multi}

    raise ValueError(f"Unknown step: {step_name}")
