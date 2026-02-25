#!/usr/bin/env python3
"""Unit tests for V5.2 recovery/fingerprint/state hardening."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.router import (
    _compute_step_input_fingerprint,
    _recover_previous_artifact_if_valid,
)
from engine.state import init_state, load_state, mark_step_done, read_modify_write


class _FakeConfig:
    def __init__(self, repo_root: Path):
        self._schemas = repo_root / "_schemas"

    def get_path(self, key: str) -> Path:
        if key == "schemas":
            return self._schemas
        raise KeyError(key)


class EnginePipelineRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.case_dir = self.tmp_path / "casos" / "TST" / "2026-02-24"
        init_state(self.case_dir, "TST", "2026-02-24")
        self.config = _FakeConfig(Path(__file__).resolve().parents[2])
        self._write_red_team_inputs()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_json(self, name: str, payload: dict) -> Path:
        path = self.case_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _write_red_team_inputs(self) -> None:
        self._write_json(
            "TruthPack_v1_TST.json",
            {"version_esquema": "TruthPack_v1", "ticker": "TST"},
        )
        self._write_json(
            "AgentReport_v1_BULL_TST.json",
            {"version_esquema": "AgentReport_v1", "agent_role": "BULL"},
        )

    def _set_previous_artifact(
        self,
        *,
        step_name: str = "RED_TEAM",
        include_fingerprint: bool = True,
        artifact_payload: dict | None = None,
        artifact_name: str | None = None,
    ) -> tuple[str, str | None]:
        artifact_name = artifact_name or f"AgentReport_v1_{step_name}_prev.json"
        payload = artifact_payload or {"version_esquema": "AgentReport_v1", "agent_role": step_name}
        self._write_json(artifact_name, payload)
        fp = _compute_step_input_fingerprint(self.case_dir, step_name) if include_fingerprint else None

        def _mod(state: dict) -> None:
            step = state.setdefault("pipeline", {}).setdefault(
                step_name,
                {"estado": "PENDING", "artefacto": None, "artefacto_previo": None},
            )
            step["estado"] = "DONE"
            step["artefacto"] = artifact_name
            step["artefacto_previo"] = None
            step.pop("reused_previous_artifact", None)
            step.pop("reuse_reason", None)
            step.pop("reused_artifact_path", None)
            step.pop("reuse_bootstrap_legacy", None)
            if include_fingerprint and fp:
                step["input_fingerprint"] = fp
            else:
                step.pop("input_fingerprint", None)

        read_modify_write(self.case_dir, _mod)
        return artifact_name, fp

    @mock.patch("engine.error_tracker.resolve_error", return_value=False)
    @mock.patch("engine.router.validate_artifact", return_value=(False, ["invalid schema"]))
    @mock.patch("engine.dispatcher._is_retryable_dispatch_error", return_value=True)
    def test_recovery_requires_schema_valid(self, *_mocks) -> None:
        self._set_previous_artifact(include_fingerprint=True)
        result = _recover_previous_artifact_if_valid(
            self.config, self.case_dir, "RED_TEAM", "timeout", {}
        )
        self.assertIsNone(result)
        step = load_state(self.case_dir)["pipeline"]["RED_TEAM"]
        self.assertNotIn("reused_previous_artifact", step)

    @mock.patch("engine.error_tracker.resolve_error", return_value=False)
    @mock.patch("engine.router.validate_artifact", return_value=(True, []))
    @mock.patch("engine.dispatcher._is_retryable_dispatch_error", return_value=True)
    def test_recovery_persists_fingerprint_after_mark_done(self, *_mocks) -> None:
        artifact_name, _ = self._set_previous_artifact(include_fingerprint=False)
        current_fp = _compute_step_input_fingerprint(self.case_dir, "RED_TEAM")

        result = _recover_previous_artifact_if_valid(
            self.config, self.case_dir, "RED_TEAM", "timeout", {}
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("artifact"), artifact_name)

        step = load_state(self.case_dir)["pipeline"]["RED_TEAM"]
        self.assertEqual(step.get("input_fingerprint"), current_fp)
        self.assertTrue(step.get("reused_previous_artifact"))
        self.assertTrue(step.get("reuse_bootstrap_legacy"))

    @mock.patch("engine.error_tracker.resolve_error", return_value=False)
    @mock.patch("engine.router.validate_artifact", return_value=(True, []))
    @mock.patch("engine.dispatcher._is_retryable_dispatch_error", return_value=True)
    def test_recovery_works_when_state_artifact_pointer_missing(self, *_mocks) -> None:
        artifact_name, fp = self._set_previous_artifact(include_fingerprint=True)

        def _drop_pointer(state: dict) -> None:
            step = state["pipeline"]["RED_TEAM"]
            step["artefacto"] = None
            step["artefacto_previo"] = None
            # keep fingerprint; this is the legacy gap we want to recover from
            step["input_fingerprint"] = fp

        read_modify_write(self.case_dir, _drop_pointer)

        result = _recover_previous_artifact_if_valid(
            self.config, self.case_dir, "RED_TEAM", "timeout", {}
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("artifact"), artifact_name)

        step = load_state(self.case_dir)["pipeline"]["RED_TEAM"]
        self.assertEqual(step.get("artefacto"), artifact_name)
        self.assertTrue(step.get("reused_previous_artifact"))

    @mock.patch("engine.error_tracker.resolve_error", return_value=False)
    @mock.patch("engine.router.validate_artifact", return_value=(True, []))
    @mock.patch("engine.dispatcher._is_retryable_dispatch_error", return_value=True)
    def test_recovery_bootstrap_legacy_once_then_strict(self, *_mocks) -> None:
        self._set_previous_artifact(include_fingerprint=False)
        first = _recover_previous_artifact_if_valid(
            self.config, self.case_dir, "RED_TEAM", "timeout", {}
        )
        self.assertIsNotNone(first)
        self.assertTrue(first.get("success"))

        # Input drift: fingerprint must change and block next reuse.
        self._write_json(
            "TruthPack_v1_TST.json",
            {"version_esquema": "TruthPack_v1", "ticker": "TST", "changed": True},
        )
        second = _recover_previous_artifact_if_valid(
            self.config, self.case_dir, "RED_TEAM", "timeout", {}
        )
        self.assertIsNone(second)

    def test_fingerprint_includes_missing_inputs_and_schema(self) -> None:
        fp_base = _compute_step_input_fingerprint(self.case_dir, "RED_TEAM")

        bull_path = self.case_dir / "AgentReport_v1_BULL_TST.json"
        bull_path.unlink()
        fp_missing = _compute_step_input_fingerprint(self.case_dir, "RED_TEAM")
        self.assertNotEqual(fp_base, fp_missing)

        self._write_json(
            "AgentReport_v1_BULL_TST.json",
            {"version_esquema": "AgentReport_v1", "agent_role": "BULL"},
        )
        with mock.patch("engine.router._infer_schema_for_step", return_value="SchemaA"):
            fp_schema_a = _compute_step_input_fingerprint(self.case_dir, "RED_TEAM")
        with mock.patch("engine.router._infer_schema_for_step", return_value="SchemaB"):
            fp_schema_b = _compute_step_input_fingerprint(self.case_dir, "RED_TEAM")
        self.assertNotEqual(fp_schema_a, fp_schema_b)

    @mock.patch("engine.error_tracker.resolve_error", return_value=True)
    def test_substep_done_does_not_resolve_parent_early(self, resolve_mock) -> None:
        mark_step_done(self.case_dir, "PREFETCH", model="python")
        self.assertEqual(resolve_mock.call_count, 0)

        mark_step_done(self.case_dir, "SOURCES_COMPILER", model="python")
        self.assertEqual(resolve_mock.call_count, 1)
        args = resolve_mock.call_args.args
        self.assertEqual(args[1], "SOURCES")
        self.assertEqual(load_state(self.case_dir)["pipeline"]["SOURCES"]["estado"], "DONE")

    @mock.patch("engine.error_tracker.resolve_error", return_value=False)
    @mock.patch("engine.router.validate_artifact", return_value=(True, []))
    @mock.patch("engine.dispatcher._is_retryable_dispatch_error", return_value=True)
    def test_reuse_scope_only_redteam_arbitro(self, *_mocks) -> None:
        self._set_previous_artifact(
            step_name="BULL",
            include_fingerprint=True,
            artifact_name="AgentReport_v1_BULL_prev.json",
        )
        result = _recover_previous_artifact_if_valid(
            self.config, self.case_dir, "BULL", "timeout", {}
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
