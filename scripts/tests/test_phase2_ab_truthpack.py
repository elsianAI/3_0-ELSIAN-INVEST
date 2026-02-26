#!/usr/bin/env python3
"""Unit tests for scripts/phase2_ab_truthpack.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.phase2_ab_truthpack as phase2_ab


class Phase2ABTruthPackTests(unittest.TestCase):
    def test_make_runtime_config_sets_benchmark_non_fail_fast(self) -> None:
        cfg = {"execution": {"fail_fast": True}, "git": {"enabled": True}}
        out = phase2_ab.make_runtime_config(cfg, chunked_enabled=True)
        self.assertTrue(out["execution"]["tp_extractor_chunked_enabled"])
        self.assertFalse(out["execution"]["fail_fast"])
        self.assertFalse(out["git"]["enabled"])

    def test_extract_adjusted_and_gate_completeness(self) -> None:
        tp = {
            "data_quality": {
                "completitud_ajustada_por_tipo": {"pct": 72.5},
                "gates": [{"name": "DATA_COMPLETENESS", "completeness_pct": 61.0}],
            }
        }
        self.assertEqual(phase2_ab.extract_adjusted_completeness(tp), 72.5)
        self.assertEqual(phase2_ab.extract_gate_completeness(tp), 61.0)

    def test_compute_proxy_cost_methods_and_arbitrations(self) -> None:
        provenance = {
            "records": [
                {"dispatch_meta": {"method": "llm_single"}},
                {"dispatch_meta": {"method": "llm_chunked_single", "chunk_successful": 4}},
                {"dispatch_meta": {"method": "llm_chunked_fusion", "chunk_successful": 3}},
                {
                    "dispatch_meta": {
                        "method": "llm_chunked_best_chunk_fallback",
                        "chunk_successful": 2,
                        "cross_layer_reconciliation": {"arbitrations": 2},
                    }
                },
            ]
        }
        total, breakdown = phase2_ab.compute_proxy_cost(provenance)
        expected = 1.0 + (4 * 0.2) + (3 * 0.2 + 1.0) + (2 * 0.2 + 1.0) + (2 * 2.0)
        self.assertAlmostEqual(total, expected, places=6)
        self.assertGreater(breakdown["chunk_calls_cost"], 0.0)
        self.assertGreater(breakdown["fusion_calls_cost"], 0.0)
        self.assertGreater(breakdown["reconciliation_calls_cost"], 0.0)

    def test_collect_snapshot_metrics_raises_when_adjusted_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "TruthPack_v1_TST.json").write_text(
                json.dumps({"data_quality": {"gates": []}}),
                encoding="utf-8",
            )
            (d / "_extraction_provenance.json").write_text(
                json.dumps({"records": [{"dispatch_meta": {"method": "llm_single"}}]}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                phase2_ab.collect_snapshot_metrics(d)

    def test_collect_snapshot_metrics_raises_when_provenance_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "TruthPack_v1_TST.json").write_text(
                json.dumps(
                    {
                        "data_quality": {
                            "completitud_ajustada_por_tipo": {"pct": 70.0},
                            "gates": [{"name": "DATA_COMPLETENESS", "completeness_pct": 60.0}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(FileNotFoundError):
                phase2_ab.collect_snapshot_metrics(d)

    def test_evaluate_go_no_go_thresholds(self) -> None:
        case_results = {
            "A": {"status": "ok", "delta_pp_adjusted": 12.0, "cost_ratio": 1.2, "latency_ratio": 2.0},
            "B": {"status": "ok", "delta_pp_adjusted": 11.0, "cost_ratio": 1.3, "latency_ratio": 2.4},
        }
        verdict_ok = phase2_ab.evaluate_go_no_go(case_results, canary_ok=True, regression_ok=True)
        self.assertTrue(verdict_ok["go"])

        verdict_fail = phase2_ab.evaluate_go_no_go(case_results, canary_ok=False, regression_ok=True)
        self.assertFalse(verdict_fail["go"])
        self.assertTrue(any("canary" in r for r in verdict_fail["reasons"]))

    def test_absolutize_paths_resolves_relative_from_base_config_dir(self) -> None:
        cfg = {"paths": {"casos": "casos", "schemas": "_schemas"}}
        out = phase2_ab.absolutize_paths(cfg, base_config_dir=Path("/tmp/workspace"))
        self.assertTrue(Path(out["paths"]["casos"]).is_absolute())
        self.assertTrue(Path(out["paths"]["schemas"]).is_absolute())
        self.assertEqual(Path(out["paths"]["casos"]).name, "casos")
        self.assertEqual(Path(out["paths"]["schemas"]).name, "_schemas")

    def test_absolutize_paths_keeps_legacy_paths_layout_supported(self) -> None:
        cfg = {"_paths": {"casos": "casos"}}
        out = phase2_ab.absolutize_paths(cfg, base_config_dir=Path("/tmp/workspace"))
        self.assertIn("_paths", out)
        self.assertTrue(Path(out["_paths"]["casos"]).is_absolute())

    def test_runtime_config_paths_are_in_workspace_with_hidden_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with mock.patch.object(phase2_ab, "WORKSPACE", workspace):
                off_path, on_path = phase2_ab.runtime_config_paths("abc123")
            self.assertEqual(off_path.parent, workspace)
            self.assertEqual(on_path.parent, workspace)
            self.assertEqual(off_path.name, ".engine_config_ab_off_abc123.json")
            self.assertEqual(on_path.name, ".engine_config_ab_on_abc123.json")

    def test_assert_truthpack_done_passes_when_group_and_substeps_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            (case_dir / "_estado.json").write_text(
                json.dumps(
                    {
                        "pipeline": {"TRUTH_PACK": {"estado": "DONE"}},
                        "sub_steps": {
                            "TP_EXTRACTOR_FILING": {"status": "DONE"},
                            "TP_EXTRACTOR_MERGER": {"status": "DONE"},
                            "TP_CALCULATOR": {"status": "DONE"},
                            "TP_VALIDATOR": {"status": "DONE"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            phase2_ab.assert_truthpack_done(case_dir)

    def test_assert_truthpack_done_fails_when_truthpack_not_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            (case_dir / "_estado.json").write_text(
                json.dumps(
                    {
                        "pipeline": {"TRUTH_PACK": {"estado": "FAILED"}},
                        "sub_steps": {
                            "TP_EXTRACTOR_FILING": {"status": "DONE"},
                            "TP_EXTRACTOR_MERGER": {"status": "DONE"},
                            "TP_CALCULATOR": {"status": "DONE"},
                            "TP_VALIDATOR": {"status": "DONE"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                phase2_ab.assert_truthpack_done(case_dir)

    def test_assert_truthpack_done_fails_when_any_substep_not_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            (case_dir / "_estado.json").write_text(
                json.dumps(
                    {
                        "pipeline": {"TRUTH_PACK": {"estado": "DONE"}},
                        "sub_steps": {
                            "TP_EXTRACTOR_FILING": {"status": "DONE"},
                            "TP_EXTRACTOR_MERGER": {"status": "FAILED"},
                            "TP_CALCULATOR": {"status": "DONE"},
                            "TP_VALIDATOR": {"status": "DONE"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                phase2_ab.assert_truthpack_done(case_dir)

    def test_assert_truthpack_done_allows_tp_validator_failed_on_data_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp)
            (case_dir / "_estado.json").write_text(
                json.dumps(
                    {
                        "pipeline": {"TRUTH_PACK": {"estado": "DONE"}},
                        "sub_steps": {
                            "TP_EXTRACTOR_FILING": {"status": "DONE"},
                            "TP_EXTRACTOR_MERGER": {"status": "DONE"},
                            "TP_CALCULATOR": {"status": "DONE"},
                            "TP_VALIDATOR": {
                                "status": "FAILED",
                                "error": "TruthPack data_quality: FAIL",
                                "failure_meta": {"last_error": "TruthPack data_quality: FAIL"},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "TruthPack_v1_TEP.json").write_text(
                json.dumps({"data_quality": {"overall_status": "FAIL"}}),
                encoding="utf-8",
            )
            phase2_ab.assert_truthpack_done(case_dir, allow_validator_failed=True)

    def test_main_marks_case_error_when_rc_zero_but_truthpack_state_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            workspace.mkdir(parents=True, exist_ok=True)
            casos_dir = workspace / "casos"
            case_dir = casos_dir / "TEP" / "2026-02-25"
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "_estado.json").write_text(
                json.dumps(
                    {
                        "pipeline": {"TRUTH_PACK": {"estado": "FAILED"}},
                        "sub_steps": {
                            "TP_EXTRACTOR_FILING": {"status": "DONE"},
                            "TP_EXTRACTOR_MERGER": {"status": "DONE"},
                            "TP_CALCULATOR": {"status": "DONE"},
                            "TP_VALIDATOR": {"status": "DONE"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            base_config = workspace / "engine_config.json"
            base_config.write_text(json.dumps({"paths": {"casos": str(casos_dir)}}), encoding="utf-8")
            output_dir = workspace / "out"

            fake_run = phase2_ab.RunResult(
                ok=True,
                duration_s=1.0,
                stdout="ok",
                stderr="",
                return_code=0,
            )

            with (
                mock.patch.object(phase2_ab, "WORKSPACE", workspace),
                mock.patch.object(phase2_ab, "CASOS_DIR", casos_dir),
                mock.patch.object(phase2_ab, "run_rehacer", return_value=fake_run),
                mock.patch.object(
                    phase2_ab,
                    "run_aux_check",
                    return_value=True,
                ),
                mock.patch.object(
                    phase2_ab,
                    "cleanup_tmp_partials",
                    return_value=0,
                ),
                mock.patch.object(
                    phase2_ab,
                    "snapshot_case",
                    return_value=None,
                ),
                mock.patch.object(sys, "argv", [
                    "phase2_ab_truthpack.py",
                    "--cases",
                    "TEP:2026-02-25",
                    "--base-config",
                    str(base_config),
                    "--output-dir",
                    str(output_dir),
                    "--skip-canary",
                    "--skip-regression",
                ]),
            ):
                rc = phase2_ab.main()

            self.assertEqual(rc, 1)
            summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            case = summary["cases"]["TEP:2026-02-25"]
            self.assertEqual(case["status"], "error")
            self.assertIn("off_truthpack_not_done", case["error"])


if __name__ == "__main__":
    unittest.main()
