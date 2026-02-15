"""Backend Codex: codex exec con --output-last-message."""

from __future__ import annotations

import subprocess
import json
import tempfile
import time
from pathlib import Path

from .base import LLMBackend, DispatchResult


class CodexBackend(LLMBackend):

    @property
    def name(self) -> str:
        return "codex"

    def dispatch(
        self,
        prompt: str,
        output_schema: Path | None = None,
        cwd: Path | None = None,
        timeout: int = 600,
    ) -> DispatchResult:
        """
        Ejecuta codex exec con --output-last-message para captura robusta.
        Lee resultado de archivo temporal (no de stdout).
        """
        # Create temp file for output capture
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="codex_out_")
        output_file = Path(tmp_path)
        # Close the fd so codex can write to it
        import os
        os.close(fd)

        cmd = [
            self.binary_path, "exec", prompt,
            "--model", self.model,
            "--full-auto",
            "--output-last-message", str(output_file),
        ]

        if output_schema and output_schema.exists():
            cmd.extend(["--output-schema", str(output_schema)])

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

            if output_file.exists() and output_file.stat().st_size > 0:
                raw = output_file.read_text()
                try:
                    output = json.loads(raw)
                    return DispatchResult(True, output, raw, self.model, "codex", duration)
                except json.JSONDecodeError as e:
                    return DispatchResult(
                        False, None, raw, self.model, "codex", duration,
                        f"JSON parse error: {e}"
                    )
            else:
                # Fallback: try stdout
                raw = proc.stdout or ""
                stderr = proc.stderr or ""
                if raw.strip():
                    try:
                        output = json.loads(raw)
                        return DispatchResult(True, output, raw, self.model, "codex", duration)
                    except json.JSONDecodeError:
                        pass
                return DispatchResult(
                    False, None, raw, self.model, "codex", duration,
                    f"No output file produced. stderr: {stderr[:500]}"
                )

        except subprocess.TimeoutExpired:
            return DispatchResult(
                False, None, "", self.model, "codex", timeout, "Timeout"
            )
        finally:
            output_file.unlink(missing_ok=True)

    def check_available(self) -> bool:
        """Verifica que codex está operativo."""
        try:
            result = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False
