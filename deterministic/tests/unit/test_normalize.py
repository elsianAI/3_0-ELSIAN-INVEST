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


if __name__ == "__main__":
    unittest.main()
