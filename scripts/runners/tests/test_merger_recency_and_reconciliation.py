"""Tests for V6.2 merge recency tie-break and cross-filing reconciliation.

P0: Verifies that lower index (= more recent filing) wins tie-breaks.
P1: Verifies material discrepancy detection and classification in reconciliation.
"""

import sys, os, json, unittest
from pathlib import Path

# Ensure project root is on sys.path
_proj = Path(__file__).resolve().parents[3]
if str(_proj) not in sys.path:
    sys.path.insert(0, str(_proj))

from scripts.runners.tp_extractor_merger import _merge_period_entries, merge, MAX_PERIODS_PER_FILING
from scripts.runners.tp_validator import _reconcile_cross_filing


# ─────────────────────────────────────────────
# P0: Recency tie-break tests
# ─────────────────────────────────────────────

class RecencyTieBreakTests(unittest.TestCase):
    """The merger uses ext_idx as the recency index.
    Index 0 = most recent filing (router sorts newest first).
    When same priority (tie), lower index should win."""

    def test_lower_index_wins_tiebreak(self):
        """Filing at index 0 (most recent) should beat index 2 (older)."""
        existing = {
            "periodo": "2023",
            "ingresos_usd": 100,
            "_field_sources": {"ingresos_usd": "10-K"},
        }
        new_entry = {
            "periodo": "2023",
            "ingresos_usd": 120,
        }
        # new_recency=0 (most recent), existing_recency=2 (older)
        merged = _merge_period_entries(
            existing, new_entry,
            existing_priority=1, new_priority=1,
            new_source="10-K",
            new_recency=0, existing_recency=2,
        )
        self.assertEqual(merged["ingresos_usd"], 120,
                         "More recent filing (index 0) should win over older (index 2)")
        self.assertIn(":recency", merged["_field_sources"]["ingresos_usd"])

    def test_higher_index_loses_tiebreak(self):
        """Filing at index 3 (older) should NOT beat index 1 (more recent)."""
        existing = {
            "periodo": "2023",
            "ingresos_usd": 100,
            "_field_sources": {"ingresos_usd": "10-K"},
        }
        new_entry = {
            "periodo": "2023",
            "ingresos_usd": 120,
        }
        # new_recency=3 (older), existing_recency=1 (more recent)
        merged = _merge_period_entries(
            existing, new_entry,
            existing_priority=1, new_priority=1,
            new_source="10-K",
            new_recency=3, existing_recency=1,
        )
        self.assertEqual(merged["ingresos_usd"], 100,
                         "Older filing (index 3) should NOT override more recent (index 1)")

    def test_priority_still_trumps_recency(self):
        """Higher priority (lower number) always wins regardless of recency."""
        existing = {
            "periodo": "2023",
            "ingresos_usd": 100,
            "_field_sources": {"ingresos_usd": "10-Q"},
        }
        new_entry = {
            "periodo": "2023",
            "ingresos_usd": 120,
        }
        # new has priority 1 (10-K), existing has priority 2 (10-Q)
        # even though new_recency=5 (older) vs existing_recency=0 (newer)
        merged = _merge_period_entries(
            existing, new_entry,
            existing_priority=2, new_priority=1,
            new_source="10-K",
            new_recency=5, existing_recency=0,
        )
        self.assertEqual(merged["ingresos_usd"], 120,
                         "Priority should trump recency")
        self.assertEqual(merged["_field_sources"]["ingresos_usd"], "10-K")
        self.assertNotIn(":recency", merged["_field_sources"]["ingresos_usd"])

    def test_conflict_recorded_in_merge_conflicts(self):
        """Every conflict (same-tier or different) must be recorded."""
        existing = {
            "periodo": "2023",
            "ingresos_usd": 100,
            "_field_sources": {"ingresos_usd": "10-K"},
        }
        new_entry = {
            "periodo": "2023",
            "ingresos_usd": 120,
        }
        merged = _merge_period_entries(
            existing, new_entry,
            existing_priority=1, new_priority=1,
            new_source="10-K",
            new_recency=0, existing_recency=2,
        )
        conflicts = merged.get("_merge_conflicts", [])
        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c["campo"], "ingresos_usd")
        self.assertEqual(c["valor_kept"], 120)
        self.assertEqual(c["valor_dropped"], 100)
        self.assertEqual(c["reason"], "recency")

    def test_no_conflict_on_null_fill(self):
        """Null-fill should not generate a conflict record."""
        existing = {
            "periodo": "2023",
            "ingresos_usd": None,
            "_field_sources": {},
        }
        new_entry = {
            "periodo": "2023",
            "ingresos_usd": 100,
        }
        merged = _merge_period_entries(
            existing, new_entry,
            existing_priority=1, new_priority=1,
            new_source="10-K",
            new_recency=0, existing_recency=1,
        )
        conflicts = merged.get("_merge_conflicts", [])
        self.assertEqual(len(conflicts), 0,
                         "Null-fill should not be a conflict")
        self.assertEqual(merged["ingresos_usd"], 100)

    def test_source_dropped_correct_on_priority_win(self):
        """When new wins by priority, source_dropped must be the OLD source."""
        existing = {
            "periodo": "2023",
            "ingresos_usd": 100,
            "_field_sources": {"ingresos_usd": "10-Q"},
        }
        new_entry = {
            "periodo": "2023",
            "ingresos_usd": 200,
        }
        merged = _merge_period_entries(
            existing, new_entry,
            existing_priority=2, new_priority=1,
            new_source="10-K",
            new_recency=1, existing_recency=0,
        )
        conflicts = merged.get("_merge_conflicts", [])
        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c["source_kept"], "10-K")
        self.assertEqual(c["source_dropped"], "10-Q",
                         "Dropped source must be the previous source, not the new one")

    def test_source_dropped_correct_on_recency_win(self):
        """When new wins by recency, source_dropped must be the OLD source."""
        existing = {
            "periodo": "2023",
            "ingresos_usd": 100,
            "_field_sources": {"ingresos_usd": "10-K"},
        }
        new_entry = {
            "periodo": "2023",
            "ingresos_usd": 200,
        }
        merged = _merge_period_entries(
            existing, new_entry,
            existing_priority=1, new_priority=1,
            new_source="10-K_v2",
            new_recency=0, existing_recency=2,
        )
        conflicts = merged.get("_merge_conflicts", [])
        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c["source_kept"], "10-K_v2")
        self.assertEqual(c["source_dropped"], "10-K",
                         "Dropped source must be the previous source from provenance")


class RecencyEndToEndMergeTests(unittest.TestCase):
    """End-to-end merge() with multiple filings to verify recency order."""

    def _make_partial(self, filing_type, priority, periodo, ingresos):
        return {
            "filing_type": filing_type,
            "filing_priority": priority,
            "historico_anual": [{
                "periodo": periodo,
                "fecha_fin": f"{periodo}-12-31",
                "tipo_periodo": "anual",
                "moneda_original": "USD",
                "ingresos_usd": ingresos,
            }],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }

    def test_merge_respects_recency_order(self):
        """First partial in list (index 0) = most recent filing.
        With same priority, index 0 should win."""
        partials = [
            self._make_partial("10-K", 1, "2023", 200),  # idx 0 — most recent
            self._make_partial("10-K", 1, "2023", 150),  # idx 1 — older
        ]
        result = merge(partials)
        annual = result.get("historico_anual", [])
        entry_2023 = [e for e in annual if e.get("periodo") == "2023"]
        self.assertEqual(len(entry_2023), 1)
        self.assertEqual(entry_2023[0]["ingresos_usd"], 200,
                         "Index 0 (most recent) should win same-tier merge")


# ─────────────────────────────────────────────
# P1: Reconciliation classification tests
# ─────────────────────────────────────────────

class ReconciliationClassificationTests(unittest.TestCase):
    """Verify _reconcile_cross_filing classifies discrepancies correctly."""

    def _make_tp_with_conflicts(self, conflicts, total_assets=None):
        """Build a minimal TP with _merge_conflicts embedded in an annual entry."""
        tp = {
            "historico_anual": [{
                "periodo": "2023",
                "_merge_conflicts": conflicts,
                "_field_sources": {},
            }],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        if total_assets is not None:
            tp["balance_sheet_ultimo"]["activos_totales_usd"] = total_assets
        return tp

    def test_concordancia_under_1pct(self):
        """diff < 1% → concordancia."""
        conflicts = [{
            "campo": "ingresos_usd",
            "valor_kept": 1000,
            "valor_dropped": 1005,
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "concordancia")
        self.assertLess(log[0]["diff_pct"], 1.0)

    def test_extraction_discrepancy_moderate(self):
        """diff 1%-20% → extraction_discrepancy."""
        conflicts = [{
            "campo": "ingresos_usd",
            "valor_kept": 1000,
            "valor_dropped": 1100,  # ~9.5% diff
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "extraction_discrepancy")

    def test_potential_restatement_both_conditions(self):
        """V6.1: potential_restatement requires diff_pct > 5% AND diff_abs > threshold."""
        # 40% diff AND abs = 20M > 5M threshold → both conditions met
        conflicts = [{
            "campo": "net_income_usd",
            "valor_kept": 50_000_000,
            "valor_dropped": 70_000_000,
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "potential_restatement")

    def test_high_pct_but_low_abs_is_extraction_discrepancy(self):
        """V6.1: high pct alone (without abs > threshold) is NOT restatement."""
        # 40% diff but abs = 500 < 5M threshold → only pct met
        conflicts = [{
            "campo": "net_income_usd",
            "valor_kept": 1000,
            "valor_dropped": 1500,
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "extraction_discrepancy",
                         "High pct without abs > threshold should NOT be restatement")

    def test_potential_restatement_abs_threshold(self):
        """Even moderate pct diff triggers restatement if abs > threshold."""
        # 10% diff but abs = 10M > threshold of 5M (no total_assets)
        conflicts = [{
            "campo": "ingresos_usd",
            "valor_kept": 100_000_000,
            "valor_dropped": 110_000_000,
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "potential_restatement")

    def test_threshold_scales_with_total_assets(self):
        """threshold_abs = max(5M, 0.5% of total_assets)."""
        # total_assets = 10B → threshold = 50M
        # diff = 30M (3%) → below 50M threshold → extraction_discrepancy
        conflicts = [{
            "campo": "ingresos_usd",
            "valor_kept": 1_000_000_000,
            "valor_dropped": 1_030_000_000,
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts, total_assets=10_000_000_000)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "extraction_discrepancy")

    def test_non_numeric_conflicts_skipped(self):
        """String-valued conflicts should not appear in reconciliation log."""
        conflicts = [{
            "campo": "sector",
            "valor_kept": "Technology",
            "valor_dropped": "Tech",
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 0,
                         "Non-numeric conflicts should be skipped")

    def test_quarterly_conflicts_also_processed(self):
        """Conflicts in historico_trimestral should also be reconciled."""
        tp = {
            "historico_anual": [],
            "historico_trimestral": [{
                "periodo": "Q3-2023",
                "_merge_conflicts": [{
                    "campo": "ingresos_usd",
                    "valor_kept": 50_000_000,
                    "valor_dropped": 80_000_000,  # 46% diff, abs=30M > 5M
                    "source_kept": "10-Q",
                    "source_dropped": "10-Q",
                    "reason": "recency",
                }],
                "_field_sources": {},
            }],
            "balance_sheet_ultimo": {},
        }
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["periodo"], "Q3-2023")
        self.assertEqual(log[0]["clasificacion"], "potential_restatement")

    def test_diff_fields_present(self):
        """Log entries should contain diff_abs and diff_pct."""
        conflicts = [{
            "campo": "cfo_usd",
            "valor_kept": 200,
            "valor_dropped": 220,
            "source_kept": "10-K",
            "source_dropped": "10-K",
            "reason": "recency",
        }]
        tp = self._make_tp_with_conflicts(conflicts)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertIn("diff_abs", log[0])
        self.assertIn("diff_pct", log[0])
        self.assertAlmostEqual(log[0]["diff_abs"], 20.0)
        # avg = 210, diff = 20/210*100 ≈ 9.52
        self.assertAlmostEqual(log[0]["diff_pct"], 9.52, places=1)

    def test_empty_conflicts(self):
        """No conflicts → empty reconciliation log."""
        tp = {
            "historico_anual": [{"periodo": "2023", "_merge_conflicts": [], "_field_sources": {}}],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 0)


# ─────────────────────────────────────────────
# Max periods per filing enforcement
# ─────────────────────────────────────────────

class MaxPeriodsPerFilingTests(unittest.TestCase):
    """Verify merger truncates entries when a single filing exceeds the limit."""

    def test_annual_truncated_to_max(self):
        """Filing with 15 annual entries → only 10 most recent kept."""
        entries = [
            {"periodo": str(2000 + i), "fecha_fin": f"{2000+i}-12-31",
             "tipo_periodo": "anual", "moneda_original": "USD",
             "ingresos_usd": (2000 + i) * 100}
            for i in range(15)
        ]
        partial = {
            "filing_type": "10-K",
            "filing_priority": 1,
            "historico_anual": entries,
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        result = merge([partial])
        annual = result.get("historico_anual", [])
        self.assertLessEqual(len(annual), MAX_PERIODS_PER_FILING,
                             f"Should be capped at {MAX_PERIODS_PER_FILING}")
        # Most recent periods should survive
        periodos = [e["periodo"] for e in annual]
        self.assertIn("2014", periodos, "Most recent period should be kept")
        self.assertNotIn("2000", periodos, "Oldest period should be dropped")

    def test_quarterly_truncated_to_max(self):
        """Filing with 15 quarterly entries → only 10 most recent kept."""
        entries = [
            {"periodo": f"Q{(i%4)+1}-{2020 + i//4}", "fecha_fin": f"{2020+i//4}-{(i%4+1)*3:02d}-30",
             "tipo_periodo": "trimestral", "moneda_original": "USD",
             "ingresos_usd": 100 * (i + 1)}
            for i in range(15)
        ]
        partial = {
            "filing_type": "10-Q",
            "filing_priority": 2,
            "historico_anual": [],
            "historico_trimestral": entries,
            "balance_sheet_ultimo": {},
        }
        result = merge([partial])
        quarterly = result.get("historico_trimestral", [])
        self.assertLessEqual(len(quarterly), MAX_PERIODS_PER_FILING)

    def test_under_limit_not_truncated(self):
        """Filing with 5 entries should keep all 5."""
        entries = [
            {"periodo": str(2020 + i), "fecha_fin": f"{2020+i}-12-31",
             "tipo_periodo": "anual", "moneda_original": "USD",
             "ingresos_usd": 100 * (i + 1)}
            for i in range(5)
        ]
        partial = {
            "filing_type": "10-K",
            "filing_priority": 1,
            "historico_anual": entries,
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        result = merge([partial])
        annual = result.get("historico_anual", [])
        self.assertEqual(len(annual), 5, "Under-limit should not be truncated")

    def test_constant_is_10(self):
        """Verify the constant matches the plan."""
        self.assertEqual(MAX_PERIODS_PER_FILING, 10)


# ─────────────────────────────────────────────
# Reconciliation threshold fallback
# ─────────────────────────────────────────────

class ReconciliationThresholdFallbackTests(unittest.TestCase):
    """Verify fallback threshold uses 1B proxy when total_assets is null."""

    def _make_tp_with_conflict(self, valor_kept, valor_dropped, total_assets=None):
        tp = {
            "historico_anual": [{
                "periodo": "2023",
                "_merge_conflicts": [{
                    "campo": "ingresos_usd",
                    "valor_kept": valor_kept,
                    "valor_dropped": valor_dropped,
                    "source_kept": "10-K",
                    "source_dropped": "10-K",
                    "reason": "recency",
                }],
                "_field_sources": {},
            }],
            "historico_trimestral": [],
            "balance_sheet_ultimo": {},
        }
        if total_assets is not None:
            tp["balance_sheet_ultimo"]["activos_totales_usd"] = total_assets
        return tp

    def test_fallback_threshold_is_5m(self):
        """Without total_assets, threshold = max(5M, 0.5% * 1B) = 5M.
        diff_abs = 4M < 5M, so even with >5% pct it should be extraction_discrepancy."""
        # 8% diff, abs = 4M < 5M → extraction_discrepancy (not restatement)
        tp = self._make_tp_with_conflict(50_000_000, 54_000_000)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "extraction_discrepancy",
                         "abs 4M < fallback threshold 5M → not restatement")

    def test_fallback_triggers_restatement_above_5m(self):
        """Without total_assets, abs > 5M AND pct > 5% → potential_restatement."""
        # 10% diff, abs = 10M > 5M
        tp = self._make_tp_with_conflict(100_000_000, 110_000_000)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "potential_restatement")

    def test_with_total_assets_scales_threshold(self):
        """With total_assets=20B, threshold = max(5M, 0.5%*20B) = 100M.
        abs = 10M < 100M → extraction_discrepancy even though pct > 5%."""
        tp = self._make_tp_with_conflict(100_000_000, 110_000_000,
                                          total_assets=20_000_000_000)
        log = _reconcile_cross_filing(tp)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["clasificacion"], "extraction_discrepancy",
                         "abs 10M < scaled threshold 100M → not restatement")


if __name__ == "__main__":
    unittest.main()
