#!/usr/bin/env python3
"""Tests for rehacer group reset behavior (V6.2 A/B precondition)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine.engine import _cmd_rehacer
from engine.state import init_state, load_state, read_modify_write, SUB_STEPS


class _FakeConfig:
    def __init__(self, root: Path):
        self.workspace = root
        self._paths = {"casos": root / "casos"}
        self._paths["casos"].mkdir(parents=True, exist_ok=True)
        self.raw = {"git": {"enabled": False}}

    def get_path(self, key: str) -> Path:
        return self._paths[key]


class RehacerGroupResetTests(unittest.TestCase):
    def test_rehacer_truthpack_resets_all_substeps_even_when_parent_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _FakeConfig(root)
            ticker = "TST"
            date_str = "2026-02-25"
            case_dir = config.get_path("casos") / ticker / date_str
            init_state(case_dir, ticker, date_str)

            def _seed_done_state(state: dict) -> None:
                state["pipeline"]["TRUTH_PACK"] = {
                    "estado": "DONE",
                    "artefacto": "TruthPack_v1_TST.json",
                    "artefacto_previo": None,
                }
                for sub in SUB_STEPS["TRUTH_PACK"]:
                    state["sub_steps"][sub] = {"status": "DONE"}

            read_modify_write(case_dir, _seed_done_state)

            args = SimpleNamespace(
                ticker=ticker,
                step_name="TRUTH_PACK",
                date=date_str,
                exchange="",
                country="",
                web_ir="",
            )

            with mock.patch("engine.engine.execute_step", return_value={"success": True, "model": "python"}) as mocked_exec:
                _cmd_rehacer(config, args)

            mocked_exec.assert_called_once()
            state = load_state(case_dir)
            self.assertEqual(state["pipeline"]["TRUTH_PACK"]["estado"], "PENDING")
            for sub in SUB_STEPS["TRUTH_PACK"]:
                self.assertEqual(
                    state["sub_steps"][sub]["status"],
                    "PENDING",
                    msg=f"{sub} should be reset to PENDING",
                )


if __name__ == "__main__":
    unittest.main()
