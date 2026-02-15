"""Backend Claude Code: claude -p con --output-format json."""

from __future__ import annotations

import subprocess
import json
import time
from pathlib import Path

from .base import LLMBackend, DispatchResult


class ClaudeBackend(LLMBackend):

    @property
    def name(self) -> str:
        return "claude"

    def dispatch(
        self,
        prompt: str,
        output_schema: Path | None = None,
        cwd: Path | None = None,
        timeout: int = 600,
    ) -> DispatchResult:
        """
        Ejecuta claude -p en modo no-interactivo.
        Lee resultado de stdout (JSON format).
        
        NOTA: Claude Code CLI: npm install -g @anthropic-ai/claude-code
        Este backend se usa como escalation-only (fallback).
        """
        cmd = [
            self.binary_path, "-p", prompt,
            "--model", self.model,
            "--output-format", "json",
            "--no-session-persistence",
        ]

        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd) if cwd else None,
            )
            duration = time.time() - start
            raw = proc.stdout or ""

            if proc.returncode != 0 and not raw.strip():
                return DispatchResult(
                    False, None, raw, self.model, "claude", duration,
                    f"Non-zero exit code: {proc.returncode}. stderr: {(proc.stderr or '')[:500]}"
                )

            # Claude --output-format json wraps result in a JSON envelope
            try:
                envelope = json.loads(raw)
                # Claude Code JSON output has a "result" field with the actual content
                if isinstance(envelope, dict) and "result" in envelope:
                    result_text = envelope["result"]
                    # Try to parse the result as JSON (the actual artifact)
                    if isinstance(result_text, str):
                        try:
                            output = json.loads(result_text)
                            return DispatchResult(True, output, raw, self.model, "claude", duration)
                        except json.JSONDecodeError:
                            # Result is text, not JSON — return envelope
                            return DispatchResult(True, envelope, raw, self.model, "claude", duration)
                    elif isinstance(result_text, dict):
                        return DispatchResult(True, result_text, raw, self.model, "claude", duration)
                # Direct JSON output
                return DispatchResult(True, envelope, raw, self.model, "claude", duration)
            except json.JSONDecodeError as e:
                return DispatchResult(
                    False, None, raw, self.model, "claude", duration,
                    f"JSON parse error: {e}"
                )

        except subprocess.TimeoutExpired:
            return DispatchResult(
                False, None, "", self.model, "claude", timeout, "Timeout"
            )

    def check_available(self) -> bool:
        try:
            result = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False
