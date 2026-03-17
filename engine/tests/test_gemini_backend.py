import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.backends.gemini import GeminiBackend
from engine.dispatcher import _is_retryable_dispatch_error


def _backend_config(preflight_disable_yolo: bool = True) -> dict:
    return {
        "model_catalog": {
            "gemini-profile": {
                "gemini": {
                    "model_id": "gemini-test",
                    "preflight_disable_yolo": preflight_disable_yolo,
                }
            }
        }
    }


class GeminiBackendTests(unittest.TestCase):
    def test_dispatch_uses_headless_env(self) -> None:
        backend = GeminiBackend("gemini", "gemini-test", _backend_config())
        seen_env = {}

        def _fake_run(*args, **kwargs):
            seen_env.update(kwargs.get("env", {}))
            return subprocess.CompletedProcess(
                args[0],
                0,
                stdout='{"response":"{\\"ok\\": true}","session_id":"abc"}',
                stderr="",
            )

        with patch("engine.backends.gemini.subprocess.run", side_effect=_fake_run):
            result = backend.dispatch("prompt", cwd=Path("."), timeout=5)

        self.assertTrue(result.success)
        self.assertEqual(seen_env.get("CI"), "1")
        self.assertEqual(seen_env.get("NO_COLOR"), "1")
        self.assertEqual(seen_env.get("TERM"), "dumb")

    def test_dispatch_retries_known_runtime_crash(self) -> None:
        backend = GeminiBackend("gemini", "gemini-test", _backend_config())
        crash_stderr = (
            "Warning: Detected unsettled top-level await at /node_modules/yoga-layout/dist/src/index.js"
        )
        responses = [
            subprocess.CompletedProcess(["gemini"], 13, stdout="", stderr=crash_stderr),
            subprocess.CompletedProcess(
                ["gemini"],
                0,
                stdout='{"response":"{\\"ok\\": true}","session_id":"abc"}',
                stderr="",
            ),
        ]

        with patch("engine.backends.gemini.subprocess.run", side_effect=responses) as mocked_run, \
            patch("engine.backends.gemini.time.sleep"):
            result = backend.dispatch("prompt", cwd=Path("."), timeout=5)

        self.assertTrue(result.success)
        self.assertEqual(mocked_run.call_count, 2)
        self.assertEqual(result.output, {"ok": True})

    def test_dispatch_returns_normalized_runtime_crash_error(self) -> None:
        backend = GeminiBackend("gemini", "gemini-test", _backend_config())
        crash_stderr = "Warning: Detected unsettled top-level await at yoga-layout"

        with patch(
            "engine.backends.gemini.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["gemini"], 13, stdout="", stderr=crash_stderr),
                subprocess.CompletedProcess(["gemini"], 13, stdout="", stderr=crash_stderr),
            ],
        ), patch("engine.backends.gemini.time.sleep"):
            result = backend.dispatch("prompt", cwd=Path("."), timeout=5)

        self.assertFalse(result.success)
        self.assertIn("Gemini CLI runtime crash", result.error or "")
        self.assertIn("yoga-layout", result.raw_output)

    def test_dispatcher_marks_runtime_crash_as_retryable(self) -> None:
        self.assertTrue(
            _is_retryable_dispatch_error(
                "Gemini CLI runtime crash",
                "Warning: Detected unsettled top-level await at yoga-layout",
            )
        )


if __name__ == "__main__":
    unittest.main()