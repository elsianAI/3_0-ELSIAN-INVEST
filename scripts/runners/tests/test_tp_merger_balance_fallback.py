import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.tp_extractor_merger import (
    _merge_balance_sheet,
    _impute_balance_identity,
    _impute_deuda_total,
    _warn_lease_only_debt_missing,
)


class TpMergerBalanceFallbackTests(unittest.TestCase):
    def test_fallback_critical_allowed_same_period(self):
        extractions = [
            {
                "filing_type": "ANNUAL_REPORT",
                "balance_sheet_ultimo": {
                    "periodo": "FY2024",
                    "fecha_fin": "2024-12-31",
                    "activos_totales_usd": 120.0,
                    "pasivos_totales_usd": None,
                },
            },
            {
                "filing_type": "REGULATORY_FILING",
                "balance_sheet_ultimo": {
                    "periodo": "FY2024",
                    "fecha_fin": "2024-12-31",
                    "pasivos_totales_usd": 70.0,
                },
            },
        ]
        warnings = []
        merged = _merge_balance_sheet(extractions, warnings)
        self.assertEqual(merged.get("pasivos_totales_usd"), 70.0)
        self.assertIn("pasivos_totales_usd", merged.get("_field_sources", {}))
        self.assertIn(
            "fallback_critical",
            merged["_field_sources"]["pasivos_totales_usd"],
        )
        self.assertFalse(any("cross_period_blocked" in w for w in warnings))

    def test_fallback_critical_blocked_cross_period(self):
        extractions = [
            {
                "filing_type": "ANNUAL_REPORT",
                "balance_sheet_ultimo": {
                    "periodo": "FY2024",
                    "fecha_fin": "2024-12-31",
                    "activos_totales_usd": 120.0,
                    "pasivos_totales_usd": None,
                },
            },
            {
                "filing_type": "REGULATORY_FILING",
                "balance_sheet_ultimo": {
                    "periodo": "FY2023",
                    "fecha_fin": "2023-12-31",
                    "pasivos_totales_usd": 70.0,
                },
            },
        ]
        warnings = []
        merged = _merge_balance_sheet(extractions, warnings)
        self.assertIsNone(merged.get("pasivos_totales_usd"))
        self.assertNotIn("pasivos_totales_usd", merged.get("_field_sources", {}))
        self.assertTrue(any("cross_period_blocked" in w for w in warnings))


    # ── V5.1 Imputation tests ──────────────────────────────────────────

    def test_fallback_critical_with_identity_imputation(self):
        """When fallback can't fill pasivos (cross-period), identity imputation kicks in."""
        extractions = [
            {
                "filing_type": "ANNUAL_REPORT",
                "balance_sheet_ultimo": {
                    "periodo": "FY2024",
                    "fecha_fin": "2024-12-31",
                    "activos_totales_usd": 120.0,
                    "pasivos_totales_usd": None,
                    "patrimonio_usd": 50.0,
                },
            },
        ]
        warnings = []
        merged = _merge_balance_sheet(extractions, warnings)
        # Should be imputed: 120 - 50 = 70
        self.assertEqual(merged.get("pasivos_totales_usd"), 70.0)
        self.assertEqual(
            merged.get("_field_sources", {}).get("pasivos_totales_usd"),
            "IMPUTED:balance_identity",
        )
        self.assertTrue(any("imputed via identity" in w for w in warnings))


class TpImputeBalanceIdentityTests(unittest.TestCase):
    """Direct tests for _impute_balance_identity()."""

    def test_impute_liabilities_from_identity(self):
        base = {"activos_totales_usd": 120.0, "pasivos_totales_usd": None, "patrimonio_usd": 50.0}
        prov = {}
        warnings = []
        _impute_balance_identity(base, prov, warnings)
        self.assertEqual(base["pasivos_totales_usd"], 70.0)
        self.assertEqual(prov["pasivos_totales_usd"], "IMPUTED:balance_identity")

    def test_impute_equity_from_identity(self):
        base = {"activos_totales_usd": 120.0, "pasivos_totales_usd": 70.0, "patrimonio_usd": None}
        prov = {}
        warnings = []
        _impute_balance_identity(base, prov, warnings)
        self.assertEqual(base["patrimonio_usd"], 50.0)
        self.assertEqual(prov["patrimonio_usd"], "IMPUTED:balance_identity")

    def test_impute_assets_from_identity(self):
        base = {"activos_totales_usd": None, "pasivos_totales_usd": 70.0, "patrimonio_usd": 50.0}
        prov = {}
        warnings = []
        _impute_balance_identity(base, prov, warnings)
        self.assertEqual(base["activos_totales_usd"], 120.0)
        self.assertEqual(prov["activos_totales_usd"], "IMPUTED:balance_identity")

    def test_no_impute_when_all_present(self):
        base = {"activos_totales_usd": 120.0, "pasivos_totales_usd": 70.0, "patrimonio_usd": 50.0}
        prov = {}
        warnings = []
        _impute_balance_identity(base, prov, warnings)
        # No changes
        self.assertEqual(base["activos_totales_usd"], 120.0)
        self.assertEqual(base["pasivos_totales_usd"], 70.0)
        self.assertEqual(base["patrimonio_usd"], 50.0)
        self.assertEqual(prov, {})

    def test_no_impute_when_only_one_present(self):
        base = {"activos_totales_usd": 120.0, "pasivos_totales_usd": None, "patrimonio_usd": None}
        prov = {}
        warnings = []
        _impute_balance_identity(base, prov, warnings)
        self.assertIsNone(base["pasivos_totales_usd"])
        self.assertIsNone(base["patrimonio_usd"])

    def test_no_impute_negative(self):
        base = {"activos_totales_usd": 50.0, "pasivos_totales_usd": None, "patrimonio_usd": 80.0}
        prov = {}
        warnings = []
        _impute_balance_identity(base, prov, warnings)
        # Would be 50 - 80 = -30, so should NOT impute
        self.assertIsNone(base["pasivos_totales_usd"])
        self.assertTrue(any("negative" in w for w in warnings))

    def test_impute_provenance_tracked(self):
        base = {"activos_totales_usd": 120.0, "pasivos_totales_usd": None, "patrimonio_usd": 50.0}
        prov = {"activos_totales_usd": "ANNUAL_REPORT", "patrimonio_usd": "ANNUAL_REPORT"}
        warnings = []
        _impute_balance_identity(base, prov, warnings)
        self.assertEqual(prov["pasivos_totales_usd"], "IMPUTED:balance_identity")
        self.assertEqual(prov["activos_totales_usd"], "ANNUAL_REPORT")  # untouched


class TpImputeDeudaTotalTests(unittest.TestCase):
    """Direct tests for _impute_deuda_total()."""

    def test_deuda_from_lt_plus_st(self):
        base = {"deuda_total_usd": None, "deuda_largo_plazo_usd": 50.0, "deuda_corto_plazo_usd": 20.0}
        prov = {}
        warnings = []
        _impute_deuda_total(base, prov, warnings)
        self.assertEqual(base["deuda_total_usd"], 70.0)
        self.assertEqual(prov["deuda_total_usd"], "IMPUTED:debt_components")

    def test_deuda_lt_only(self):
        base = {"deuda_total_usd": None, "deuda_largo_plazo_usd": 50.0}
        prov = {}
        warnings = []
        _impute_deuda_total(base, prov, warnings)
        self.assertEqual(base["deuda_total_usd"], 50.0)
        self.assertEqual(prov["deuda_total_usd"], "IMPUTED:long_term_only")

    def test_no_impute_deuda_when_present(self):
        base = {"deuda_total_usd": 100.0, "deuda_largo_plazo_usd": 50.0, "deuda_corto_plazo_usd": 20.0}
        prov = {}
        warnings = []
        _impute_deuda_total(base, prov, warnings)
        self.assertEqual(base["deuda_total_usd"], 100.0)
        self.assertEqual(prov, {})

    def test_no_impute_deuda_nothing_available(self):
        base = {"deuda_total_usd": None}
        prov = {}
        warnings = []
        _impute_deuda_total(base, prov, warnings)
        self.assertIsNone(base["deuda_total_usd"])

    def test_warns_when_only_lease_data_exists(self):
        merged_like = {
            "balance_sheet_ultimo": {"deuda_total_usd": None},
            "lease_data": {
                "lease_liabilities_total_usd": 795.4,
                "lease_liabilities_current_usd": 216.0,
                "lease_liabilities_non_current_usd": 580.0,
            },
        }
        warnings = []
        _warn_lease_only_debt_missing(merged_like, warnings)
        self.assertTrue(any("lease_only_not_used_for_total_debt" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
