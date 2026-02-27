"""Tests for deterministic.src.extract.tables"""

import unittest
from pathlib import Path

from deterministic.src.extract.tables import (
    parse_number,
    extract_from_markdown_table,
    extract_tables_from_clean_md,
)


class TestParseNumber(unittest.TestCase):
    def test_simple_integer(self):
        self.assertEqual(parse_number("1234"), 1234.0)

    def test_comma_thousands(self):
        self.assertEqual(parse_number("1,234,567"), 1234567.0)

    def test_decimal(self):
        self.assertEqual(parse_number("1,234.56"), 1234.56)

    def test_negative_parentheses(self):
        self.assertEqual(parse_number("(1,234)"), -1234.0)

    def test_negative_sign(self):
        self.assertEqual(parse_number("-1,234"), -1234.0)

    def test_dollar_sign(self):
        self.assertEqual(parse_number("$1,234"), 1234.0)

    def test_euro_sign(self):
        self.assertEqual(parse_number("€1,234"), 1234.0)

    def test_dash_none(self):
        self.assertIsNone(parse_number("—"))

    def test_na_none(self):
        self.assertIsNone(parse_number("N/A"))

    def test_empty_none(self):
        self.assertIsNone(parse_number(""))

    def test_european_format(self):
        self.assertAlmostEqual(parse_number("1.234,56"), 1234.56, places=2)

    def test_percentage(self):
        self.assertAlmostEqual(parse_number("25.5%"), 25.5, places=1)


class TestExtractFromMarkdownTable(unittest.TestCase):
    def test_simple_table(self):
        table = """| | 2024 | 2023 |
| --- | --- | --- |
| Revenue | 185,200 | 162,400 |
| Net income | 25,500 | 20,000 |"""

        fields = extract_from_markdown_table(table, "income_statement")
        self.assertTrue(len(fields) >= 4)

        # Check Revenue 2024
        rev_2024 = [
            f for f in fields
            if f.label == "Revenue" and "FY2024" in f.column_header
        ]
        self.assertEqual(len(rev_2024), 1)
        self.assertEqual(rev_2024[0].value, 185200.0)

    def test_table_with_dated_headers(self):
        table = """| | Year Ended December 31, 2024 | Year Ended December 31, 2023 |
| --- | --- | --- |
| Revenue | 100 | 90 |"""

        fields = extract_from_markdown_table(table)
        fy24 = [f for f in fields if "FY2024" in f.column_header]
        self.assertTrue(len(fy24) >= 1)

    def test_negative_values(self):
        table = """| | 2024 | 2023 |
| --- | --- | --- |
| Cost of revenue | (98,500) | (87,200) |"""

        fields = extract_from_markdown_table(table)
        costs = [f for f in fields if f.label == "Cost of revenue"]
        self.assertTrue(any(f.value == -98500.0 for f in costs))


class TestExtractTablesFromCleanMd(unittest.TestCase):
    def test_fixture_file(self):
        fixture_path = (
            Path(__file__).parent.parent / "fixtures" / "table_10k_sample.md"
        )
        if not fixture_path.exists():
            self.skipTest("Fixture file not found")

        text = fixture_path.read_text(encoding="utf-8")
        fields = extract_tables_from_clean_md(text, "test_fixture.md")

        # Should extract multiple fields
        self.assertTrue(len(fields) > 0)

        # Check that Revenue is extracted
        revenues = [f for f in fields if "Revenue" in f.label or "revenue" in f.label.lower()]
        self.assertTrue(len(revenues) > 0)


if __name__ == "__main__":
    unittest.main()
