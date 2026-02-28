"""Tests for deterministic.src.normalize.aliases"""

import unittest

from deterministic.src.normalize.aliases import AliasResolver


class TestAliasResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = AliasResolver()

    def test_exact_canonical(self):
        self.assertEqual(self.resolver.resolve("ingresos"), "ingresos")

    def test_alias_revenue(self):
        self.assertEqual(self.resolver.resolve("revenue"), "ingresos")

    def test_alias_net_revenue(self):
        self.assertEqual(self.resolver.resolve("net revenue"), "ingresos")

    def test_alias_total_revenues(self):
        self.assertEqual(self.resolver.resolve("total revenues"), "ingresos")

    def test_alias_ebit(self):
        self.assertEqual(self.resolver.resolve("operating income"), "ebit")

    def test_alias_net_income(self):
        self.assertEqual(self.resolver.resolve("net income"), "net_income")

    def test_alias_cash_flow(self):
        result = self.resolver.resolve("net cash from operating activities")
        self.assertEqual(result, "cfo")

    def test_alias_capex(self):
        result = self.resolver.resolve("capital expenditures")
        self.assertEqual(result, "capex")

    def test_alias_french(self):
        result = self.resolver.resolve("chiffre d'affaires")
        self.assertEqual(result, "ingresos")

    def test_unknown_returns_none(self):
        self.assertIsNone(self.resolver.resolve("xyzzy_not_a_field"))

    def test_case_insensitive(self):
        self.assertEqual(self.resolver.resolve("REVENUE"), "ingresos")
        self.assertEqual(self.resolver.resolve("Net Income"), "net_income")

    def test_get_all_canonical_names(self):
        names = self.resolver.get_all_canonical_names()
        self.assertIn("ingresos", names)
        self.assertIn("ebit", names)
        self.assertIn("net_income", names)
        self.assertTrue(len(names) > 10)

    def test_deferred_revenue_not_matched(self):
        """'deferred revenue' must NOT resolve to 'ingresos' via fuzzy 'revenue'."""
        self.assertIsNone(self.resolver.resolve("deferred revenue"))

    def test_net_income_attributable_to_travelzoo(self):
        """Long label containing 'net income' should still resolve via multi-word fuzzy."""
        result = self.resolver.resolve("Net income attributable to Travelzoo")
        self.assertEqual(result, "net_income")

    def test_merchant_payables_not_matched(self):
        """'merchant payables' should NOT match any canonical field."""
        self.assertIsNone(self.resolver.resolve("merchant payables"))

    def test_deferred_tax_assets_not_matched(self):
        """'deferred tax assets' should NOT match 'total_assets'."""
        self.assertIsNone(self.resolver.resolve("deferred tax assets"))

    # ── Iteration 4: disambiguation rules ──────────────────────────

    def test_net_income_rejects_per_share(self):
        """'Net income per share—diluted' must NOT resolve to net_income."""
        self.assertNotEqual(
            self.resolver.resolve("Net income per share—diluted"), "net_income"
        )

    def test_net_income_rejects_basic_eps(self):
        self.assertNotEqual(
            self.resolver.resolve("Net income per share—basic"), "net_income"
        )

    def test_shares_outstanding_matches_shares_used(self):
        """'Shares used in per share calculation from continuing operations—basic'."""
        result = self.resolver.resolve(
            "Shares used in per share calculation from continuing operations—basic"
        )
        self.assertEqual(result, "shares_outstanding")

    def test_shares_outstanding_matches_weighted_avg(self):
        result = self.resolver.resolve("Weighted average common shares—basic")
        self.assertEqual(result, "shares_outstanding")

    def test_shares_outstanding_rejects_common_stock_par(self):
        """'Common stock, $0.01 par value ...' must NOT resolve to shares_outstanding."""
        label = (
            "Common stock, $ 0.01 par value ( 20,000 shares authorized "
            "as of December 31, 2024 and 2023, respectively; 11,836 shares "
            "issued and outstanding as of December 31, 2024 and 13,575 "
            "shares issued and outstanding as of December 31, 2023)"
        )
        result = self.resolver.resolve(label)
        self.assertNotEqual(result, "shares_outstanding")

    def test_income_tax_rejects_prepaid(self):
        """'Prepaid income taxes' must NOT resolve to income_tax."""
        self.assertNotEqual(
            self.resolver.resolve("Prepaid income taxes"), "income_tax"
        )

    def test_income_tax_rejects_payable(self):
        self.assertNotEqual(
            self.resolver.resolve("Income tax payable"), "income_tax"
        )

    def test_income_tax_rejects_cash_paid_refund(self):
        self.assertNotEqual(
            self.resolver.resolve("Cash paid (refund) for income taxes, net"),
            "income_tax",
        )

    def test_income_tax_matches_expense(self):
        self.assertEqual(
            self.resolver.resolve("Income tax expense"), "income_tax"
        )

    def test_income_tax_matches_provision(self):
        self.assertEqual(
            self.resolver.resolve("Provision for income taxes"), "income_tax"
        )

    def test_cash_and_equivalents_rejects_restricted(self):
        """'Cash, cash equivalents and restricted cash' must NOT resolve to cash_and_equivalents."""
        self.assertNotEqual(
            self.resolver.resolve("Cash, cash equivalents and restricted cash"),
            "cash_and_equivalents",
        )

    def test_cash_and_equivalents_matches_exact(self):
        self.assertEqual(
            self.resolver.resolve("Cash and cash equivalents"),
            "cash_and_equivalents",
        )

    def test_total_liabilities_rejects_and_equity(self):
        self.assertNotEqual(
            self.resolver.resolve("Total liabilities and stockholders' equity"),
            "total_liabilities",
        )

    def test_total_liabilities_matches_pure(self):
        self.assertEqual(
            self.resolver.resolve("Total liabilities"), "total_liabilities"
        )

    def test_eps_diluted_matches_net_income_per_share_diluted(self):
        result = self.resolver.resolve("Net income per share —diluted")
        self.assertEqual(result, "eps_diluted")

    def test_eps_basic_matches_net_income_per_share_basic(self):
        result = self.resolver.resolve("Net income per share—basic")
        self.assertEqual(result, "eps_basic")

    def test_label_priority_exact(self):
        """Priority score for exact match on cash_and_equivalents."""
        score = self.resolver.label_priority(
            "cash_and_equivalents", "Cash and cash equivalents"
        )
        self.assertGreater(score, 0)

    def test_label_priority_default(self):
        score = self.resolver.label_priority("ingresos", "Revenue")
        self.assertEqual(score, 0)

    # ── Iteration 6: Phase B disambiguation tests ──────────────────

    def test_net_income_rejects_before_income_tax(self):
        """'Income before income taxes' must NOT resolve to net_income."""
        result = self.resolver.resolve("Income before income taxes")
        self.assertNotEqual(result, "net_income")

    def test_ebit_prefers_operating_income(self):
        """'Operating income' should get a higher priority score than
        'Income from operations' for the ebit canonical field."""
        score_oi = self.resolver.label_priority("ebit", "Operating income")
        score_ifo = self.resolver.label_priority("ebit", "Income from operations")
        self.assertGreater(score_oi, score_ifo)

    def test_net_income_prefers_exact_over_qualified(self):
        """Exact 'Net income' should score higher than
        'Net income attributable to Travelzoo' for net_income."""
        score_exact = self.resolver.label_priority("net_income", "Net income")
        score_qualified = self.resolver.label_priority(
            "net_income", "Net income attributable to Travelzoo"
        )
        self.assertGreater(score_exact, score_qualified)

    # ── Iteration 9: discontinued operations & NCI equity tests ────

    def test_total_assets_rejects_discontinued_operations(self):
        """'Total assets from discontinued operations' must NOT resolve to total_assets."""
        result = self.resolver.resolve("Total assets from discontinued operations")
        self.assertIsNone(result, "Discontinued ops label should be rejected for total_assets")

    def test_total_liabilities_rejects_discontinued_operations(self):
        """'Total liabilities from discontinued operations' must NOT resolve to total_liabilities."""
        result = self.resolver.resolve("Total liabilities from discontinued operations")
        self.assertIsNone(result, "Discontinued ops label should be rejected for total_liabilities")

    def test_total_equity_rejects_discontinued_operations(self):
        """'Total equity from discontinued operations' must NOT resolve to total_equity."""
        result = self.resolver.resolve("Total equity from discontinued operations")
        self.assertIsNone(result, "Discontinued ops label should be rejected for total_equity")

    def test_total_assets_matches_plain(self):
        """Plain 'Total assets' must still resolve to total_assets."""
        self.assertEqual(self.resolver.resolve("Total assets"), "total_assets")

    # ── Iteration 10: parenthetical qualifier stripping ────────────

    def test_eps_basic_with_loss_qualifier(self):
        """'Net income (loss) per share —basic' → eps_basic after stripping (loss)."""
        result = self.resolver.resolve("Net income (loss) per share —basic")
        self.assertEqual(result, "eps_basic")

    def test_eps_diluted_with_loss_qualifier(self):
        """'Income (loss) per share—diluted' → eps_diluted after stripping (loss)."""
        result = self.resolver.resolve("Income (loss) per share—diluted")
        self.assertEqual(result, "eps_diluted")

    def test_emdash_spacing_normalize(self):
        """'share—basic' and 'share —basic' both normalize consistently."""
        n1 = AliasResolver._normalize("net income per share—basic")
        n2 = AliasResolver._normalize("net income per share —basic")
        self.assertEqual(n1, n2,
                         "Em-dash with/without leading space should normalize the same")

    def test_operating_loss_resolves_to_ebit(self):
        """'Operating loss' should resolve to ebit."""
        self.assertEqual(self.resolver.resolve("Operating loss"), "ebit")

    def test_total_stockholders_deficit_resolves_to_total_equity(self):
        """'Total stockholders' deficit' → total_equity."""
        result = self.resolver.resolve("Total stockholders' deficit")
        self.assertEqual(result, "total_equity")

    def test_income_loss_from_operations_resolves_to_ebit(self):
        """'Income (loss) from operations' → ebit after stripping (loss)."""
        result = self.resolver.resolve("Income (loss) from operations")
        self.assertEqual(result, "ebit")


if __name__ == "__main__":
    unittest.main()
