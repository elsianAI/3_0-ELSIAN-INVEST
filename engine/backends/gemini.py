"""Backend Gemini: gemini -p con salida JSON."""

from __future__ import annotations

import subprocess
import json
import time
from pathlib import Path

from .base import LLMBackend, DispatchResult


class GeminiBackend(LLMBackend):

    @property
    def name(self) -> str:
        return "gemini"

    def dispatch(
        self,
        prompt: str,
        output_schema: Path | None = None,
        cwd: Path | None = None,
        timeout: int = 600,
    ) -> DispatchResult:
        """
        Ejecuta gemini CLI en modo prompt.
        Lee resultado de stdout.
        """
        cmd = [
            self.binary_path, "-p", prompt,
            "--model", self.model,
            "--output-format", "json",
            "--yolo",
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
                    False, None, raw, self.model, "gemini", duration,
                    f"Non-zero exit code: {proc.returncode}. stderr: {(proc.stderr or '')[:500]}"
                )

            # Try to extract JSON from output (gemini may include preamble text)
            output = _extract_json(raw)
            if output is not None:
                return DispatchResult(True, output, raw, self.model, "gemini", duration)
            else:
                return DispatchResult(
                    False, None, raw, self.model, "gemini", duration,
                    "Could not parse JSON from output"
                )

        except subprocess.TimeoutExpired:
            return DispatchResult(
                False, None, "", self.model, "gemini", timeout, "Timeout"
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


def _extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from text that may contain non-JSON preamble."""
    # First try direct parse
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block in markdown code fence
    import re
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find first { ... } block
    brace_start = text.find("{")
    if brace_start >= 0:
        # Find matching closing brace
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        break

    return None
