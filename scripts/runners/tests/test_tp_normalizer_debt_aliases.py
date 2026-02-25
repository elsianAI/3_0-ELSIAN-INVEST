import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.tp_normalizer import normalize


class TpNormalizerDebtAliasesTests(unittest.TestCase):
    def test_maps_ifrs_other_financial_liabilities_to_debt_components(self):
        raw = {
            "balance_sheet_ultimo": {
                "other_financial_liabilities_non_current": 300.0,
                "other_financial_liabilities_current": 120.0,
            },
            "historico_anual": [],
            "historico_trimestral": [],
        }
        out = normalize(raw)
        bs = out.get("balance_sheet_ultimo", {})
        self.assertEqual(bs.get("deuda_largo_plazo_usd"), 300.0)
        self.assertEqual(bs.get("deuda_corto_plazo_usd"), 120.0)


if __name__ == "__main__":
    unittest.main()
