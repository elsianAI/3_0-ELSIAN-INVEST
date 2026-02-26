import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runners.deterministic_extractor import (
    extract_deterministic_facts,
    format_deterministic_hints_block,
    split_semantic_chunks,
)


class DeterministicExtractorTests(unittest.TestCase):
    def test_extract_anchor_fields_with_section_units(self):
        text = """
## INCOME STATEMENT
In millions of EUR
Total revenue 10,280
Net income 523

## BALANCE SHEET
In millions of EUR
Total assets 12,074
Total liabilities 7,518
Total equity 4,556
"""
        out = extract_deterministic_facts(text)
        best = out.get("best_by_field", {})
        self.assertIn("ingresos_usd", best)
        self.assertIn("activos_totales_usd", best)
        self.assertIn("pasivos_totales_usd", best)
        self.assertIn("patrimonio_usd", best)
        # 10,280 * 1,000,000
        self.assertGreater(best["ingresos_usd"]["value"], 1_000_000_000)

    def test_debt_hints_do_not_trigger_on_lease_only_line(self):
        text = """
## BALANCE SHEET
In millions of EUR
Lease liabilities non-current 795.4
"""
        out = extract_deterministic_facts(text)
        best = out.get("best_by_field", {})
        self.assertNotIn("deuda_largo_plazo_usd", best)
        self.assertNotIn("deuda_corto_plazo_usd", best)

    def test_split_semantic_chunks_prefers_sections(self):
        text = (
            "## INCOME STATEMENT\n" + ("Revenue 100\n" * 3000) +
            "## BALANCE SHEET\n" + ("Total assets 200\n" * 3000) +
            "## CASH FLOW\n" + ("Cash from operations 50\n" * 3000)
        )
        chunks = split_semantic_chunks(
            text,
            target_chars=8000,
            max_chars=10000,
            overlap_chars=800,
            max_chunks=8,
        )
        self.assertGreaterEqual(len(chunks), 2)
        self.assertLessEqual(len(chunks), 8)
        self.assertTrue(all("text" in c and c["text"] for c in chunks))

    def test_format_deterministic_hints_block(self):
        extraction = {
            "entries": [],
            "best_by_field": {
                "ingresos_usd": {
                    "value": 10280000000,
                    "section": "income_statement",
                    "line": 12,
                    "confidence": "high",
                }
            },
        }
        block = format_deterministic_hints_block(extraction)
        self.assertIsNotNone(block)
        self.assertIn("DATOS PRE-EXTRAIDOS", block)
        self.assertIn("ingresos_usd", block)


if __name__ == "__main__":
    unittest.main()

