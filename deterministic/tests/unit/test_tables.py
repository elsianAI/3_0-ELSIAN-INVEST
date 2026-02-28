"""Tests for deterministic.src.extract.tables"""

import re
import unittest
from pathlib import Path

from deterministic.src.extract.tables import (
    parse_number,
    extract_from_markdown_table,
    extract_tables_from_clean_md,
)
from deterministic.src.pipeline import DeterministicPipeline


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


    def test_double_header_year_ended_plus_years(self):
        """Double-header table: 'Year Ended December 31,' row then '2024 / 2023' sub-row."""
        table = """| | Year Ended December 31, | | | | | | |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | 2024 | | 2023 | | | | |
| Revenues | $ | 83,902 | | | $ | 84,477 | |
| Net income | $ | 13,682 | | | $ | 12,468 | |"""

        fields = extract_from_markdown_table(table, "income_statement")
        fy24_rev = [
            f for f in fields
            if f.label == "Revenues" and f.column_header == "FY2024"
        ]
        fy23_rev = [
            f for f in fields
            if f.label == "Revenues" and f.column_header == "FY2023"
        ]
        self.assertEqual(len(fy24_rev), 1)
        self.assertEqual(fy24_rev[0].value, 83902.0)
        self.assertEqual(len(fy23_rev), 1)
        self.assertEqual(fy23_rev[0].value, 84477.0)

    def test_percentage_rows_are_skipped(self):
        """Rows with '%' in data cells must be filtered out."""
        table = """| | 2024 | | 2023 | | |
| --- | --- | --- | --- | --- | --- |
| Revenues | 100.0 | % | | 100.0 | % |
| Gross profit | 87.5 | | | 87.1 | |"""

        fields = extract_from_markdown_table(table, "income_statement")
        # "Revenues" row has "%" → skipped; "Gross profit" has no "%" → extracted
        rev = [f for f in fields if f.label == "Revenues"]
        self.assertEqual(len(rev), 0, "Percentage rows should be skipped")
        gp = [f for f in fields if f.label == "Gross profit"]
        self.assertTrue(len(gp) > 0, "Non-percentage rows should be extracted")

    def test_currency_symbol_column_skip(self):
        """When a column has '$' and the next column has the number, use the number."""
        table = """| | 2024 | | 2023 | | | | |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Revenues | $ | 83,902 | | | $ | 84,477 | |"""

        fields = extract_from_markdown_table(table, "income_statement")
        # Should pick up 83,902 and 84,477 despite "$" in the mapped column
        vals = [f.value for f in fields if f.label == "Revenues"]
        self.assertIn(83902.0, vals)

    # ── Iteration 4: row-level filtering ────────────────────────────

    def test_total_liabilities_and_equity_row_ignored(self):
        """'Total liabilities and stockholders' equity' row must be filtered."""
        table = """| | 2024 | 2023 |
| --- | --- | --- |
| Total liabilities | 50,369 | 46,499 |
| Total liabilities and stockholders' equity | 54,722 | 55,382 |"""

        fields = extract_from_markdown_table(table, "balance_sheet")
        labels = [f.label for f in fields]
        self.assertIn("Total liabilities", labels)
        self.assertNotIn("Total liabilities and stockholders' equity", labels)

    def test_eps_row_not_extracted_as_net_income(self):
        """EPS row labels should not be extractable as generic net_income.\n\n        This is tested at the alias level; here we verify the row IS extracted
        with its original label so the alias resolver can route it to eps_*."""
        table = """| | 2024 | 2023 |
| --- | --- | --- |
| Net income per share—diluted | 1.06 | 0.83 |"""

        fields = extract_from_markdown_table(table, "income_statement")
        self.assertTrue(len(fields) >= 2)
        # The label should still be present (not filtered out at table level)
        labels = [f.label for f in fields]
        self.assertIn("Net income per share—diluted", labels)


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

    def test_global_table_index_across_subsections(self):
        """Tables in different subsections must get unique global tbl indices.

        Reproduces the collision: two tables (one percentage, one monetary)
        in different subsections of the same section both ended up as tbl0,
        making their source_locations identical and causing wrong collision
        resolution.
        """
        md = (
            "## Income Statement\n"
            "### Operating Income\n"
            "| | 2024 |\n"
            "| --- | --- |\n"
            "| Cost of revenue | 12.5 |\n"
            "\n"
            "### Revenue Breakdown\n"
            "| | 2024 |\n"
            "| --- | --- |\n"
            "| Cost of revenue | 10,469 |\n"
        )
        fields = extract_tables_from_clean_md(md, "test.clean.md")
        cost_fields = [f for f in fields if "Cost of revenue" in f.label]
        self.assertEqual(len(cost_fields), 2, "Should find 2 cost_of_revenue entries")

        # Extract tbl indices from source_location
        tbl_indices = []
        for f in cost_fields:
            m = re.search(r"tbl(\d+)", f.source_location)
            self.assertIsNotNone(m, f"No tbl index in {f.source_location}")
            tbl_indices.append(int(m.group(1)))

        # Must be different indices (global counter, not per-subsection)
        self.assertNotEqual(
            tbl_indices[0], tbl_indices[1],
            f"Both tables got same tbl index {tbl_indices[0]}; "
            "global counter not working"
        )
        # First table should be tbl0, second tbl1
        self.assertEqual(tbl_indices[0], 0)
        self.assertEqual(tbl_indices[1], 1)

    def test_global_tbl_idx_collision_correct_value_wins(self):
        """With global tbl indexing + descending tbl tiebreak, the later table
        (monetary value 10469) must win over the earlier table (pct value 12.5)
        when both map to the same canonical field in the same period.
        """
        md = (
            "## Income Statement\n"
            "### Operating Income\n"
            "| | 2024 |\n"
            "| --- | --- |\n"
            "| Cost of revenue | 12.5 |\n"
            "\n"
            "### Revenue Breakdown\n"
            "| | 2024 |\n"
            "| --- | --- |\n"
            "| Cost of revenue | 10,469 |\n"
        )
        fields = extract_tables_from_clean_md(md, "test.clean.md")
        cost_fields = [f for f in fields if "Cost of revenue" in f.label]
        self.assertEqual(len(cost_fields), 2)

        # Compute sort keys and verify later table wins
        key0 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="test.clean.md",
            source_location=cost_fields[0].source_location,
        )
        key1 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="test.clean.md",
            source_location=cost_fields[1].source_location,
        )
        # Later table (tbl1, value=10469) should have lower sort key → wins
        self.assertLess(key1, key0,
                        "Later table (10469) should beat earlier table (12.5)")
        self.assertEqual(cost_fields[1].value, 10469.0)


if __name__ == "__main__":
    unittest.main()
