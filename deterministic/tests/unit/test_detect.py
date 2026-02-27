"""Tests for deterministic.src.extract.detect"""

import unittest

from deterministic.src.extract.detect import (
    detect_currency,
    detect_language,
    detect_periods,
    detect_scale,
    detect_sections,
    detect_filing_type,
    detect_period_end_date,
    analyze_filing,
)


class TestDetectCurrency(unittest.TestCase):
    def test_usd_dollar_sign(self):
        self.assertEqual(detect_currency("Revenue was $185,200"), "USD")

    def test_eur_symbol(self):
        self.assertEqual(detect_currency("Chiffre d'affaires: €10,280M"), "EUR")

    def test_gbp_symbol(self):
        self.assertEqual(detect_currency("Revenue £5,200 million"), "GBP")

    def test_default_usd(self):
        self.assertEqual(detect_currency("no currency here"), "USD")

    def test_mixed_currencies(self):
        text = "$100 $200 $300 €50"
        self.assertEqual(detect_currency(text), "USD")


class TestDetectScale(unittest.TestCase):
    def test_in_millions(self):
        scale, conf = detect_scale("(in millions)")
        self.assertEqual(scale, "millions")
        self.assertEqual(conf, "high")

    def test_in_thousands(self):
        scale, conf = detect_scale("Amounts in thousands of USD")
        self.assertEqual(scale, "thousands")
        self.assertEqual(conf, "high")

    def test_in_billions(self):
        scale, conf = detect_scale("(in billions)")
        self.assertEqual(scale, "billions")
        self.assertEqual(conf, "high")

    def test_no_scale(self):
        scale, conf = detect_scale("just some text")
        self.assertEqual(scale, "raw")
        self.assertEqual(conf, "low")

    def test_french_millions(self):
        scale, conf = detect_scale("(en millions d'euros)")
        self.assertEqual(scale, "millions")
        self.assertEqual(conf, "high")


class TestDetectLanguage(unittest.TestCase):
    def test_english(self):
        self.assertEqual(detect_language("Revenue for the year ended"), "en")

    def test_french(self):
        text = "Le chiffre d'affaires du groupe et le résultat net de l'exercice"
        self.assertEqual(detect_language(text), "fr")

    def test_spanish(self):
        text = "Los ingresos totales y el beneficio neto del ejercicio"
        self.assertEqual(detect_language(text), "es")


class TestDetectPeriods(unittest.TestCase):
    def test_fy_pattern(self):
        periods = detect_periods("FY2024 results")
        self.assertIn("FY2024", periods)

    def test_quarter_pattern(self):
        periods = detect_periods("Q3-2024 quarterly results")
        self.assertIn("Q3-2024", periods)

    def test_year_ended(self):
        periods = detect_periods("For the Year Ended December 31, 2024")
        self.assertIn("FY2024", periods)

    def test_three_months_ended(self):
        periods = detect_periods("Three Months Ended September 30, 2024")
        self.assertIn("Q3-2024", periods)

    def test_multiple_periods(self):
        text = "FY2024 versus FY2023, Q3-2024 data"
        periods = detect_periods(text)
        self.assertIn("FY2024", periods)
        self.assertIn("FY2023", periods)
        self.assertIn("Q3-2024", periods)


class TestDetectSections(unittest.TestCase):
    def test_income_statement(self):
        text = "CONSOLIDATED STATEMENTS OF INCOME"
        sections = detect_sections(text)
        self.assertIn("income_statement", sections)

    def test_balance_sheet(self):
        text = "CONSOLIDATED BALANCE SHEET"
        sections = detect_sections(text)
        self.assertIn("balance_sheet", sections)

    def test_cash_flow(self):
        text = "CONSOLIDATED STATEMENTS OF CASH FLOWS"
        sections = detect_sections(text)
        self.assertIn("cash_flow", sections)


class TestDetectFilingType(unittest.TestCase):
    def test_10k(self):
        self.assertEqual(detect_filing_type("SRC_001_10-K_FY2024.htm"), "10-K")

    def test_10q(self):
        self.assertEqual(detect_filing_type("SRC_005_10-Q_Q3-2024.htm"), "10-Q")

    def test_8k(self):
        self.assertEqual(detect_filing_type("SRC_010_8-K_2024-11-06.htm"), "8-K")


class TestDetectPeriodEndDate(unittest.TestCase):
    def test_year_ended(self):
        text = "For the Year Ended December 31, 2024"
        self.assertEqual(detect_period_end_date(text), "2024-12-31")

    def test_iso_date(self):
        text = "Period ending 2024-06-30"
        self.assertEqual(detect_period_end_date(text), "2024-06-30")


class TestAnalyzeFiling(unittest.TestCase):
    def test_full_analysis(self):
        text = """(in millions)
        CONSOLIDATED STATEMENTS OF INCOME
        For the Year Ended December 31, 2024
        Revenue: $185,200
        """
        meta = analyze_filing("SRC_001_10-K_FY2024.clean.md", text)
        self.assertEqual(meta.scale, "millions")
        self.assertEqual(meta.currency, "USD")
        self.assertEqual(meta.filing_type, "10-K")
        self.assertIn("income_statement", meta.sections_found)


if __name__ == "__main__":
    unittest.main()
