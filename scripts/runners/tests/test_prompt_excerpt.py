import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.prompt_builder import _build_financial_focus_excerpt


class PromptExcerptTests(unittest.TestCase):
    def test_short_content_returns_full(self):
        content = "Revenue and cash flow summary."
        excerpt, meta = _build_financial_focus_excerpt(content, "ANNUAL_REPORT", 300_000)
        self.assertEqual(excerpt, content)
        self.assertEqual(meta.get("mode"), "full")

    def test_long_content_uses_smart_excerpt_when_anchors_exist(self):
        filler_a = ("intro text " * 9000)
        anchor_block = (
            "CONSOLIDATED BALANCE SHEETS\n"
            + ("Total assets 1000 Total liabilities 600 Equity 400\n" * 400)
            + "STATEMENT OF CASH FLOWS\n"
            + ("Net cash provided by operating activities 123\n" * 400)
        )
        filler_b = ("tail filler " * 12000)
        content = filler_a + anchor_block + filler_b

        limit = 120_000
        excerpt, meta = _build_financial_focus_excerpt(content, "ANNUAL_REPORT", limit)
        self.assertEqual(meta.get("mode"), "smart_excerpt")
        self.assertLessEqual(len(excerpt), limit)
        self.assertGreaterEqual(int(meta.get("selected_windows", 0)), 1)
        self.assertIn("balance sheets", excerpt.lower())

    def test_long_content_without_anchors_falls_back_to_linear(self):
        content = "x" * 220_000
        limit = 100_000
        excerpt, meta = _build_financial_focus_excerpt(content, "OTHER", limit)
        self.assertEqual(meta.get("mode"), "linear_fallback")
        self.assertEqual(excerpt, content[:limit])

    def test_french_balance_sheet_anchors_trigger_excerpt(self):
        filler = ("texte introductif " * 12000)
        french_block = (
            "Bilan consolidé\n"
            + ("Total de l'actif 1000 Total du passif 600\n" * 350)
        )
        content = filler + french_block + ("annexes " * 12000)
        excerpt, meta = _build_financial_focus_excerpt(content, "ANNUAL_REPORT", 150_000)
        self.assertEqual(meta.get("mode"), "smart_excerpt")
        self.assertIn("total de l'actif", excerpt.lower())


if __name__ == "__main__":
    unittest.main()
