import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.tp_normalizer import normalize


class TpNormalizerScaleRepairTests(unittest.TestCase):
    def test_applies_entry_scale_multiplier_for_monetary_fields(self):
        raw = {
            "historico_anual": [
                {
                    "periodo": "FY2024",
                    "fecha_fin": "2024-12-31",
                    "tipo_periodo": "anual",
                    "moneda_original": "EUR",
                    "scale": "millions",
                    "revenue": 10280.0,
                    "operating_income": 1331.0,
                }
            ],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        out = normalize(raw)
        annual = out.get("historico_anual", [])
        self.assertEqual(len(annual), 1)
        self.assertEqual(annual[0].get("ingresos_usd"), 10_280_000_000.0)
        self.assertEqual(annual[0].get("ebit_usd"), 1_331_000_000.0)

    def test_repairs_revenue_from_raw_source_when_missing(self):
        raw = {
            "historico_anual": [
                {
                    "periodo": "FY2021",
                    "fecha_fin": "2021-12-31",
                    "tipo_periodo": "anual",
                    "moneda_original": "EUR",
                    "revenue": None,
                    "_source_data_raw_eur_m": {"revenue_eur_m": 7115},
                }
            ],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        out = normalize(raw)
        annual = out.get("historico_anual", [])
        self.assertEqual(len(annual), 1)
        self.assertEqual(annual[0].get("ingresos_usd"), 7_115_000_000.0)

    def test_repairs_tiny_revenue_from_raw_source(self):
        raw = {
            "historico_anual": [
                {
                    "periodo": "FY2021",
                    "fecha_fin": "2021-12-31",
                    "tipo_periodo": "anual",
                    "moneda_original": "EUR",
                    "ingresos_usd": 47.0,
                    "_source_data_raw_eur_m": {"revenue_eur_m": 7115},
                }
            ],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        out = normalize(raw)
        annual = out.get("historico_anual", [])
        self.assertEqual(len(annual), 1)
        self.assertEqual(annual[0].get("ingresos_usd"), 7_115_000_000.0)


if __name__ == "__main__":
    unittest.main()

