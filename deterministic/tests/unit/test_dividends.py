"""Tests for _extract_dividends_per_share in pipeline.py."""

import unittest

from deterministic.src.pipeline import _extract_dividends_per_share


class TestExtractDividendsPerShare(unittest.TestCase):

    def test_single_dividend(self):
        text = (
            "Balance at December 31, 2022\n"
            "Some equity movements...\n"
            "Dividend paid ($ 1.71 per share)\n"
        )
        results = _extract_dividends_per_share(text, "test.clean.md")
        self.assertEqual(len(results), 1)
        period, value, loc = results[0]
        self.assertEqual(period, "FY2023")
        self.assertAlmostEqual(value, 1.71)
        self.assertIn("test.clean.md", loc)

    def test_multiple_dividends(self):
        text = (
            "Balance at December 31, 2020\n"
            "Dividend paid ($ 1.50 per share)\n"
            "Balance at December 31, 2021\n"
            "Dividend paid ($ 1.60 per share)\n"
            "Balance at December 31, 2022\n"
            "Dividend paid ($ 1.71 per share)\n"
        )
        results = _extract_dividends_per_share(text, "f.md")
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0][0], "FY2021")
        self.assertAlmostEqual(results[0][1], 1.50)
        self.assertEqual(results[1][0], "FY2022")
        self.assertAlmostEqual(results[1][1], 1.60)
        self.assertEqual(results[2][0], "FY2023")
        self.assertAlmostEqual(results[2][1], 1.71)

    def test_no_balance_marker_returns_empty(self):
        text = "Dividend paid ($ 1.71 per share)\n"
        results = _extract_dividends_per_share(text, "f.md")
        self.assertEqual(results, [])

    def test_no_dividend_returns_empty(self):
        text = "Balance at December 31, 2022\nSome other text\n"
        results = _extract_dividends_per_share(text, "f.md")
        self.assertEqual(results, [])

    def test_comma_in_value(self):
        text = (
            "Balance at December 31, 2023\n"
            "Dividend paid ($ 1,234.56 per share)\n"
        )
        results = _extract_dividends_per_share(text, "f.md")
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0][1], 1234.56)

    def test_case_insensitive(self):
        text = (
            "balance at december 31, 2022\n"
            "dividend paid ($ 2.00 per share)\n"
        )
        results = _extract_dividends_per_share(text, "f.md")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "FY2023")


if __name__ == "__main__":
    unittest.main()
