#!/usr/bin/env python3
"""Unit tests for scripts/phase2_ab_truthpack.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.phase2_ab_truthpack import (
    absolutize_paths,
    collect_snapshot_metrics,
    compute_proxy_cost,
    evaluate_go_no_go,
    extract_adjusted_completeness,
    extract_gate_completeness,
)


class Phase2ABTruthPackTests(unittest.TestCase):
    def test_extract_adjusted_and_gate_completeness(self) -> None:
        tp = {
            "data_quality": {
                "completitud_ajustada_por_tipo": {"pct": 72.5},
                "gates": [{"name": "DATA_COMPLETENESS", "completeness_pct": 61.0}],
            }
        }
        self.assertEqual(extract_adjusted_completeness(tp), 72.5)
        self.assertEqual(extract_gate_completeness(tp), 61.0)

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
        total, breakdown = compute_proxy_cost(provenance)
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
                collect_snapshot_metrics(d)

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
                collect_snapshot_metrics(d)

    def test_evaluate_go_no_go_thresholds(self) -> None:
        case_results = {
            "A": {"status": "ok", "delta_pp_adjusted": 12.0, "cost_ratio": 1.2, "latency_ratio": 2.0},
            "B": {"status": "ok", "delta_pp_adjusted": 11.0, "cost_ratio": 1.3, "latency_ratio": 2.4},
        }
        verdict_ok = evaluate_go_no_go(case_results, canary_ok=True, regression_ok=True)
        self.assertTrue(verdict_ok["go"])

        verdict_fail = evaluate_go_no_go(case_results, canary_ok=False, regression_ok=True)
        self.assertFalse(verdict_fail["go"])
        self.assertTrue(any("canary" in r for r in verdict_fail["reasons"]))

    def test_absolutize_paths_resolves_relative_from_base_config_dir(self) -> None:
        cfg = {"paths": {"casos": "casos", "schemas": "_schemas"}}
        out = absolutize_paths(cfg, base_config_dir=Path("/tmp/workspace"))
        self.assertTrue(Path(out["paths"]["casos"]).is_absolute())
        self.assertTrue(Path(out["paths"]["schemas"]).is_absolute())
        self.assertEqual(Path(out["paths"]["casos"]).name, "casos")
        self.assertEqual(Path(out["paths"]["schemas"]).name, "_schemas")

    def test_absolutize_paths_keeps_legacy_paths_layout_supported(self) -> None:
        cfg = {"_paths": {"casos": "casos"}}
        out = absolutize_paths(cfg, base_config_dir=Path("/tmp/workspace"))
        self.assertIn("_paths", out)
        self.assertTrue(Path(out["_paths"]["casos"]).is_absolute())


if __name__ == "__main__":
    unittest.main()
