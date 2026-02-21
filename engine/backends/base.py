"""ABC para backends LLM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DispatchResult:
    success: bool
    output: dict | None       # JSON parseado del output
    raw_output: str           # Output crudo (para debug)
    model: str                # Modelo usado (model_id passed to CLI, e.g. "opus", "gpt-5.3-codex-spark")
    backend: str              # Nombre corto del backend/transporte lógico (e.g. "codex", "claude", "gemini")
    duration_s: float         # Tiempo de ejecución
    error: str | None = None  # Mensaje de error si success=False
    backends_used: list[str] | None = None  # For multi-model: which backends contributed
    routed_via: str | None = None  # Transport route (e.g. "copilot")
    fallback_reason: str | None = None  # Trigger category for fallback route
    # v2 fields: canonical model identity and transport used
    model_profile: str | None = None  # Canonical model identity (e.g. "claude-opus-4.6", "gpt-5.3-codex")
    transport: str | None = None  # Actual transport used (e.g. "claude", "copilot")
    # Optional diagnostics for structured failure/forensics.
    exit_code: int | None = None
    attempt: int | None = None  # Last attempt number that produced this result
    attempts: list[dict] | None = None  # Attempt-by-attempt trace when available
    failure_ctx: dict | None = None  # Compact structured failure context (persisted to state)


class LLMBackend(ABC):
    def __init__(self, binary_path: str, model: str, config: dict):
        self.binary_path = binary_path
        self.model = model
        self.config = config
        # Populated by check_available() for operator-facing diagnostics.
        self.last_health_error: str | None = None
        # Optional warning when backend is available in degraded mode.
        self.last_health_warning: str | None = None

    @abstractmethod
    def dispatch(
        self,
        prompt: str,
        output_schema: Path | None = None,
        cwd: Path | None = None,
        timeout: int = 600,
    ) -> DispatchResult:
        """Envía prompt al backend, espera resultado, retorna DispatchResult."""

    @abstractmethod
    def check_available(self) -> bool:
        """Verifica que el backend está operativo."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre del backend (codex, gemini, claude)."""


# ── JSON recovery utility ─────────────────────────────────────────────────────

import json as _json
import re as _re


def _try_recover_json(raw: str, error: str | None = None) -> dict | None:
    """Intenta recuperar un dict JSON de texto con formato inválido.

    Si se pasa ``error``, actúa como guardia: solo procede si el error es de
    tipo JSON (parse/decode/escape). Si ``error`` es None, ejecuta la cascada
    siempre (uso interno de backends para extracción pura sin filtrado).
    """
    if error is not None:
        lowered = error.lower()
        if not any(k in lowered for k in ("json", "parse", "decode", "escape")):
            return None

    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Intento 1: parse directo
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass

    # Intento 2: sanitizar escapes inválidos (\X donde X no pertenece al set JSON)
    sanitized = _re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
    if sanitized != text:
        try:
            return _json.loads(sanitized)
        except _json.JSONDecodeError:
            pass

    # Intento 3: extraer contenido de markdown fence (```json...``` o ```...```)
    md_match = _re.search(r"```(?:json)?\s*\n(.*?)\n```", text, _re.DOTALL)
    if md_match:
        try:
            return _json.loads(md_match.group(1))
        except _json.JSONDecodeError:
            pass

    # Intento 4: extraer primer bloque {...} balanceado
    brace_start = text.find("{")
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return _json.loads(text[brace_start:i + 1])
                    except _json.JSONDecodeError:
                        break

    return None
