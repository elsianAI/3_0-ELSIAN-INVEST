"""Backend Codex: codex exec con --output-last-message."""

from __future__ import annotations

import subprocess
import json
import tempfile
import time
import sys
from pathlib import Path

from .base import LLMBackend, DispatchResult

# Module-level cache for auth pre-flight results.
# Format: {(binary_path, model): (timestamp, is_ok, reason_if_failed, warning)}
_AUTH_CACHE: dict[tuple[str, str], tuple[float, bool, str | None, str | None]] = {}
_AUTH_CACHE_TTL_OK = 600
_AUTH_CACHE_TTL_FAIL = 60


class CodexBackend(LLMBackend):

    @property
    def name(self) -> str:
        return "codex"

    def _reasoning_effort_args(self, model_name: str) -> list[str]:
        """Reasoning effort override from config."""
        # v2: check model_catalog for reasoning_effort
        catalog = (self.config or {}).get("model_catalog", {})
        for _profile_name, profile_cfg in catalog.items():
            codex_cfg = profile_cfg.get("codex", {})
            if codex_cfg.get("model_id") == model_name:
                effort = codex_cfg.get("reasoning_effort")
                if isinstance(effort, str) and effort.strip():
                    return ["-c", f"model_reasoning_effort={effort.strip()}"]
                break
        # v1 compat: check models.codex.model_reasoning_effort
        models_cfg = (self.config or {}).get("models", {})
        for model_cfg in models_cfg.values():
            if not isinstance(model_cfg, dict):
                continue
            if model_cfg.get("default_model") == self.model:
                raw = model_cfg.get("model_reasoning_effort")
                if isinstance(raw, str) and raw.strip():
                    return ["-c", f"model_reasoning_effort={raw.strip()}"]
                break
        return []

    def dispatch(
        self,
        prompt: str,
        output_schema: Path | None = None,
        cwd: Path | None = None,
        timeout: int = 600,
        step_name: str | None = None,
    ) -> DispatchResult:
        """Dispatch to exactly one model. No fallback to different models."""
        _ = step_name
        return self._dispatch_single_model(
            model_name=self.model,
            prompt=prompt,
            output_schema=output_schema,
            cwd=cwd,
            timeout=timeout,
        )

    def _dispatch_single_model(
        self,
        model_name: str,
        prompt: str,
        output_schema: Path | None,
        cwd: Path | None,
        timeout: int,
    ) -> DispatchResult:
        """Ejecuta codex exec con --output-last-message para un modelo concreto."""
        import os
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="codex_out_")
        output_file = Path(tmp_path)
        os.close(fd)

        cmd = [
            self.binary_path, "exec", prompt,
            "--model", model_name,
        ]
        cmd.extend(self._reasoning_effort_args(model_name))
        cmd.extend([
            "--full-auto",
            "--skip-git-repo-check",
            "--output-last-message", str(output_file),
        ])

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
                    return DispatchResult(
                        True, output, raw, model_name, "codex", duration,
                        exit_code=proc.returncode,
                    )
                except json.JSONDecodeError as e:
                    return DispatchResult(
                        False, None, raw, model_name, "codex", duration,
                        f"JSON parse error: {e}",
                        exit_code=proc.returncode,
                    )
            else:
                raw = proc.stdout or ""
                stderr = proc.stderr or ""
                if raw.strip():
                    try:
                        output = json.loads(raw)
                        return DispatchResult(
                            True, output, raw, model_name, "codex", duration,
                            exit_code=proc.returncode,
                        )
                    except json.JSONDecodeError:
                        pass
                # Pass full stderr as raw_output so _is_retryable_dispatch_error
                # can detect quota/rate-limit/network patterns even when stdout is empty.
                return DispatchResult(
                    False, None, raw or stderr, model_name, "codex", duration,
                    f"No output file produced. stderr: {stderr[:2000]}",
                    exit_code=proc.returncode,
                )

        except subprocess.TimeoutExpired:
            return DispatchResult(
                False, None, "", model_name, "codex", timeout, "Timeout",
                exit_code=124,
            )
        finally:
            output_file.unlink(missing_ok=True)

    def check_available(self) -> bool:
        """Check codex binary + authentication availability."""
        cache_key = (self.binary_path, self.model)
        auth_fail_markers = (
            "not logged in",
            "login required",
            "authentication required",
            "unauthorized",
            "invalid api key",
            "expired token",
            "no active session",
        )
        auth_ok_markers = (
            "logged in",
            "authenticated",
            "active session",
            "login: ok",
            "status: ok",
        )

        def _cache_store(
            ok: bool,
            reason: str | None = None,
            warning: str | None = None,
        ) -> bool:
            _AUTH_CACHE[cache_key] = (time.time(), ok, reason, warning)
            self.last_health_error = None if ok else reason
            self.last_health_warning = warning if ok else None
            return ok

        # Serve cached availability.
        cached = _AUTH_CACHE.get(cache_key)
        if cached:
            if len(cached) == 4:
                ts, ok, reason, warning = cached
            else:
                ts, ok, reason = cached
                warning = None
            ttl = _AUTH_CACHE_TTL_OK if ok else _AUTH_CACHE_TTL_FAIL
            if time.time() - ts < ttl:
                self.last_health_error = None if ok else reason
                self.last_health_warning = warning if ok else None
                return ok

        # Phase 1: binary exists
        try:
            result = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return _cache_store(
                    False,
                    f"codex --version failed (exit={result.returncode})",
                )
        except Exception as exc:
            return _cache_store(False, f"codex --version error: {exc}")

        # Phase 2: free auth check
        try:
            auth = subprocess.run(
                [self.binary_path, "login", "status"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = ((auth.stdout or "") + "\n" + (auth.stderr or "")).strip()
            low = output.lower()
            if auth.returncode == 0:
                if not output:
                    return _cache_store(False, "codex login status returned empty output")
                if any(marker in low for marker in auth_fail_markers) or "logged in: false" in low:
                    return _cache_store(False, "codex login status: not logged in")
                if any(marker in low for marker in auth_ok_markers):
                    return _cache_store(True)
                print(
                    f"[codex] login status ambiguous output, using fallback probe: {output[:120]}",
                    file=sys.stderr,
                )

            legacy_markers = (
                "unknown",
                "unrecognized",
                "invalid",
                "unexpected argument",
                "usage:",
            )
            if not any(marker in low for marker in legacy_markers):
                short = output[:200] if output else f"exit={auth.returncode}"
                return _cache_store(False, f"codex login status failed: {short}")
        except subprocess.TimeoutExpired:
            return _cache_store(False, "codex login status timeout (15s)")
        except Exception as exc:
            print(
                f"[codex] WARNING: login status check errored, using fallback probe: {exc}",
                file=sys.stderr,
            )

        # Phase 3 (legacy fallback): minimal paid probe
        import os
        fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="codex_health_")
        output_file = Path(tmp_path)
        os.close(fd)
        try:
            probe = subprocess.run(
                [
                    self.binary_path, "exec", "respond with ok",
                    "--model", self.model,
                    *self._reasoning_effort_args(self.model),
                    "--full-auto",
                    "--skip-git-repo-check",
                    "--output-last-message", str(output_file),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            raw_file = output_file.read_text(errors="replace") if output_file.exists() else ""
            low = (((probe.stdout or "") + "\n" + (probe.stderr or "") + "\n" + raw_file).lower())
            if any(marker in low for marker in auth_fail_markers) or ("login" in low and "required" in low):
                return _cache_store(False, "codex fallback probe: authentication required")
            if probe.returncode != 0:
                short = ((probe.stderr or probe.stdout or raw_file)[:200] or f"exit={probe.returncode}")
                return _cache_store(False, f"codex fallback probe failed: {short}")
            if not raw_file.strip():
                return _cache_store(False, "codex fallback probe produced empty output")
            return _cache_store(True)
        except subprocess.TimeoutExpired:
            return _cache_store(False, "codex fallback probe timeout (30s)")
        except Exception as exc:
            return _cache_store(False, f"codex fallback probe error: {exc}")
        finally:
            output_file.unlink(missing_ok=True)
