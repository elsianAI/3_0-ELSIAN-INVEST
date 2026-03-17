#!/usr/bin/env python3
"""Regression coverage for the ZD repair bundle integration."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from engine.truthpack_import import convert_legacy_truthpack


class ZDRepairRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.case_dir = cls.repo_root / "casos" / "ZD" / "2026-03-16"
        cls.input_path = cls.case_dir / "truth_pack.json"
        cls.payload = json.loads(cls.input_path.read_text(encoding="utf-8"))

    def test_zd_truthpack_conversion_applies_repair_bundle(self) -> None:
        converted = convert_legacy_truthpack(
            self.payload,
            ticker="ZD",
            date_str="2026-03-16",
            source_path=self.input_path,
        )

        self.assertEqual(converted["settlement_receivables_net_usd"], 313_413_000)
        self.assertEqual(converted["trade_receivables_net_usd"], 346_848_000)
        self.assertEqual(converted["shares_outstanding_end"], 38_376_859)
        self.assertEqual(converted["weighted_avg_diluted"], 41_098_514)
        self.assertEqual(converted["pretax_income_usd"], 80_747_000)
        self.assertEqual(converted["ebit_to_pretax_unexplained_usd"], 0)
        self.assertEqual(converted["fcf_adjusted_ex_tds_wc_fy2025_usd"], 232_270_000)
        self.assertEqual(
            converted["metricas_derivadas"]["q4_2025_tds_wc_impact_implied_usd"],
            103_200_000,
        )

    def test_zd_receivables_guardrail_uses_trade_dso_for_collection(self) -> None:
        converted = convert_legacy_truthpack(
            self.payload,
            ticker="ZD",
            date_str="2026-03-16",
            source_path=self.input_path,
        )

        guardrail = converted["receivables_guardrail"]
        self.assertGreater(guardrail["settlement_mix_ratio"], 0.25)
        self.assertEqual(guardrail["dso_collection_basis"], "dso_trade")
        self.assertEqual(guardrail["dso_working_capital_basis"], "dso_total")
        self.assertEqual(guardrail["working_capital_signal"], "settlement_float_mix")
        self.assertEqual(converted["metricas_derivadas"]["dso_total_fy2025_dias"], 167.8)
        self.assertEqual(converted["metricas_derivadas"]["dso_trade_fy2025_dias"], 87.2)

    def test_prompt_patches_are_present(self) -> None:
        forensic_prompt = (
            self.repo_root
            / "_instrucciones"
            / "activas"
            / "instrucciones_forensic_detection_V1.md"
        ).read_text(encoding="utf-8")
        implied_prompt = (
            self.repo_root
            / "_instrucciones"
            / "activas"
            / "instrucciones_implied_V4.md"
        ).read_text(encoding="utf-8")
        arbitro_prompt = (
            self.repo_root
            / "_instrucciones"
            / "activas"
            / "instrucciones_arbitro_V6.md"
        ).read_text(encoding="utf-8")

        self.assertIn("DSO_total y DSO_trade", forensic_prompt)
        self.assertIn("5% de EBIT y $10M", forensic_prompt)
        self.assertIn("FCF0_ajustado_ex_float", implied_prompt)
        self.assertIn("EV/FCF ajustado", implied_prompt)
        self.assertIn("DSO_total alto no es bloqueador automático", arbitro_prompt)
        self.assertIn("la salida base debe ser WATCHLIST", arbitro_prompt)


if __name__ == "__main__":
    unittest.main()
