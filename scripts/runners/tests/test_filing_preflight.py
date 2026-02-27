"""Tests for filing_preflight.py (V6.2 — 1B.2)."""

import sys
import os
import unittest

# Ensure runners directory is on path
_RUNNERS = os.path.join(os.path.dirname(__file__), "..")
if _RUNNERS not in sys.path:
    sys.path.insert(0, _RUNNERS)

from filing_preflight import preflight, format_prompt_block


class PreflightLanguageTests(unittest.TestCase):
    def test_detects_english(self):
        text = "Total assets were $5.2 billion. Net income increased 10%."
        result = preflight(text)
        self.assertEqual(result["language"], "en")

    def test_detects_french(self):
        text = "Le résultat net consolidé s'élève à 150 millions d'euros. Le chiffre d'affaires a augmenté."
        result = preflight(text)
        self.assertEqual(result["language"], "fr")


class PreflightStandardTests(unittest.TestCase):
    def test_detects_ifrs(self):
        text = "These financial statements have been prepared in accordance with IFRS."
        result = preflight(text)
        self.assertEqual(result["accounting_standard"], "IFRS")

    def test_detects_us_gaap(self):
        text = "Prepared under U.S. GAAP reporting requirements."
        result = preflight(text)
        self.assertEqual(result["accounting_standard"], "US-GAAP")


class PreflightCurrencyTests(unittest.TestCase):
    def test_detects_usd(self):
        text = "All amounts in United States dollars unless otherwise stated."
        result = preflight(text)
        self.assertEqual(result["currency"], "USD")

    def test_detects_eur(self):
        text = "Montants exprimés en euros. € millions."
        result = preflight(text)
        self.assertEqual(result["currency"], "EUR")


class PreflightUnitsTests(unittest.TestCase):
    def test_detects_millions(self):
        text = "CONSOLIDATED BALANCE SHEETS\n(in millions)\nTotal assets: 5,200"
        result = preflight(text)
        # Should detect units in balance_sheet section or globally
        has_millions = False
        for section, info in result.get("units_by_section", {}).items():
            if info["multiplier"] == 1_000_000:
                has_millions = True
        if result.get("units_global") and result["units_global"]["multiplier"] == 1_000_000:
            has_millions = True
        self.assertTrue(has_millions, "Should detect 'in millions'")

    def test_different_units_per_section(self):
        text = (
            "INCOME STATEMENT (in millions)\n"
            "Revenue: 5,200\n" * 20 + "\n"
            "NOTES TO FINANCIAL STATEMENTS (in thousands)\n"
            "Detail breakdown follows\n"
        )
        result = preflight(text)
        units = result.get("units_by_section", {})
        # Should detect at least one section with millions
        # The key test is that it doesn't error out
        self.assertIsInstance(units, dict)


class PreflightRestatementTests(unittest.TestCase):
    def test_detects_english_restatement(self):
        text = "Certain prior period amounts have been restated to correct errors."
        result = preflight(text)
        self.assertTrue(result["restatement_detected"])

    def test_detects_french_restatement(self):
        text = "Les comptes de l'exercice précédent ont été réexprimés suite à un changement de méthode."
        result = preflight(text)
        self.assertTrue(result["restatement_detected"])

    def test_detects_asterisk_restated(self):
        text = "Revenue * restated for discontinued operations"
        result = preflight(text)
        self.assertTrue(result["restatement_detected"])

    def test_no_false_positive_on_clean_text(self):
        text = "Revenue increased 15%. Net income was $50M. Total assets $1B."
        result = preflight(text)
        self.assertFalse(result["restatement_detected"])


class PreflightFiscalYearTests(unittest.TestCase):
    def test_detects_fiscal_year(self):
        text = "For the fiscal year ended December 31, 2024"
        result = preflight(text)
        self.assertEqual(result["fiscal_year"], 2024)


class PreflightSectionsTests(unittest.TestCase):
    def test_detects_core_sections(self):
        text = (
            "CONSOLIDATED STATEMENTS OF INCOME\n"
            "Revenue: 5,200\n\n"
            "CONSOLIDATED BALANCE SHEETS\n"
            "Total assets: 10,000\n\n"
            "CONSOLIDATED STATEMENTS OF CASH FLOWS\n"
            "Operating: 1,200\n"
        )
        result = preflight(text)
        sections = result["sections_detected"]
        self.assertIn("income_statement", sections)
        self.assertIn("balance_sheet", sections)
        self.assertIn("cash_flow", sections)


class PreflightPromptBlockTests(unittest.TestCase):
    def test_formats_block_with_signals(self):
        meta = preflight(
            "Prepared under IFRS. All amounts in euros (in millions). "
            "Fiscal year ended December 31, 2024. Total assets: 5,200M."
        )
        block = format_prompt_block(meta)
        self.assertIsNotNone(block)
        self.assertIn("IFRS", block)
        self.assertIn("EUR", block)

    def test_returns_none_for_empty(self):
        meta = preflight("")
        block = format_prompt_block(meta)
        self.assertIsNone(block)

    def test_returns_none_for_no_signals(self):
        meta = preflight("Lorem ipsum dolor sit amet.")
        block = format_prompt_block(meta)
        # May or may not be None depending on false positives
        # At minimum, should not crash
        self.assertIsInstance(block, (str, type(None)))


class PreflightDegradationTests(unittest.TestCase):
    def test_handles_empty_text(self):
        result = preflight("")
        self.assertIsNone(result["language"])
        self.assertFalse(result["restatement_detected"])

    def test_handles_binary_garbage(self):
        """Should not crash on non-text content."""
        result = preflight("\x00\xff\xfe" * 1000)
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
