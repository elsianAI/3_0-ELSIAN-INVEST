#!/usr/bin/env python3
"""Unit tests for scripts/regression_check.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.regression_check as rc


def _annual_entry(periodo: str, fecha_fin: str, seed: int) -> dict:
    return {
        "periodo": periodo,
        "fecha_fin": fecha_fin,
        "ingresos_usd": float(seed * 1_000_000),
        "ebit_usd": float(seed * 100_000),
        "net_income_usd": float(seed * 80_000),
        "cfo_usd": float(seed * 60_000),
        "capex_usd": float(-seed * 20_000),
    }


def _make_truthpack(
    annual: list[dict],
    *,
    confidence: float = 90.0,
    completeness: float = 80.0,
    market_cap: float = 1_000_000_000.0,
    precio: float = 10.0,
) -> dict:
    return {
        "ticker": "TST",
        "version_esquema": "TruthPack_v1",
        "historico_anual": annual,
        "historico_trimestral": [{"periodo": "Q4-2025"}, {"periodo": "Q3-2025"}],
        "balance_sheet_ultimo": {
            "activos_totales_usd": 10_000_000_000.0,
            "pasivos_totales_usd": 4_000_000_000.0,
            "patrimonio_usd": 6_000_000_000.0,
            "caja_usd": 500_000_000.0,
            "deuda_total_usd": 1_200_000_000.0,
        },
        "mercado": {
            "market_cap_usd": market_cap,
            "precio": {"valor": precio},
        },
        "data_quality": {
            "overall_status": "PASS",
            "confidence_score": confidence,
            "gates": [{"name": "DATA_COMPLETENESS", "completeness_pct": completeness}],
        },
    }


class RegressionCheckTests(unittest.TestCase):
    def _run_check(self, golden_tp: dict, current_tp: dict) -> tuple[bool, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            golden_dir = root / "golden"
            casos_dir = root / "casos"
            golden_dir.mkdir(parents=True, exist_ok=True)

            ticker = "TST"
            date_str = "2026-01-01"
            case_dir = casos_dir / ticker / date_str
            case_dir.mkdir(parents=True, exist_ok=True)

            golden_snapshot = rc._extract_snapshot(golden_tp)
            (golden_dir / f"golden_{ticker}_{date_str}.json").write_text(
                json.dumps(golden_snapshot, ensure_ascii=False),
                encoding="utf-8",
            )
            (case_dir / "TruthPack_v1_TST.json").write_text(
                json.dumps(current_tp, ensure_ascii=False),
                encoding="utf-8",
            )

            with (
                mock.patch.object(rc, "GOLDEN_DIR", golden_dir),
                mock.patch.object(rc, "CASOS_DIR", casos_dir),
            ):
                return rc.check_case(ticker, date_str)

    def test_annual_order_change_does_not_fail_when_period_keys_match(self) -> None:
        a = _annual_entry("FY2024", "2024-12-31", 24)
        b = _annual_entry("FY2023", "2023-12-31", 23)
        c = _annual_entry("FY2022", "2022-12-31", 22)
        golden_tp = _make_truthpack([a, b, c])
        current_tp = _make_truthpack([c, a, b])

        passed, issues = self._run_check(golden_tp, current_tp)
        self.assertTrue(passed, msg="\n".join(issues))
        self.assertFalse(any("REGRESSION" in i for i in issues))

    def test_annual_value_change_for_same_period_fails(self) -> None:
        a = _annual_entry("FY2024", "2024-12-31", 24)
        b = _annual_entry("FY2023", "2023-12-31", 23)
        c = _annual_entry("FY2022", "2022-12-31", 22)
        golden_tp = _make_truthpack([a, b, c])
        b_changed = dict(b)
        b_changed["ingresos_usd"] = b_changed["ingresos_usd"] + 1_000_000
        current_tp = _make_truthpack([a, b_changed, c])

        passed, issues = self._run_check(golden_tp, current_tp)
        self.assertFalse(passed)
        self.assertTrue(
            any("annual[periodo=FY2023,fecha_fin=2023-12-31].ingresos_usd" in i for i in issues)
        )

    def test_missing_period_is_reported_as_regression(self) -> None:
        a = _annual_entry("FY2024", "2024-12-31", 24)
        b = _annual_entry("FY2023", "2023-12-31", 23)
        c = _annual_entry("FY2022", "2022-12-31", 22)
        golden_tp = _make_truthpack([a, b, c])
        current_tp = _make_truthpack([a, b])

        passed, issues = self._run_check(golden_tp, current_tp)
        self.assertFalse(passed)
        self.assertTrue(any("missing in current snapshot" in i for i in issues))

    def test_historico_anual_count_drop_is_regression(self) -> None:
        a = _annual_entry("FY2024", "2024-12-31", 24)
        b = _annual_entry("FY2023", "2023-12-31", 23)
        c = _annual_entry("FY2022", "2022-12-31", 22)
        golden_tp = _make_truthpack([a, b, c])
        current_tp = _make_truthpack([a, b])

        _, issues = self._run_check(golden_tp, current_tp)
        self.assertTrue(any("REGRESSION historico_anual_count" in i for i in issues))

    def test_confidence_drop_is_regression(self) -> None:
        a = _annual_entry("FY2024", "2024-12-31", 24)
        b = _annual_entry("FY2023", "2023-12-31", 23)
        c = _annual_entry("FY2022", "2022-12-31", 22)
        golden_tp = _make_truthpack([a, b, c], confidence=95.0)
        current_tp = _make_truthpack([a, b, c], confidence=85.0)

        passed, issues = self._run_check(golden_tp, current_tp)
        self.assertFalse(passed)
        self.assertTrue(any("REGRESSION quality.confidence_score" in i for i in issues))

    def test_market_tolerance_works(self) -> None:
        a = _annual_entry("FY2024", "2024-12-31", 24)
        b = _annual_entry("FY2023", "2023-12-31", 23)
        c = _annual_entry("FY2022", "2022-12-31", 22)
        golden_tp = _make_truthpack([a, b, c], market_cap=1_000.0)

        passed_ok, issues_ok = self._run_check(golden_tp, _make_truthpack([a, b, c], market_cap=1_040.0))
        self.assertTrue(passed_ok, msg="\n".join(issues_ok))

        passed_bad, issues_bad = self._run_check(golden_tp, _make_truthpack([a, b, c], market_cap=1_120.0))
        self.assertFalse(passed_bad)
        self.assertTrue(any("REGRESSION market.market_cap_usd" in i for i in issues_bad))


if __name__ == "__main__":
    unittest.main()
