import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.tp_calculator import _ttm


class TpCalculatorTtmSemestralTests(unittest.TestCase):
    def _annual_fy2024(self) -> dict:
        return {
            "periodo": "FY2024",
            "fecha_fin": "2024-12-31",
            "ingresos_usd": 10_280_000_000.0,
            "ebit_usd": 1_082_000_000.0,
            "net_income_usd": 434_000_000.0,
            "cfo_usd": 1_813_000_000.0,
            "capex_usd": -258_000_000.0,
        }

    def _quarterly_revenue_only(self) -> list[dict]:
        return [
            {"periodo": "Q3-2024", "fecha_fin": "2024-09-30", "ingresos_usd": 2_550_000_000.0},
            {"periodo": "Q4-2024", "fecha_fin": "2024-12-31", "ingresos_usd": 2_730_000_000.0},
            {"periodo": "Q1-2025", "fecha_fin": "2025-03-31", "ingresos_usd": 2_590_000_000.0},
            {"periodo": "Q2-2025", "fecha_fin": "2025-06-30", "ingresos_usd": 2_450_000_000.0},
        ]

    def _h1_entries_complete(self) -> list[dict]:
        return [
            {
                "periodo": "H1-2024",
                "fecha_fin": "2024-06-30",
                "_periodo_parcial": True,
                "ingresos_usd": 5_076_000_000.0,
                "ebit_usd": 503_000_000.0,
                "net_income_usd": 247_000_000.0,
                "cfo_usd": 771_000_000.0,
                "capex_usd": -268_000_000.0,
            },
            {
                "periodo": "H1-2025",
                "fecha_fin": "2025-06-30",
                "_periodo_parcial": True,
                "ingresos_usd": 5_116_000_000.0,
                "ebit_usd": 530_000_000.0,
                "net_income_usd": 294_000_000.0,
                "cfo_usd": 588_000_000.0,
                "capex_usd": -248_000_000.0,
            },
        ]

    def test_ttm_upgrades_to_semestral_when_quarterly_is_sparse(self):
        annual = [self._annual_fy2024()]
        quarters = self._quarterly_revenue_only() + self._h1_entries_complete()

        ttm = _ttm(annual, quarters)

        self.assertEqual(ttm.get("metodo"), "semestral_FY_H1")
        self.assertEqual(ttm.get("ingresos_usd"), 10_320_000_000.0)
        self.assertEqual(ttm.get("ebit_usd"), 1_109_000_000.0)
        self.assertEqual(ttm.get("cfo_usd"), 1_630_000_000.0)
        self.assertEqual(ttm.get("capex_usd"), -238_000_000.0)
        self.assertIsNotNone(ttm.get("nota"))
        self.assertIn("semestral", str(ttm.get("nota")).lower())

    def test_ttm_keeps_quarterly_method_when_semestral_not_applicable(self):
        annual = [self._annual_fy2024()]
        quarters = self._quarterly_revenue_only() + [
            {
                "periodo": "H1-2025",
                "fecha_fin": "2025-06-30",
                "_periodo_parcial": True,
                "ingresos_usd": 5_116_000_000.0,
                # Missing ebit/cfo on purpose -> semestral fallback must not apply.
                "ebit_usd": None,
                "cfo_usd": None,
            }
        ]

        ttm = _ttm(annual, quarters)

        self.assertEqual(ttm.get("metodo"), "suma_4_trimestres")
        self.assertIsNotNone(ttm.get("ingresos_usd"))
        self.assertIsNone(ttm.get("ebit_usd"))
        self.assertIsNone(ttm.get("cfo_usd"))


if __name__ == "__main__":
    unittest.main()

