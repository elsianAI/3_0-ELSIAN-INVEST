"""Backend GitHub Copilot CLI (standalone binary).

Usa el binario `copilot` instalado por la extensión GitHub Copilot Chat de
VS Code. No requiere token exchange ni suscripción Pro+; funciona con la
autenticación existente de la extensión.

Binario típico en macOS:
  ~/Library/Application Support/Code - Insiders/User/globalStorage/
    github.copilot-chat/copilotCli/copilot
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from .base import LLMBackend, DispatchResult, _try_recover_json

# Steps that require tool access (browsing, web search). Must mirror
# claude.py's _TOOLS_ENABLED_STEPS to keep behaviour consistent across
# transports.
_TOOLS_ENABLED_STEPS = {
    "MONITOR",
    "SCANNER",
    "SCOUT_PREFILTRO",
    "SCOUT_Q",
    "SCOUT_E",
    "OUTCOME",
}

# Prompt prefix injected for pipeline (non-tool) steps to compensate for
# copilot CLI lacking --output-format json and --tools "" flags.
_JSON_ONLY_PREFIX = (
    "[SYSTEM CONSTRAINT] You MUST respond with ONLY a single valid JSON object. "
    "Do NOT use markdown formatting, code fences, prose, or tool calls. "
    "Start your response with { and end with }. "
    "Do NOT execute any shell commands or read any files.\n\n"
)

# ── Cache TTLs ────────────────────────────────────────────────
_AUTH_CACHE_TTL_OK   = 600   # 10 min
_AUTH_CACHE_TTL_FAIL = 60    # 60 s — retry rápido tras fix

# ── Module-level auth cache ────────────────────────────────────
# Format: {(binary_path, model): (timestamp, is_ok, reason_if_failed)}
_AUTH_CACHE: dict[tuple[str, str], tuple[float, bool, str | None]] = {}

# Models officially listed in `copilot --help` (validated by --model flag).
# Models NOT in this set are passed via GITHUB_COPILOT_MODEL env var instead,
# which bypasses CLI validation and maps to any model the backend supports
# (same pool as VS Code Copilot Chat).
_OFFICIAL_CLI_MODELS = frozenset({
    "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-haiku-4.5",
    "claude-opus-4.6", "claude-opus-4.6-fast", "claude-opus-4.5",
    "claude-sonnet-4",
    "gemini-3.1-pro-preview", "gemini-3-flash",
    "gpt-5.3-codex-spark", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
    "gpt-5.1-codex-max", "gpt-5.1-codex", "gpt-5.1",
    "gpt-5.1-codex-mini", "gpt-5-mini", "gpt-4.1",
})


# ── Helpers de output ─────────────────────────────────────────

def _strip_stats_footer(text: str) -> str:
    """Elimina el footer de estadísticas que imprime el CLI tras el contenido.

    El formato es:
        <contenido del modelo>

        Total usage est: ...
        API time spent: ...
        ...
    """
    # El footer empieza en la primera línea que comienza con "Total usage est:"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("Total usage est:"):
            return "\n".join(lines[:i]).rstrip()
    return text.rstrip()


# ── Backend ───────────────────────────────────────────────────

class CopilotBackend(LLMBackend):
    """Backend GitHub Copilot usando el binario CLI standalone.

    binary_path: path al binario `copilot` (de la extensión Copilot Chat).
    model: modelo a usar (e.g. 'gpt-5.3-codex', 'claude-sonnet-4.6').
    config: dict completo de engine_config.json.
    """

    @property
    def name(self) -> str:
        return "copilot"

    def dispatch(
        self,
        prompt: str,
        output_schema: Path | None = None,
        cwd: Path | None = None,
        timeout: int = 120,
        step_name: str | None = None,
    ) -> DispatchResult:
        """Ejecuta `copilot -p <prompt> --model <model>` en modo no-interactivo.

        El CLI imprime la respuesta del modelo seguida de un footer de stats.
        Extraemos el JSON del bloque de respuesta y descartamos el footer.
        """
        step_key = (step_name or "").strip().upper()
        tools_enabled = step_key in _TOOLS_ENABLED_STEPS

        # For pipeline steps, prefix prompt to force JSON-only output.
        # Copilot CLI has no --output-format json or --tools "" flags,
        # so the only way to constrain output is via prompt injection.
        effective_prompt = prompt if tools_enabled else (_JSON_ONLY_PREFIX + prompt)

        # Official models use --model flag; others use GITHUB_COPILOT_MODEL env var
        # (bypasses CLI validation, same backend pool as VS Code Copilot Chat).
        if self.model in _OFFICIAL_CLI_MODELS:
            cmd = [
                self.binary_path,
                "-p", effective_prompt,
                "--model", self.model,
                "--no-color",
                "--no-auto-update",
                "--no-ask-user",
            ]
            env = None  # inherit current environment
        else:
            cmd = [
                self.binary_path,
                "-p", effective_prompt,
                "--no-color",
                "--no-auto-update",
                "--no-ask-user",
            ]
            env = {**os.environ, "GITHUB_COPILOT_MODEL": self.model}

        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd) if cwd else None,
                env=env,  # None = inherit; dict = env-var-augmented for non-official models
            )
            duration = time.time() - start
            raw = proc.stdout or ""
            stderr = (proc.stderr or "").strip()

            if proc.returncode != 0 and not raw.strip():
                return DispatchResult(
                    False, None, raw, self.model, "copilot", duration,
                    f"copilot exit={proc.returncode}. stderr: {stderr[:400]}",
                    exit_code=proc.returncode,
                )

            # Separar contenido del footer de stats
            content = _strip_stats_footer(raw)

            # Extraer JSON del contenido
            output = _try_recover_json(content)
            if output is not None:
                return DispatchResult(True, output, raw, self.model, "copilot", duration, exit_code=proc.returncode)

            snippet = content.strip().replace("\n", " ")[:240]
            return DispatchResult(
                False, None, raw, self.model, "copilot", duration,
                f"Copilot result is not JSON artifact: {snippet or '<empty>'}",
                exit_code=proc.returncode,
            )

        except subprocess.TimeoutExpired:
            return DispatchResult(
                False, None, "", self.model, "copilot", float(timeout), "Timeout",
                exit_code=124,
            )
        except Exception as exc:
            return DispatchResult(
                False, None, "", self.model, "copilot", time.time() - start,
                f"Unexpected dispatch error: {exc}",
                exit_code=None,
            )

    def check_available(self) -> bool:
        """Verifica que el binario `copilot` existe y responde.

        Fases:
          1. `copilot --version` — binario accesible (FREE, 0 tokens)
          2. Resultado cacheado OK=10min, FAIL=60s
        La auth real (¿está logueado el usuario?) se detecta en el primer dispatch;
        no hacemos preflight pagado para no consumir Premium requests en cada pipeline.
        """
        cache_key = (self.binary_path, self.model)

        def _cache_store(ok: bool, reason: str | None = None) -> bool:
            _AUTH_CACHE[cache_key] = (time.time(), ok, reason)
            self.last_health_error = None if ok else reason
            self.last_health_warning = None
            return ok

        # Phase 0: serve cache
        cached = _AUTH_CACHE.get(cache_key)
        if cached:
            ts, result, reason = cached
            ttl = _AUTH_CACHE_TTL_OK if result else _AUTH_CACHE_TTL_FAIL
            if time.time() - ts < ttl:
                self.last_health_error = None if result else reason
                self.last_health_warning = None
                return result

        # Phase 1: binario existe y responde
        try:
            ver = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if ver.returncode != 0:
                return _cache_store(
                    False,
                    f"copilot --version failed (exit={ver.returncode})",
                )
            version_str = (ver.stdout or ver.stderr or "").strip()
            print(f"[copilot] binary OK: {version_str[:80]}", file=sys.stderr)
            return _cache_store(True)
        except FileNotFoundError:
            return _cache_store(
                False,
                f"copilot binary not found at: {self.binary_path}. "
                "Instala la extensión GitHub Copilot Chat en VS Code.",
            )
        except subprocess.TimeoutExpired:
            return _cache_store(False, "copilot --version timeout (10s)")
        except Exception as exc:
            return _cache_store(False, f"copilot --version error: {exc}")
