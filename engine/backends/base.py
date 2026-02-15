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
    model: str                # Modelo usado
    backend: str              # Nombre del backend
    duration_s: float         # Tiempo de ejecución
    error: str | None = None  # Mensaje de error si success=False


class LLMBackend(ABC):
    def __init__(self, binary_path: str, model: str, config: dict):
        self.binary_path = binary_path
        self.model = model
        self.config = config

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
