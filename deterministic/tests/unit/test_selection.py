"""Tests for deterministic selection / collision resolution."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from deterministic.src.pipeline import DeterministicPipeline


class TestSelectionSortKey(unittest.TestCase):
    """Test the hierarchical comparator sort key."""

    def setUp(self):
        config_dir = str(Path(__file__).parent.parent.parent / "config")
        self.pipeline = DeterministicPipeline(config_dir=config_dir)
        # Force reload of selection rules (class-level cache)
        DeterministicPipeline._SELECTION_RULES = None

    def test_primary_filing_beats_8k(self):
        """10-K filing should beat 8-K for FY period."""
        key_10k = DeterministicPipeline.compute_sort_key(
            period_key="FY2022",
            filing_type="10-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_003_10-K_FY2022.clean.md",
            source_location="table:balance_sheet:row10:col2",
        )
        key_8k = DeterministicPipeline.compute_sort_key(
            period_key="FY2022",
            filing_type="8-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_028_8-K_2023-10-24.clean.md",
            source_location="table:balance_sheet:row10:col2",
        )
        self.assertLess(key_10k, key_8k)

    def test_table_beats_narrative(self):
        """Table source should beat narrative source."""
        key_table = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row5:col2",
        )
        key_narrative = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="narrative",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="narrative:char100",
        )
        self.assertLess(key_table, key_narrative)

    def test_higher_semantic_rank_wins(self):
        """Higher label_priority + section_bonus should win (lower sort key)."""
        key_high = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=100,
            section_bonus=5,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row5:col2",
        )
        key_low = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=-5,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:note_section:row5:col2",
        )
        self.assertLess(key_high, key_low)

    def test_stable_tiebreaker_by_filing_order(self):
        """Same everything except filing name: lower SRC wins."""
        key_src1 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row5:col2",
        )
        key_src2 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_002_10-K_FY2023.clean.md",
            source_location="table:income_statement:row5:col2",
        )
        self.assertLess(key_src1, key_src2)

    def test_stable_tiebreaker_by_row_descending(self):
        """Same filing, different rows: HIGHER row wins (totals at bottom)."""
        key_row3 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row3:col2",
        )
        key_row10 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row10:col2",
        )
        # row10 should win (lower sort key) because row descending by default
        self.assertLess(key_row10, key_row3)

    def test_stable_tiebreaker_by_col(self):
        """Same filing+row, different cols: lower col wins."""
        key_col0 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row5:col0",
        )
        key_col4 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=50,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row5:col4",
        )
        self.assertLess(key_col0, key_col4)

    def test_consolidated_beats_segment_via_primary_section(self):
        """Primary IS section should beat deprioritized section for ebit."""
        key_consolidated = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=100,
            section_bonus=5,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:consolidated_statements_of_operations:row12:col2",
        )
        key_segment = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=100,
            section_bonus=-5,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:loss_from_operations:row6:col2",
        )
        self.assertLess(key_consolidated, key_segment)

    def test_note_section_loses_to_main_for_income_tax(self):
        """A field from a primary section beats a note section."""
        key_main = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=100,
            section_bonus=5,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row15:col2",
        )
        key_note = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=100,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:note_income_taxes:row5:col2",
        )
        self.assertLess(key_main, key_note)

    def test_later_row_wins_over_percentage_row(self):
        """Regression guard: row 15 (total) should beat row 3 (detail/pct)."""
        key_pct = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row3:col2",
        )
        key_total = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:row15:col2",
        )
        # Total row (15) wins over detail row (3) with descending row order
        self.assertLess(key_total, key_pct)

    def test_section_bonus_reads_config(self):
        """_section_bonus should use values from selection_rules.json."""
        config_dir = str(Path(__file__).parent.parent.parent / "config")
        rules = DeterministicPipeline._load_selection_rules(config_dir)
        bonus = DeterministicPipeline._section_bonus(
            "table:consolidated_statements_of_operations:row5", rules
        )
        penalty = DeterministicPipeline._section_bonus(
            "table:loss_from_operations:row5", rules
        )
        neutral = DeterministicPipeline._section_bonus(
            "table:balance_sheet:row5", rules
        )
        self.assertEqual(bonus, rules.get("section_weights", {}).get("primary_is_bonus", 5))
        self.assertEqual(penalty, rules.get("section_weights", {}).get("deprioritized_penalty", -5))
        self.assertEqual(neutral, 0)

    def test_later_table_wins_over_earlier_table(self):
        """Regression guard: tbl1 (later table) should beat tbl0 (earlier table)
        when everything else is identical.

        Reproduces exact scenario: cost_of_revenue has 12.5 in tbl0 (percentage
        table) and 10469 in tbl1 (monetary table). Without table_idx, both would
        have identical sort keys and the first (wrong) value wins.
        """
        key_tbl0 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:tbl0:row5:col2",
        )
        key_tbl1 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:tbl1:row5:col2",
        )
        # Keys must be different (table index breaks the tie)
        self.assertNotEqual(key_tbl0, key_tbl1)
        # Later table (tbl1) should win → lower sort key
        self.assertLess(key_tbl1, key_tbl0)

    def test_collision_later_table_replaces_earlier(self):
        """Integration: simulate collision resolution where two candidates from
        different tables in the same section compete. The later table's value
        (10469) must replace the earlier table's value (12.5).

        This does NOT use abs(value) — resolution is purely positional.
        """
        from deterministic.src.schemas import FieldResult

        rules = None  # Use defaults

        # Simulate first candidate arriving (tbl0, percentage value 12.5)
        sort_key_tbl0 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:tbl0:row5:col2",
            rules=rules,
        )
        fr_tbl0 = FieldResult(
            value=12.5,
            scale="units",
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:tbl0:row5:col2",
            confidence="medium",
        )
        fr_tbl0._sort_key = sort_key_tbl0  # type: ignore[attr-defined]

        # Simulate second candidate arriving (tbl1, monetary value 10469)
        sort_key_tbl1 = DeterministicPipeline.compute_sort_key(
            period_key="FY2024",
            filing_type="10-K",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_001_10-K_FY2024.clean.md",
            source_location="table:income_statement:tbl1:row5:col2",
            rules=rules,
        )

        # Apply the same collision logic as pipeline.extract():
        # if new_sort_key >= old_sort_key → discard new
        old_sort_key = fr_tbl0._sort_key  # type: ignore[attr-defined]
        should_discard = sort_key_tbl1 >= old_sort_key

        # The later table (10469) should NOT be discarded — it should replace
        self.assertFalse(should_discard,
                         "Later table candidate (10469) was wrongly discarded; "
                         "table_idx should break the tie in favor of later tables")


class TestSelectionRulesConfig(unittest.TestCase):
    """Test that selection_rules.json loads correctly."""

    def test_config_loads(self):
        """selection_rules.json should be valid JSON with required keys."""
        config_path = Path(__file__).parent.parent.parent / "config" / "selection_rules.json"
        self.assertTrue(config_path.exists(), f"Missing {config_path}")
        data = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("filing_priority_by_period", data)
        self.assertIn("source_type_priority", data)
        self.assertIn("section_weights", data)
        self.assertIn("stable_tiebreaker", data)

    def test_filing_priority_covers_all_period_types(self):
        """FY, Q, H should all have filing priority lists."""
        config_path = Path(__file__).parent.parent.parent / "config" / "selection_rules.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        priorities = data["filing_priority_by_period"]
        for key in ("FY", "Q", "H"):
            self.assertIn(key, priorities)
            self.assertIsInstance(priorities[key], list)
            self.assertGreater(len(priorities[key]), 0)


class TestPeriodAffinity(unittest.TestCase):
    """Test the period-filing affinity logic."""

    def test_q_primary_beats_q_comparative(self):
        """For Q1-2024, the primary 10-Q (SRC_012_10-Q_Q1-2024) should beat
        a comparative column in SRC_009_10-Q_Q1-2025."""
        key_primary = DeterministicPipeline.compute_sort_key(
            period_key="Q1-2024",
            filing_type="10-Q",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_012_10-Q_Q1-2024.clean.md",
            source_location="table:income_statement:row10:col2",
        )
        key_comparative = DeterministicPipeline.compute_sort_key(
            period_key="Q1-2024",
            filing_type="10-Q",
            source_type="table",
            label_priority=0,
            section_bonus=0,
            source_filing="SRC_009_10-Q_Q1-2025.clean.md",
            source_location="table:income_statement:row10:col2",
        )
        self.assertLess(key_primary, key_comparative,
                        "Primary filing should have lower sort key than comparative")

    def test_fy_no_affinity_discrimination(self):
        """For FY periods, affinity should be 0 for both filings
        (preserves restatement handling)."""
        self.assertEqual(
            DeterministicPipeline._period_affinity("FY2023", "SRC_001_10-K_FY2024.clean.md"),
            0,
        )
        self.assertEqual(
            DeterministicPipeline._period_affinity("FY2023", "SRC_002_10-K_FY2023.clean.md"),
            0,
        )

    def test_q_affinity_primary(self):
        """A filing whose name contains the period_key has affinity 0."""
        self.assertEqual(
            DeterministicPipeline._period_affinity("Q1-2024", "SRC_012_10-Q_Q1-2024.clean.md"),
            0,
        )

    def test_q_affinity_comparative(self):
        """A filing whose name does NOT contain the period_key has affinity 1."""
        self.assertEqual(
            DeterministicPipeline._period_affinity("Q1-2024", "SRC_009_10-Q_Q1-2025.clean.md"),
            1,
        )


class TestMergePeriodAffinity(unittest.TestCase):
    """Test that merge_extractions respects period affinity for same-type filings."""

    def test_primary_filing_wins_same_type_merge(self):
        """For Q1-2024, the primary filing's value should survive merge
        even when a comparative filing was inserted first."""
        from deterministic.src.merge import merge_extractions
        from deterministic.src.schemas import FieldResult

        # Comparative: SRC_009 has Q1-2024 income_tax = 5730 (wrong)
        fr_comp = FieldResult(value=5730, scale="raw",
                              source_filing="SRC_009_10-Q_Q1-2025.clean.md",
                              source_location="tbl2:row10:col2")
        fr_comp._sort_key = (2, 1, 0, 0, ("SRC_009_10-Q_Q1-2025.clean.md", -2, -10, 2))

        # Primary: SRC_012 has Q1-2024 income_tax = 1505 (correct)
        fr_primary = FieldResult(value=1505, scale="raw",
                                 source_filing="SRC_012_10-Q_Q1-2024.clean.md",
                                 source_location="tbl2:row12:col1")
        fr_primary._sort_key = (2, 0, 0, 0, ("SRC_012_10-Q_Q1-2024.clean.md", -2, -12, 1))

        filing_extractions = [
            ("10-Q", "SRC_009_10-Q_Q1-2025.clean.md", {"Q1-2024": {"income_tax": fr_comp}}),
            ("10-Q", "SRC_012_10-Q_Q1-2024.clean.md", {"Q1-2024": {"income_tax": fr_primary}}),
        ]
        result = merge_extractions(filing_extractions, ticker="TEST")
        actual = result.periods["Q1-2024"].fields["income_tax"].value
        self.assertEqual(actual, 1505, "Primary filing value should win over comparative")

    def test_fy_first_seen_preserved(self):
        """For FY periods with same affinity (both 0), first-seen-wins is preserved."""
        from deterministic.src.merge import merge_extractions
        from deterministic.src.schemas import FieldResult

        # SRC_005 (restated FY2019 from FY2020 10-K) — first seen
        fr_first = FieldResult(value=11236, scale="raw",
                               source_filing="SRC_005_10-K_FY2020.clean.md",
                               source_location="tbl3:row8:col2")
        fr_first._sort_key = (1, 0, 0, 0, ("SRC_005_10-K_FY2020.clean.md", -3, -8, 2))

        # SRC_006 (original FY2019) — second seen
        fr_second = FieldResult(value=5625, scale="raw",
                                source_filing="SRC_006_10-K_FY2019.clean.md",
                                source_location="tbl3:row8:col2")
        fr_second._sort_key = (1, 0, 0, 0, ("SRC_006_10-K_FY2019.clean.md", -3, -8, 2))

        filing_extractions = [
            ("10-K", "SRC_005_10-K_FY2020.clean.md", {"FY2019": {"cfo": fr_first}}),
            ("10-K", "SRC_006_10-K_FY2019.clean.md", {"FY2019": {"cfo": fr_second}}),
        ]
        result = merge_extractions(filing_extractions, ticker="TEST")
        actual = result.periods["FY2019"].fields["cfo"].value
        self.assertEqual(actual, 11236, "First-seen should win for FY (restatement preserved)")


if __name__ == "__main__":
    unittest.main()
