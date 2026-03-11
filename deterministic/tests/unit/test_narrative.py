"""Tests for deterministic.src.extract.narrative"""

import unittest
from pathlib import Path

from deterministic.src.extract.narrative import (
    extract_from_narrative,
    extract_comparatives,
)


class TestExtractFromNarrative(unittest.TestCase):
    def test_revenue_amounted_to(self):
        text = "Revenue amounted to $185.2 million"
        fields = extract_from_narrative(text)
        self.assertTrue(len(fields) >= 1)
        rev = [f for f in fields if "revenue" in f.label.lower()]
        self.assertTrue(len(rev) >= 1)
        self.assertAlmostEqual(rev[0].value, 185.2, places=1)
        self.assertEqual(rev[0].scale, "millions")

    def test_eur_revenue(self):
        text = "Revenue amounted to EUR10,280 million"
        fields = extract_from_narrative(text)
        rev = [f for f in fields if "revenue" in f.label.lower()]
        self.assertTrue(len(rev) >= 1)

    def test_net_income_of(self):
        text = "Net income of $523 million"
        fields = extract_from_narrative(text)
        ni = [f for f in fields if "net income" in f.label.lower() or "income" in f.label.lower()]
        self.assertTrue(len(ni) >= 1)

    def test_operating_income_reached(self):
        text = "Operating income reached $34,400 thousand"
        fields = extract_from_narrative(text)
        self.assertTrue(len(fields) >= 1)

    def test_ebitda(self):
        text = "EBITDA was €1,500 million for FY2024"
        fields = extract_from_narrative(text)
        self.assertTrue(len(fields) >= 1)


class TestExtractComparatives(unittest.TestCase):
    def test_versus_pattern(self):
        text = "Revenue of $185M versus $162M in 2023"
        comps = extract_comparatives(text, context_label="revenue")
        self.assertTrue(len(comps) >= 1)
        self.assertAlmostEqual(comps[0].value, 162.0, places=0)
        self.assertIn("2023", comps[0].period_hint)

    def test_compared_to(self):
        text = "Operating income compared to €998 million in FY2023"
        comps = extract_comparatives(text, context_label="ebit")
        self.assertTrue(len(comps) >= 1)


class TestNarrativeFixture(unittest.TestCase):
    def test_eu_sample(self):
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "narrative_eu_sample.txt"
        )
        if not fixture_path.exists():
            self.skipTest("Fixture file not found")

        text = fixture_path.read_text(encoding="utf-8")
        fields = extract_from_narrative(text)
        # Should find at least revenue and some other fields
        labels = [f.label.lower() for f in fields]
        self.assertTrue(
            any("revenue" in l for l in labels),
            f"Expected revenue in labels: {labels}",
        )

    # ── Iteration 6: context-rejection tests ───────────────────────

    def test_non_gaap_context_blocked(self):
        """Narrative preceded by 'Non-GAAP' should be suppressed."""
        text = (
            "On a Non-GAAP basis, operating income was $12.5 million "
            "for the quarter."
        )
        fields = extract_from_narrative(text)
        oi = [f for f in fields if "operating" in f.label.lower()]
        self.assertEqual(len(oi), 0, f"Non-GAAP match should be blocked: {oi}")

    def test_comparative_context_blocked(self):
        """Values appearing after 'compared to' should not be extracted
        as primary narrative fields."""
        text = (
            "Operating profit was $1.1 million, "
            "compared to operating profit of $3.2 million in Q3 2024."
        )
        fields = extract_from_narrative(text)
        # Should extract the primary value (1.1) but NOT the comparative (3.2)
        oi = [f for f in fields if "operating" in f.label.lower()
              or "profit" in f.label.lower()]
        values = [f.value for f in oi]
        self.assertIn(1.1, values, "Primary value 1.1 should be extracted")
        self.assertNotIn(3.2, values, "Comparative value 3.2 should be blocked")


if __name__ == "__main__":
    unittest.main()
