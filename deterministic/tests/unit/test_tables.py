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

    def test_total_liabilities_and_equity_row_extracted(self):
        """'Total liabilities and stockholders' equity' row must be extracted.

        This label maps to total_assets via the alias resolver (balance sheet
        identity: total L+E = total A).  Rejection is handled by the alias
        resolver's reject patterns for total_liabilities, not at table level."""
        table = """| | 2024 | 2023 |
| --- | --- | --- |
| Total liabilities | 50,369 | 46,499 |
| Total liabilities and stockholders' equity | 54,722 | 55,382 |"""

        fields = extract_from_markdown_table(table, "balance_sheet")
        labels = [f.label for f in fields]
        self.assertIn("Total liabilities", labels)
        self.assertIn("Total liabilities and stockholders' equity", labels)

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


class TestMultiHeaderSubheader(unittest.TestCase):
    """Tests for multi-row sub-header merging in 10-Q tables."""

    def test_date_fragment_subheader_detected(self):
        """'September 30,' row should be detected as sub-header."""
        from deterministic.src.extract.tables import _is_subheader_row
        cells = ["", "September 30,", "", "December 31,", "", "", "", ""]
        self.assertTrue(_is_subheader_row(cells))

    def test_period_indicator_subheader_detected(self):
        """'Three Months Ended' row should be detected as sub-header."""
        from deterministic.src.extract.tables import _is_subheader_row
        cells = ["", "Three Months Ended", "", "Nine Months Ended", ""]
        self.assertTrue(_is_subheader_row(cells))

    def test_data_row_not_subheader(self):
        """Normal data row with label in first cell is NOT a sub-header."""
        from deterministic.src.extract.tables import _is_subheader_row
        cells = ["Revenue", "22198", "", "", "20098", ""]
        self.assertFalse(_is_subheader_row(cells))

    def test_three_row_header_merging(self):
        """10-Q income statement: Three/Nine Months Ended + date + year."""
        table = (
            "|  | Three Months Ended |  | Nine Months Ended |\n"
            "| --- | --- | --- | --- |\n"
            "|  | September 30, |  | September 30, |\n"
            "|  | 2025 |  | 2024 |\n"
            "| Revenue | 22198 |  | 63224 |\n"
        )
        fields = extract_from_markdown_table(table, "income_statement", 0)
        periods = {f.column_header for f in fields}
        self.assertIn("Q3-2025", periods,
                       "Three Months Ended Sep 30 + 2025 → Q3-2025")

    def test_balance_sheet_quarter_date(self):
        """Sep 30 standalone date → Q3, Dec 31 → FY."""
        table = (
            "|  | September 30, 2025 |  | December 31, 2024 |\n"
            "| --- | --- | --- | --- |\n"
            "| Total assets | 46164 |  | 54722 |\n"
        )
        fields = extract_from_markdown_table(table, "balance_sheet", 0)
        headers = {f.column_header for f in fields}
        self.assertIn("Q3-2025", headers, "Sep 30 date → Q3")
        self.assertIn("FY2024", headers, "Dec 31 date → FY")

    def test_nine_months_ended_maps_to_9M(self):
        """Nine Months Ended should produce 9M- prefix, not Q."""
        from deterministic.src.extract.tables import _identify_period_columns
        headers = ["", "Nine Months Ended September 30, 2025"]
        pm = _identify_period_columns(headers)
        self.assertEqual(pm.get(1), "9M-2025")


class TestDateToPeriod(unittest.TestCase):
    """Tests for _date_to_period mapping."""

    def test_december_31_is_FY(self):
        from deterministic.src.extract.tables import _date_to_period
        self.assertEqual(_date_to_period(12, "2024"), "FY2024")

    def test_september_30_is_Q3(self):
        from deterministic.src.extract.tables import _date_to_period
        self.assertEqual(_date_to_period(9, "2025"), "Q3-2025")

    def test_march_31_is_Q1(self):
        from deterministic.src.extract.tables import _date_to_period
        self.assertEqual(_date_to_period(3, "2023"), "Q1-2023")

    def test_june_30_is_Q2(self):
        from deterministic.src.extract.tables import _date_to_period
        self.assertEqual(_date_to_period(6, "2024"), "Q2-2024")


class TestPercentageTableFilter(unittest.TestCase):
    """Percentage/margin tables should be skipped entirely."""

    def test_percentage_table_skipped(self):
        """Table with ≥2 rows having standalone '%' cells is skipped."""
        table = (
            "|  | 2025 | | 2024 |\n"
            "| --- | --- | --- | --- |\n"
            "| Revenue | 100.0 | % | 100.0 |\n"
            "| Cost | 20.4 |  | 12.7 |\n"
            "| Net income | 0.8 | % | 16.2 |\n"
        )
        fields = extract_from_markdown_table(table, "income_statement", 0)
        self.assertEqual(len(fields), 0,
                         "Percentage table should produce zero fields")

    def test_monetary_table_not_skipped(self):
        """Table with $ values and no standalone '%' cells is NOT skipped."""
        table = (
            "|  | 2025 | | 2024 |\n"
            "| --- | --- | --- | --- |\n"
            "| Revenue | $ | 22198 | $ |\n"
            "| Cost | 4519 |  | 2548 |\n"
        )
        fields = extract_from_markdown_table(table, "income_statement", 0)
        self.assertGreater(len(fields), 0,
                           "Monetary table should produce fields")

    def test_split_paren_third_column(self):
        """3-period table with split-paren negatives extracts ALL 3 columns.

        Regression test: when a period header lands on a ')' cell from a
        split-paren negative, the sparse-column scan must still activate
        to find the real value in a subsequent cell.
        """
        table = (
            "|  |  | 2025 |  |  | 2024 |  |  | 2023 |  |  |  |  |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- "
            "| --- | --- | --- | --- |\n"
            "| SGA |  |  | ( 285.1 | ) |  |  | ( 305.3 | ) |  "
            "|  | ( 380.5 | ) |\n"
        )
        fields = extract_from_markdown_table(table, "income_statement", 0)
        by_period = {f.column_header: f.value for f in fields if f.label == "SGA"}
        self.assertAlmostEqual(by_period.get("FY2025"), -285.1)
        self.assertAlmostEqual(by_period.get("FY2024"), -305.3)
        self.assertAlmostEqual(by_period.get("FY2023"), -380.5,
                               msg="3rd column with split-paren must be extracted")


class TestAbbreviatedMonthPeriods(unittest.TestCase):
    """Abbreviated months (Sep., Dec., Sept.) in headers."""

    def test_three_months_ended_sep_dot(self):
        """'Three Months Ended Sep. 30, 2025' → Q3-2025."""
        from deterministic.src.extract.tables import _identify_period_columns
        headers = ["", "Three Months Ended Sep. 30, 2025"]
        pm = _identify_period_columns(headers)
        self.assertEqual(pm.get(1), "Q3-2025")

    def test_standalone_dec_dot_annual_context(self):
        """'Dec. 31, 2024' in annual filing → FY2024."""
        from deterministic.src.extract.tables import _identify_period_columns
        headers = ["", "Dec. 31, 2024"]
        pm = _identify_period_columns(headers, filing_type="10-K")
        self.assertEqual(pm.get(1), "FY2024")

    def test_sept_dot_recognized(self):
        """'Sept. 30, 2025' → Q3-2025."""
        from deterministic.src.extract.tables import _identify_period_columns
        headers = ["", "Sept. 30, 2025"]
        pm = _identify_period_columns(headers)
        self.assertEqual(pm.get(1), "Q3-2025")

    def test_abbreviated_month_subheader_detected(self):
        """Sub-header row with abbreviated month is detected."""
        from deterministic.src.extract.tables import _is_subheader_row
        cells = ["", "Sep. 30,", "", "Dec. 31,"]
        self.assertTrue(
            _is_subheader_row(cells),
            "Abbreviated month sub-header should be detected",
        )

    def test_markdown_table_with_abbreviated_months(self):
        """Full markdown table with abbreviated month headers."""
        table = (
            "|  | Sep. 30, 2025 |  | Dec. 31, 2024 |\n"
            "| --- | --- | --- | --- |\n"
            "| Total assets | 46164 |  | 54722 |\n"
        )
        fields = extract_from_markdown_table(table, "balance_sheet", 0)
        headers = {f.column_header for f in fields}
        self.assertIn("Q3-2025", headers, "Sep. 30 → Q3")
        self.assertIn("FY2024", headers, "Dec. 31 → FY")


class TestNumericAnchorCalibration(unittest.TestCase):
    """Numeric-anchor calibration for sparse-header tables.

    EDGAR tables where header years sit at columns [1,3,5] but actual
    data sits at [2,5,8] require recalibrating period_map so that the
    sparse-column scan doesn't mis-assign values across periods.
    """

    def test_sparse_header_with_shifted_data(self):
        """Headers at cols [1,3,5], data at [2,5,8] — must recalibrate.

        Without calibration, col5 (FY2023 by header) picks up FY2024's
        value (1,973,568).  With calibration, FY2023 correctly gets col8.
        """
        table = (
            "|  | 2025 |  | 2024 |  | 2023 |  |  |  |  |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| Revenue |  | 1,780,070 |  |  | 1,973,568 |  |  | 1,457,886 |  |\n"
            "| SGA |  | 155,368 |  |  | 201,517 |  |  | 158,493 |  |\n"
            "| DD&A |  | 1,056,281 |  |  | 1,023,558 |  |  | 663,534 |  |\n"
            "| Accretion |  | 125,296 |  |  | 117,604 |  |  | 86,152 |  |\n"
        )
        fields = extract_from_markdown_table(table, "income_statement", 0)
        by_period = {}
        for f in fields:
            if f.label == "Revenue":
                by_period[f.column_header] = f.value
        self.assertAlmostEqual(by_period.get("FY2025"), 1780070.0)
        self.assertAlmostEqual(by_period.get("FY2024"), 1973568.0)
        self.assertAlmostEqual(
            by_period.get("FY2023"), 1457886.0,
            msg="FY2023 must get col8 value, not col5 (FY2024's data)"
        )

    def test_no_calibration_when_data_between_headers(self):
        """Headers at [1,3,5], data at [1,4,7] — scan handles this fine.

        When numeric columns don't cross into the next header col
        (col4 < col5), the sparse scan finds the value correctly.
        Recalibration should NOT fire.
        """
        table = (
            "|  | 2025 |  | 2024 |  | 2023 |  |  |  |  |  |  |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| Revenue | 300,666 |  |  | 285,236 |  |  | 188,633 |  |  |  |  |\n"
            "| SGA | 46,559 |  |  | 73,944 |  |  | 30,008 |  |  |  |  |\n"
            "| R&D | 10,832 |  |  | 9,791 |  |  | 3,925 |  |  |  |  |\n"
            "| OpExp | 155,690 |  |  | 154,614 |  |  | 78,555 |  |  |  |  |\n"
        )
        fields = extract_from_markdown_table(table, "income_statement", 0)
        by_period = {}
        for f in fields:
            if f.label == "Revenue":
                by_period[f.column_header] = f.value
        self.assertAlmostEqual(by_period.get("FY2025"), 300666.0)
        self.assertAlmostEqual(by_period.get("FY2024"), 285236.0)
        self.assertAlmostEqual(by_period.get("FY2023"), 188633.0)

    def test_mixed_layout_rows_no_calibration(self):
        """Table with mixed column layouts — calibration must not fire.

        Some rows have data at (1,3,5) and others at (1,4,7).  The
        majority pattern (1,4,7) doesn't cross headers, so no
        calibration should occur.  Row at (1,3,5) still works via
        direct header match.
        """
        table = (
            "|  | 2025 |  | 2024 |  | 2023 |  |  |  |  |  |  |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| DD&A | 8,332 |  | 8,524 |  | 2,873 |  |  |  |  |  |  |\n"
            "| SBC | 4,951 |  | 16,825 |  | 2,503 |  |  |  |  |  |  |\n"
            "| AR | 5,765 |  |  | 234 |  |  | 5,058 |  |  |  |  |\n"
            "| Inv | 11,517 |  |  | 46,875 |  |  | 16,514 |  |  |  |  |\n"
            "| AP | 52,906 |  |  | 38,188 |  |  | 46,258 |  |  |  |  |\n"
        )
        fields = extract_from_markdown_table(table, "cash_flow", 0)
        by_period = {}
        for f in fields:
            if f.label == "DD&A":
                by_period[f.column_header] = f.value
        self.assertAlmostEqual(by_period.get("FY2025"), 8332.0)
        self.assertAlmostEqual(
            by_period.get("FY2024"), 8524.0,
            msg="DD&A at col3 must map to FY2024 (header col3), "
            "not be shifted by majority-pattern calibration"
        )
        self.assertAlmostEqual(by_period.get("FY2023"), 2873.0)


if __name__ == "__main__":
    unittest.main()
