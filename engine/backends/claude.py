"""Backend Claude Code: claude -p con --output-format json."""

from __future__ import annotations

import subprocess
import json
import sys
import time
from pathlib import Path

from .base import LLMBackend, DispatchResult

# Module-level cache for auth pre-flight results (shared across instances)
# Format: {(binary_path, model): (timestamp, is_ok, reason_if_failed)}
_AUTH_CACHE: dict[tuple[str, str], tuple[float, bool, str | None]] = {}
_AUTH_CACHE_TTL_OK = 600    # 10 min for successes
_AUTH_CACHE_TTL_FAIL = 60   # 60s for failures

_TOOLS_ENABLED_STEPS = {
    "MONITOR",
    "SCANNER",
    "SCOUT_PREFILTRO",
    "SCOUT_Q",
    "SCOUT_E",
    "OUTCOME",
}


def _extract_truncation_meta(envelope: dict) -> dict:
    """Best-effort truncation diagnostics from Claude envelope."""
    meta: dict = {
        "num_turns": None,
        "output_tokens": None,
        "max_output_tokens": None,
        "truncation_detected": False,
    }
    if not isinstance(envelope, dict):
        return meta

    turns = envelope.get("num_turns")
    if isinstance(turns, (int, float)):
        meta["num_turns"] = int(turns)

    model_usage = envelope.get("modelUsage")
    if isinstance(model_usage, dict):
        for usage in model_usage.values():
            if not isinstance(usage, dict):
                continue
            output_tokens = usage.get("outputTokens")
            max_output_tokens = usage.get("maxOutputTokens")
            if isinstance(output_tokens, (int, float)):
                meta["output_tokens"] = int(output_tokens)
            if isinstance(max_output_tokens, (int, float)):
                meta["max_output_tokens"] = int(max_output_tokens)
            if meta["output_tokens"] is not None or meta["max_output_tokens"] is not None:
                break

    if meta["output_tokens"] is not None and meta["max_output_tokens"] is not None:
        meta["truncation_detected"] = meta["output_tokens"] >= meta["max_output_tokens"]
    return meta


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
        step_name: str | None = None,
    ) -> DispatchResult:
        """Dispatch to exactly one model. No fallback to different models."""
        return self._dispatch_single_model(
            model_name=self.model,
            prompt=prompt,
            output_schema=output_schema,
            cwd=cwd,
            timeout=timeout,
            step_name=step_name,
        )

    def _dispatch_single_model(
        self,
        model_name: str,
        prompt: str,
        output_schema: Path | None,
        cwd: Path | None,
        timeout: int,
        step_name: str | None,
    ) -> DispatchResult:
        """Ejecuta claude -p en modo no-interactivo para un modelo concreto."""
        step_key = (step_name or "").strip().upper()
        tools_enabled = step_key in _TOOLS_ENABLED_STEPS

        cmd = [
            self.binary_path, "-p", prompt,
            "--model", model_name,
            "--output-format", "json",
            "--max-turns", "10" if tools_enabled else "1",
            "--no-session-persistence",
        ]
        if not tools_enabled:
            cmd.extend(["--tools", ""])  # Disable all tool access
        cmd.extend([
            "--disallowedTools", "mcp__*",  # Block MCP servers from .mcp.json
            "--strict-mcp-config",  # Ignore all MCP configs (no --mcp-config → zero servers)
        ])

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

            if proc.returncode != 0 and not raw.strip():
                # Pass full stderr as raw_output so _is_retryable_dispatch_error
                # can detect quota/rate-limit/network patterns.
                return DispatchResult(
                    False, None, stderr_full, model_name, "claude", duration,
                    f"Non-zero exit code: {proc.returncode}. stderr: {stderr_full[:2000]}",
                    exit_code=proc.returncode,
                )

            # Claude --output-format json wraps result in a JSON envelope
            try:
                envelope = json.loads(raw)
                trunc_meta = _extract_truncation_meta(envelope)
                # Check for error envelope FIRST
                if isinstance(envelope, dict) and envelope.get("is_error"):
                    error_msg = envelope.get("result", "Unknown Claude CLI error")
                    if isinstance(error_msg, dict):
                        error_msg = json.dumps(error_msg)[:500]
                    return DispatchResult(
                        False, None, raw, model_name, "claude", duration,
                        f"Claude CLI error: {str(error_msg)[:500]}",
                        exit_code=proc.returncode,
                        failure_ctx={
                            **trunc_meta,
                            "parse_stage": "envelope_error",
                        },
                    )
                # Claude Code JSON output has a "result" field with the actual content
                if isinstance(envelope, dict) and "result" in envelope:
                    result_text = envelope["result"]
                    if isinstance(result_text, str):
                        try:
                            output = json.loads(result_text)
                            return DispatchResult(True, output, raw, model_name, "claude", duration, exit_code=proc.returncode)
                        except json.JSONDecodeError:
                            import re
                            md_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", result_text, re.DOTALL)
                            if md_match:
                                try:
                                    output = json.loads(md_match.group(1))
                                    return DispatchResult(True, output, raw, model_name, "claude", duration, exit_code=proc.returncode)
                                except json.JSONDecodeError:
                                    pass
                            snippet = result_text.strip().replace("\n", " ")[:240]
                            return DispatchResult(
                                False, None, result_text, model_name, "claude", duration,
                                f"Claude result is not JSON artifact: {snippet or '<empty>'}",
                                exit_code=proc.returncode,
                                failure_ctx={
                                    **trunc_meta,
                                    "parse_stage": "result_text_json_parse",
                                },
                            )
                    elif isinstance(result_text, dict):
                        return DispatchResult(True, result_text, raw, model_name, "claude", duration, exit_code=proc.returncode)
                # Accept direct artifact JSON only if it looks like a payload
                if isinstance(envelope, dict) and (
                    "version_esquema" in envelope
                    or "resumen_ejecutivo" in envelope
                    or "claims" in envelope
                    or "decision_packet" in envelope
                ):
                    return DispatchResult(True, envelope, raw, model_name, "claude", duration, exit_code=proc.returncode)
                return DispatchResult(
                    False, None, raw, model_name, "claude", duration,
                    "Claude JSON envelope did not contain artifact payload",
                    exit_code=proc.returncode,
                    failure_ctx={
                        **trunc_meta,
                        "parse_stage": "envelope_payload_missing",
                    },
                )
            except json.JSONDecodeError as e:
                return DispatchResult(
                    False, None, raw, model_name, "claude", duration,
                    f"JSON parse error: {e}",
                    exit_code=proc.returncode,
                    failure_ctx={
                        "num_turns": None,
                        "output_tokens": None,
                        "max_output_tokens": None,
                        "truncation_detected": False,
                        "parse_stage": "envelope_json_parse",
                    },
                )

        except subprocess.TimeoutExpired:
            return DispatchResult(
                False, None, "", model_name, "claude", timeout, "Timeout",
                exit_code=124,
            )

    def check_available(self) -> bool:
        """Check if Claude CLI is available AND authenticated.

        Three-phase check (all FREE, zero tokens):
          1. Quick: binary exists (--version)
          2. Auth: `claude auth status` — free, no inference
          3. Cache: result cached (OK=10min, FAIL=60s)
        """
        cache_key = (self.binary_path, self.model)

        def _cache_store(ok: bool, reason: str | None = None) -> bool:
            _AUTH_CACHE[cache_key] = (time.time(), ok, reason)
            self.last_health_error = None if ok else reason
            self.last_health_warning = None
            return ok

        # Phase 0: serve cached result
        cached = _AUTH_CACHE.get(cache_key)
        if cached:
            ts, result, reason = cached
            ttl = _AUTH_CACHE_TTL_OK if result else _AUTH_CACHE_TTL_FAIL
            if time.time() - ts < ttl:
                self.last_health_error = None if result else reason
                self.last_health_warning = None
                return result

        # Phase 1: binary exists
        try:
            ver = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if ver.returncode != 0:
                return _cache_store(
                    False,
                    f"claude --version failed (exit={ver.returncode})",
                )
        except Exception as exc:
            return _cache_store(False, f"claude --version error: {exc}")

        # Phase 2: auth check via `claude auth status`
        try:
            auth = subprocess.run(
                [self.binary_path, "auth", "status"],
                capture_output=True, text=True, timeout=15,
            )
            status_out = ((auth.stdout or "") + "\n" + (auth.stderr or "")).strip()
            low = status_out.lower()
            if auth.returncode != 0:
                legacy_markers = (
                    "unknown command",
                    "unrecognized",
                    "invalid subcommand",
                    "invalid choice",
                    "usage:",
                )
                if not any(marker in low for marker in legacy_markers):
                    short = status_out[:200] if status_out else f"exit={auth.returncode}"
                    return _cache_store(False, f"claude auth status failed: {short}")
                print(
                    f"[claude] auth status unsupported; using fallback probe (model={self.model})",
                    file=sys.stderr,
                )
            else:
                if "not logged in" in low or "no active" in low:
                    return _cache_store(False, "claude auth status: not authenticated")
                return _cache_store(True)
        except FileNotFoundError:
            return _cache_store(False, "claude binary not found for auth status check")
        except subprocess.TimeoutExpired:
            return _cache_store(False, "claude auth status timeout (15s)")
        except Exception as exc:
            print(
                f"[claude] WARNING: auth status check errored, using fallback probe: {exc}",
                file=sys.stderr,
            )

        # Phase 2b: Fallback — lightweight paid prompt (legacy)
        try:
            auth = subprocess.run(
                [self.binary_path, "-p", "respond with ok",
                 "--model", self.model,
                 "--output-format", "json", "--max-turns", "1",
                 "--no-session-persistence",
                 "--tools", "",
                 "--disallowedTools", "mcp__*",
                 "--strict-mcp-config"],
                capture_output=True, text=True, timeout=30,
            )
            if auth.returncode != 0:
                print(f"[claude] Pre-flight check FAILED (model={self.model}): "
                      f"exit code {auth.returncode}",
                      file=sys.stderr)
                return _cache_store(False, f"claude fallback probe failed (exit={auth.returncode})")
            stdout = (auth.stdout or "").strip()
            if not stdout:
                print(f"[claude] Pre-flight check FAILED (model={self.model}): "
                      f"empty stdout", file=sys.stderr)
                return _cache_store(False, "claude fallback probe: empty stdout")
            try:
                envelope = json.loads(stdout)
                if isinstance(envelope, dict) and envelope.get("is_error"):
                    msg = str(envelope.get("result", "unknown error"))[:150]
                    print(f"[claude] Pre-flight check FAILED (model={self.model}): {msg}",
                          file=sys.stderr)
                    return _cache_store(False, f"claude fallback probe error: {msg}")
            except json.JSONDecodeError:
                print(f"[claude] Pre-flight check FAILED (model={self.model}): "
                      f"non-JSON response: {stdout[:150]}", file=sys.stderr)
                return _cache_store(False, f"claude fallback probe non-JSON: {stdout[:80]}")
            return _cache_store(True)
        except subprocess.TimeoutExpired:
            print(f"[claude] Pre-flight check timed out (model={self.model})",
                  file=sys.stderr)
            return _cache_store(False, "claude fallback probe timeout (30s)")
        except Exception as exc:
            return _cache_store(False, f"claude fallback probe error: {exc}")
