"""Backend Gemini: gemini -p con salida JSON."""

from __future__ import annotations

import subprocess
import json
import sys
import time
from pathlib import Path

from .base import LLMBackend, DispatchResult, _try_recover_json

# Module-level cache for auth pre-flight results
# Format: {(binary_path, model): (timestamp, is_ok, reason_if_failed, warning)}
_AUTH_CACHE: dict[tuple[str, str], tuple[float, bool, str | None, str | None]] = {}
_AUTH_CACHE_TTL_OK = 600
_AUTH_CACHE_TTL_FAIL = 60


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
        step_name: str | None = None,
    ) -> DispatchResult:
        """Dispatch to exactly one model. No fallback to different models."""
        _ = step_name
        return self._dispatch_single_model(
            model_name=self.model,
            prompt=prompt,
            cwd=cwd,
            timeout=timeout,
        )

    def _dispatch_single_model(
        self,
        model_name: str,
        prompt: str,
        cwd: Path | None,
        timeout: int,
    ) -> DispatchResult:
        disable_yolo = self._disable_yolo()
        cmd = [
            self.binary_path,
            "-p",
            prompt,
            "--model",
            model_name,
            "--output-format",
            "json",
        ]
        if not disable_yolo:
            cmd.append("--yolo")

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
            stderr_full = proc.stderr or ""
            stderr_text = stderr_full[:2000]

            if proc.returncode != 0 and not raw.strip():
                # Pass full stderr as raw_output so _is_retryable_dispatch_error
                # can detect quota/rate-limit patterns (e.g. TerminalQuotaError)
                # even when they appear late in the stderr stream.
                return DispatchResult(
                    False, None, stderr_full, model_name, "gemini", duration,
                    f"Non-zero exit code: {proc.returncode}. stderr: {stderr_text}",
                    exit_code=proc.returncode,
                )

            # Try to extract JSON from output (gemini may include preamble text)
            output = _try_recover_json(raw)
            if output is not None:
                # Gemini CLI may wrap the artifact in an envelope
                if (
                    isinstance(output, dict)
                    and "response" in output
                    and ("session_id" in output or "stats" in output)
                ):
                    inner = _try_recover_json(str(output["response"]))
                    if inner is not None and isinstance(inner, dict):
                        output = inner
                return DispatchResult(
                    True, output, raw, model_name, "gemini", duration,
                    exit_code=proc.returncode,
                )

            err_suffix = f" (stderr: {stderr_text})" if stderr_text else ""
            return DispatchResult(
                False, None, raw, model_name, "gemini", duration,
                f"Could not parse JSON from output{err_suffix}",
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return DispatchResult(
                False, None, "", model_name, "gemini", timeout, "Timeout",
                exit_code=124,
            )

    def _disable_yolo(self) -> bool:
        # v2: check model_catalog
        catalog = (self.config or {}).get("model_catalog", {})
        for _profile_name, profile_cfg in catalog.items():
            gemini_cfg = profile_cfg.get("gemini", {})
            if gemini_cfg.get("model_id") == self.model:
                return bool(gemini_cfg.get("preflight_disable_yolo"))
        # v1 compat
        model_cfg = (self.config or {}).get("models", {}).get("gemini", {})
        return bool(model_cfg.get("preflight_disable_yolo"))

    def check_available(self) -> bool:
        """Health-check for the model. No fallback-model degraded mode."""
        cache_key = (self.binary_path, self.model)
        disable_yolo = self._disable_yolo()

        def _cache_store(
            ok: bool,
            reason: str | None = None,
            warning: str | None = None,
        ) -> bool:
            _AUTH_CACHE[cache_key] = (time.time(), ok, reason, warning)
            self.last_health_error = None if ok else reason
            self.last_health_warning = warning if ok else None
            return ok

        # Phase 0: serve cached result
        cached = _AUTH_CACHE.get(cache_key)
        if cached:
            if len(cached) == 4:
                ts, result, reason, warning = cached
            else:
                ts, result, reason = cached
                warning = None
            ttl = _AUTH_CACHE_TTL_OK if result else _AUTH_CACHE_TTL_FAIL
            if time.time() - ts < ttl:
                self.last_health_error = None if result else reason
                self.last_health_warning = warning if result else None
                return result

        self.last_health_error = None
        self.last_health_warning = None

        # Phase 1: binary exists
        try:
            ver = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if ver.returncode != 0:
                return _cache_store(
                    False,
                    f"gemini --version failed (exit={ver.returncode})",
                )
        except Exception as exc:
            return _cache_store(False, f"gemini --version error: {exc}")

        # Phase 2: auth check with actual model
        try:
            preflight_cmd = [
                self.binary_path, "-p", "respond with ok",
                "--model", self.model,
                "--output-format", "json",
            ]
            if not disable_yolo:
                preflight_cmd.append("--yolo")
            auth = subprocess.run(
                preflight_cmd,
                capture_output=True, text=True, timeout=60,
            )
            if auth.returncode != 0:
                stderr_full_pf = auth.stderr or ""
                stderr_snippet = stderr_full_pf[:150]
                # Capacity/rate-limit errors (429) are transient — the model exists
                # but is temporarily overloaded. Treat as available with a warning
                # so that the actual dispatch can handle retries.
                _capacity_indicators = (
                    "429", "rateLimitExceeded", "capacity", "RESOURCE_EXHAUSTED",
                    "MODEL_CAPACITY_EXHAUSTED",
                )
                is_capacity_error = any(ind in stderr_full_pf for ind in _capacity_indicators)
                if is_capacity_error:
                    warn_msg = f"gemini capacity warning (exit={auth.returncode}): model is rate-limited but available"
                    print(
                        f"[gemini] Pre-flight WARNING (model={self.model}): "
                        f"capacity/rate-limit error (429) — treating as available: {stderr_snippet}",
                        file=sys.stderr,
                    )
                    return _cache_store(True, warning=warn_msg)
                fail_reason = f"gemini preflight failed (exit={auth.returncode}): {stderr_snippet}"
                print(
                    f"[gemini] Pre-flight check FAILED (model={self.model}): "
                    f"exit code {auth.returncode}: {stderr_snippet}",
                    file=sys.stderr,
                )
                return _cache_store(False, fail_reason)
            stdout = (auth.stdout or "").strip()
            if not stdout:
                fail_reason = "gemini preflight: empty stdout"
                print(
                    f"[gemini] Pre-flight check FAILED (model={self.model}): empty stdout",
                    file=sys.stderr,
                )
                return _cache_store(False, fail_reason)
            try:
                envelope = json.loads(stdout)
                if isinstance(envelope, dict) and envelope.get("is_error"):
                    msg = str(envelope.get("result", "unknown error"))[:150]
                    print(
                        f"[gemini] Pre-flight check FAILED (model={self.model}): {msg}",
                        file=sys.stderr,
                    )
                    return _cache_store(False, f"gemini preflight error: {msg}")
            except json.JSONDecodeError:
                fail_reason = f"gemini preflight non-JSON: {stdout[:80]}"
                print(
                    f"[gemini] Pre-flight check FAILED (model={self.model}): "
                    f"non-JSON response: {stdout[:150]}",
                    file=sys.stderr,
                )
                return _cache_store(False, fail_reason)
            return _cache_store(True)
        except subprocess.TimeoutExpired:
            print(f"[gemini] Pre-flight check timed out (model={self.model})", file=sys.stderr)
            return _cache_store(False, "gemini preflight timeout (60s)")
        except Exception as exc:
            return _cache_store(False, f"gemini preflight error: {exc}")
