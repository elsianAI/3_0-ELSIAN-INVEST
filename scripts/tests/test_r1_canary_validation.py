#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import scripts.r1_canary_validation as r1


class R1CanaryValidationTests(unittest.TestCase):
    def _build_case(self, root: Path, annual_partials: int) -> Path:
        case_dir = root / "casos" / "TEP" / "2026-02-25"
        case_dir.mkdir(parents=True, exist_ok=True)
        for i in range(annual_partials):
            (case_dir / f"_tmp_tp_filing_{i:03d}.json").write_text(
                json.dumps({"filing_type": "ANNUAL_REPORT"}),
                encoding="utf-8",
            )
        return case_dir

    @staticmethod
    def _minimal_tp_data(periods: int) -> dict:
        annual = [
            {"periodo": f"FY{2019 + i}", "ingresos_usd": 1_000_000_000 + i}
            for i in range(periods)
        ]
        return {
            "historico_anual": annual,
            "historico_trimestral": [{"periodo": "Q1-2025", "ingresos_usd": 100}],
            "balance_sheet_ultimo": {"activos_totales_usd": 1, "pasivos_totales_usd": 1, "patrimonio_usd": 1},
            "data_quality": {"confidence_score": 90},
        }

    def test_dynamic_tep_threshold_accepts_6_periods_with_4_annual_filings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = self._build_case(root, annual_partials=4)
            validator = r1.R1CanaryValidator(str(root), verbose=False)
            tp_data = self._minimal_tp_data(periods=6)
            tp_calc = {"metricas_derivadas": {"dummy": 1}}
            result = validator.validate_structural_completeness("TEP", tp_data, tp_calc, case_dir)
            self.assertEqual(result.status, r1.CheckStatus.PASS)

    def test_dynamic_tep_threshold_rejects_5_periods_with_4_annual_filings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = self._build_case(root, annual_partials=4)
            validator = r1.R1CanaryValidator(str(root), verbose=False)
            tp_data = self._minimal_tp_data(periods=5)
            tp_calc = {"metricas_derivadas": {"dummy": 1}}
            result = validator.validate_structural_completeness("TEP", tp_data, tp_calc, case_dir)
            self.assertEqual(result.status, r1.CheckStatus.FAIL)
            self.assertIn("require >= 6", result.message)


if __name__ == "__main__":
    unittest.main()

