"""DeterministicPipeline — facade class for the full extraction pipeline.

Orchestrates: acquire -> extract -> normalize -> merge -> evaluate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from deterministic.src.schemas import (
    AcquisitionResult,
    AuditRecord,
    DashboardReport,
    DashboardRow,
    EvalReport,
    ExtractionResult,
    FieldResult,
    PeriodResult,
)
from deterministic.src.acquire.sec_edgar import fetch as sec_fetch
from deterministic.src.acquire.eu_regulators import fetch_eu_manual
from deterministic.src.extract.detect import analyze_filing, FilingMetadata
from deterministic.src.extract.tables import (
    extract_tables_from_clean_md,
    extract_tables_from_text,
    TableField,
)
from deterministic.src.extract.narrative import (
    extract_from_narrative,
    NarrativeField,
)
from deterministic.src.normalize.aliases import AliasResolver
from deterministic.src.normalize.scale import (
    infer_scale_cascade,
    validate_scale_sanity,
)
from deterministic.src.normalize.audit import AuditLog
from deterministic.src.merge import merge_extractions
from deterministic.src.evaluate import evaluate


# ── Sign normalisation ───────────────────────────────────────────────
# Expense fields that should always be stored as positive magnitudes.
_ALWAYS_POSITIVE_FIELDS = frozenset({
    "cost_of_revenue",
    "sga",
    "research_and_development",
    "depreciation_amortization",
    "interest_expense",
})

_BENEFIT_RE = re.compile(r"\bbenefit\b", re.IGNORECASE)

# ── Dividend per share from equity statement ─────────────────────────
_DIVIDEND_PER_SHARE_RE = re.compile(
    r"Dividend\s+paid\s*\(\s*\$\s*([\d,.]+)\s*per\s+share\s*\)",
    re.IGNORECASE,
)
_BALANCE_DATE_RE = re.compile(
    r"Balance\s+at\s+December\s+31[,]?\s+(20\d{2})",
    re.IGNORECASE,
)


def _extract_dividends_per_share(
    text: str, source_filename: str
) -> List[Tuple[str, float, str]]:
    """Extract dividends_per_share from equity statement labels.

    Parses lines like 'Dividend paid ($ 1.71 per share)' and associates
    them with the correct fiscal year by finding the preceding
    'Balance at December 31, YYYY' marker (dividend FY = marker_year + 1).

    Returns:
        List of (period_key, value, source_location) tuples.
    """
    results: List[Tuple[str, float, str]] = []
    # Collect all balance-date positions
    balance_positions: List[Tuple[int, int]] = []  # (char_pos, year)
    for m in _BALANCE_DATE_RE.finditer(text):
        balance_positions.append((m.start(), int(m.group(1))))

    for m in _DIVIDEND_PER_SHARE_RE.finditer(text):
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        # Find the nearest preceding balance date
        preceding_year = None
        for bpos, byear in reversed(balance_positions):
            if bpos < m.start():
                preceding_year = byear
                break
        if preceding_year is None:
            continue
        period_key = f"FY{preceding_year + 1}"
        loc = f"{source_filename}:equity_statement:char{m.start()}"
        results.append((period_key, value, loc))
    return results


def _normalize_sign(canonical: str, raw_label: str, value: float) -> float:
    """Ensure expense fields use the correct sign convention.

    Pure-expense fields are always positive (abs).
    income_tax is positive unless the label indicates a benefit.
    """
    if canonical in _ALWAYS_POSITIVE_FIELDS:
        return abs(value)
    if canonical == "income_tax" and value < 0:
        if not _BENEFIT_RE.search(raw_label):
            return abs(value)
    return value


class DeterministicPipeline:
    """Main pipeline class. Zero LLM calls, pure Python extraction."""

    def __init__(self, config_dir: str = ""):
        if not config_dir:
            config_dir = str(
                Path(__file__).parent.parent / "config"
            )
        self._config_dir = config_dir
        self._alias_resolver = AliasResolver(
            str(Path(config_dir) / "field_aliases.json")
        )

    # ── ACQUIRE ──────────────────────────────────────────────────────

    def acquire(self, case_dir: str) -> AcquisitionResult:
        """Download filings for a case. Respects cache."""
        case_path = Path(case_dir)
        case_json_path = case_path / "case.json"

        if not case_json_path.exists():
            return AcquisitionResult(
                notes=f"case.json not found in {case_dir}",
                gaps=["case.json missing"],
            )

        config = json.loads(case_json_path.read_text(encoding="utf-8"))
        ticker = config.get("ticker", "")
        source_hint = config.get("source_hint", "sec")
        filings_dir = str(case_path / "filings")

        if source_hint in ("sec", "sec_edgar"):
            result = sec_fetch(ticker, filings_dir)
        elif source_hint in ("eu_manual", "manual"):
            result = fetch_eu_manual(case_dir)
        else:
            result = AcquisitionResult(
                ticker=ticker,
                notes=f"Unknown source_hint: {source_hint}",
            )

        # Write manifest
        manifest_path = case_path / "filings_manifest.json"
        manifest_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return result

    # ── EXTRACT ──────────────────────────────────────────────────────

    # Sub-section patterns: primary IS sections get a priority bonus,
    # note/discontinued sections get penalized.
    _PRIMARY_IS_SECTION = re.compile(
        r":operating_income|:operating_profit|:consolidated_statements_of_operations"
        r"|:consolidated_statements_of_income"
        r"|:consolidated_balance_sheets|:consolidated_statements_of_comprehensive",
        re.I,
    )
    _DEPRIORITIZED_SECTION = re.compile(
        r":loss_from_operations"
        r"|:income.*from_operations"
        r"|discontinued_operations"
        r"|:discontinued"
        r"|:net_income_\(loss\)"
        r"|prepaid_income_taxes"
        r"|:income_tax_payable"
        r"|details_of_income_tax"
        r"|components_of_income"
        r"|components_of_results"
        r"|net_income.*margin"
        r"|balance_sheet_data",
        re.I,
    )

    # Tax reconciliation tables get a severe penalty because their total
    # line ("Provision for income taxes") matches the income_tax canonical
    # with high label priority, but the values may have wrong sign or
    # disagree with the IS value.  A -100 penalty ensures the merge will
    # replace these values when a better source exists.
    _STRONGLY_DEPRIORITIZED_SECTION = re.compile(
        r"federal_income_taxes"
        r"|statutory_rate"
        r"|:statements_of_operations:"
        r"|:balance_sheets:"
        r"|:statements_of_cash_flows:",
        re.I,
    )

    # ── Selection rules (loaded from config/selection_rules.json) ────

    _SELECTION_RULES_CACHE: Dict[str, Dict] = {}
    _TBL_RE = re.compile(r"tbl(\d+)")
    _ROW_RE = re.compile(r"row(\d+)")
    _COL_RE = re.compile(r"col(\d+)")

    @classmethod
    def _load_selection_rules(cls, config_dir: str) -> Dict:
        """Load selection_rules.json once per config_dir and cache."""
        key = str(Path(config_dir).resolve())
        if key in cls._SELECTION_RULES_CACHE:
            return cls._SELECTION_RULES_CACHE[key]
        path = Path(config_dir) / "selection_rules.json"
        if path.exists():
            rules = json.loads(
                path.read_text(encoding="utf-8")
            )
        else:
            rules = {}
        cls._SELECTION_RULES_CACHE[key] = rules
        return rules

    @staticmethod
    def _section_bonus(source_location: str,
                       rules: Optional[Dict] = None) -> int:
        """Return a priority bonus based on the table's sub-section.

        Reads bonus/penalty values from rules['section_weights'] if available,
        otherwise defaults to +5 / -5 / -100.
        """
        bonus = 5
        penalty = -5
        severe_penalty = -100
        if rules and "section_weights" in rules:
            sw = rules["section_weights"]
            bonus = sw.get("primary_is_bonus", 5)
            penalty = sw.get("deprioritized_penalty", -5)
            severe_penalty = sw.get("strongly_deprioritized_penalty", -100)
        if DeterministicPipeline._PRIMARY_IS_SECTION.search(source_location):
            return bonus
        if DeterministicPipeline._STRONGLY_DEPRIORITIZED_SECTION.search(source_location):
            return severe_penalty
        if DeterministicPipeline._DEPRIORITIZED_SECTION.search(source_location):
            return penalty
        return 0

    @staticmethod
    def _filing_rank(period_key: str, filing_type: str,
                     rules: Optional[Dict] = None) -> int:
        """Rank a filing type for a given period (lower = better).

        Uses filing_priority_by_period from selection_rules.json.
        """
        if rules and "filing_priority_by_period" in rules:
            priorities = rules["filing_priority_by_period"]
            # Determine period type prefix
            if period_key.startswith("FY"):
                period_type = "FY"
            elif period_key.startswith("H"):
                period_type = "H"
            else:
                period_type = "Q"
            plist = priorities.get(period_type, [])
            ft_upper = filing_type.upper()
            for idx, ft in enumerate(plist):
                if ft.upper() == ft_upper:
                    return idx
            return len(plist)  # unknown type goes last
        # Fallback to merge.py-style priority
        from deterministic.src.merge import _filing_priority
        return _filing_priority(filing_type)

    @staticmethod
    def _source_type_rank(source_type: str,
                          rules: Optional[Dict] = None) -> int:
        """Rank a source type (lower = better). table < narrative."""
        if rules and "source_type_priority" in rules:
            plist = rules["source_type_priority"]
            try:
                return plist.index(source_type)
            except ValueError:
                return len(plist)
        return 0 if source_type == "table" else 1

    @staticmethod
    def _parse_stable_order(source_filing: str,
                            source_location: str,
                            rules: Optional[Dict] = None,
                            ) -> Tuple[str, int, int, int]:
        """Extract (filing_name, tbl_index, row_number, col_number) for stable tiebreak.

        Reads direction from rules['stable_tiebreaker'] if available.
        Default: filing ASC, tbl DESC (later tables in same section win),
        row DESCENDING (totals at bottom win), col ASC.
        """
        tbl_m = DeterministicPipeline._TBL_RE.search(source_location)
        row_m = DeterministicPipeline._ROW_RE.search(source_location)
        col_m = DeterministicPipeline._COL_RE.search(source_location)
        tbl_num = int(tbl_m.group(1)) if tbl_m else 0
        row_num = int(row_m.group(1)) if row_m else 0
        col_num = int(col_m.group(1)) if col_m else 0

        # Default directions: filing ASC, tbl DESC, row DESC, col ASC
        tbl_sign = -1  # descending: higher table index → lower key → later tables win
        row_sign = -1  # descending: higher row → lower key → wins
        col_sign = 1   # ascending
        if rules and "stable_tiebreaker" in rules:
            st = rules["stable_tiebreaker"]
            if st.get("tbl_order", "").startswith("ascending"):
                tbl_sign = 1
            if st.get("row_order", "").startswith("ascending"):
                row_sign = 1
            if st.get("col_order", "").startswith("descending"):
                col_sign = -1

        return (source_filing, tbl_sign * tbl_num, row_sign * row_num, col_sign * col_num)

    @staticmethod
    def _period_affinity(period_key: str, source_filing: str) -> int:
        """Return 0 if source_filing is the primary filing for period_key, 1 otherwise.

        Only discriminates for Q and H periods.  For FY periods always returns 0
        so that newer 10-K comparative/restated values keep winning via
        lexicographic first-seen (current behaviour).
        """
        if period_key.startswith("FY"):
            return 0
        # Check if the period designation appears in the filename.
        # E.g. "Q1-2024" in "SRC_012_10-Q_Q1-2024.clean.md" → primary.
        if period_key in source_filing:
            return 0
        return 1

    @staticmethod
    def compute_sort_key(
        period_key: str,
        filing_type: str,
        source_type: str,
        label_priority: int,
        section_bonus: int,
        source_filing: str,
        source_location: str,
        rules: Optional[Dict] = None,
    ) -> Tuple:
        """Compute a comparable sort key for collision resolution.

        Lower key = better candidate. Comparison order:
        1. primary_filing_rank (lower filing type rank is better)
        2. period_affinity (0 = primary filing for this period, 1 = comparative)
        3. source_type_rank (table < narrative)
        4. semantic_rank (NEGATED label_priority + section_bonus; higher semantic = lower key)
        5. stable_order_rank (filing ASC, tbl DESC, row DESC, col ASC by default)
        """
        filing_rank = DeterministicPipeline._filing_rank(
            period_key, filing_type, rules
        )
        affinity = DeterministicPipeline._period_affinity(
            period_key, source_filing
        )
        src_rank = DeterministicPipeline._source_type_rank(
            source_type, rules
        )
        # Negate semantic priority so higher priority → lower sort key
        semantic_rank = -(label_priority + section_bonus)
        stable = DeterministicPipeline._parse_stable_order(
            source_filing, source_location, rules
        )
        return (filing_rank, affinity, src_rank, semantic_rank, stable)

    def extract(self, case_dir: str) -> ExtractionResult:
        """Extract financial data from filings in a case directory."""
        case_path = Path(case_dir)
        filings_dir = case_path / "filings"

        # Read case config
        case_json_path = case_path / "case.json"
        config = {}
        if case_json_path.exists():
            config = json.loads(case_json_path.read_text(encoding="utf-8"))

        ticker = config.get("ticker", case_path.name)
        currency = config.get("currency", "USD")

        # Load selection rules (global + per-case overrides)
        rules = dict(self._load_selection_rules(self._config_dir))
        case_overrides = config.get("selection_overrides")
        if case_overrides and isinstance(case_overrides, dict):
            rules.update(case_overrides)

        if not filings_dir.exists() or not any(filings_dir.iterdir()):
            return ExtractionResult(
                ticker=ticker,
                currency=currency,
                filings_used=0,
            )

        audit = AuditLog()
        filing_extractions: List[
            Tuple[str, str, Dict[str, Dict[str, FieldResult]]]
        ] = []

        # Process each filing
        for filing_path in sorted(filings_dir.iterdir()):
            if not filing_path.is_file():
                continue

            suffix = filing_path.suffix.lower()
            if suffix not in {".md", ".txt", ".clean.md"}:
                # Skip non-text files (.htm, .pdf handled via .clean.md/.txt)
                if suffix in {".htm", ".html", ".pdf"}:
                    continue
                continue

            # Prefer .clean.md files for table extraction
            is_clean_md = filing_path.name.endswith(".clean.md")

            text = filing_path.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                continue

            # Detect filing metadata
            metadata = analyze_filing(filing_path.name, text)

            # Determine scale for this filing
            filing_scale = metadata.scale
            filing_scale_confidence = metadata.scale_confidence

            # Extract fields
            period_fields: Dict[str, Dict[str, FieldResult]] = {}
            # Track which raw labels contribute to additive fields so that
            # new constituents are accumulated while same-label duplicates
            # from a different table use normal collision resolution.
            additive_labels: Dict[str, Dict[str, set]] = {}  # period→field→{labels}
            # Save raw table fields for post-processing (e.g. sub-total recovery)
            _raw_table_fields: list = []

            if is_clean_md:
                # Table extraction from markdown
                table_fields = extract_tables_from_clean_md(
                    text, source_filename=filing_path.name,
                    filing_type=metadata.filing_type,
                )
                _raw_table_fields = list(table_fields)
                for tf in table_fields:
                    canonical = self._alias_resolver.resolve(tf.label)
                    if canonical is None:
                        audit.discard(
                            field_name=tf.label,
                            period=tf.column_header,
                            reason="label_ambiguous",
                            source_filing=filing_path.name,
                            raw_label=tf.label,
                            raw_value=tf.value,
                        )
                        continue

                    # Scale inference
                    field_mult = self._alias_resolver.get_multiplier(canonical)
                    scale, confidence = infer_scale_cascade(
                        filing_scale, "", metadata.scale, field_mult
                    )

                    # Sanity check
                    if not validate_scale_sanity(tf.value, canonical, scale):
                        audit.discard(
                            field_name=canonical,
                            period=tf.column_header,
                            reason="scale_uncertain",
                            source_filing=filing_path.name,
                            raw_label=tf.label,
                            raw_value=tf.value,
                            scale=scale,
                        )
                        continue

                    period_key = tf.column_header
                    if not period_key or period_key == "unknown":
                        # Discard: better to lose a field than assign wrong period
                        audit.discard(
                            field_name=canonical,
                            period="unknown",
                            reason="period_unknown",
                            source_filing=filing_path.name,
                            raw_label=tf.label,
                            raw_value=tf.value,
                            scale=scale,
                        )
                        continue

                    if period_key not in period_fields:
                        period_fields[period_key] = {}

                    # Collision resolution via hierarchical sort key.
                    # Lower sort key = better candidate.
                    # For additive fields, track contributor labels to
                    # detect new constituents vs duplicate variants.
                    new_label_priority = self._alias_resolver.label_priority(
                        canonical, tf.label
                    )
                    new_sec_bonus = self._section_bonus(
                        tf.source_location, rules
                    )
                    new_sort_key = self.compute_sort_key(
                        period_key=period_key,
                        filing_type=metadata.filing_type,
                        source_type="table",
                        label_priority=new_label_priority,
                        section_bonus=new_sec_bonus,
                        source_filing=filing_path.name,
                        source_location=tf.source_location,
                        rules=rules,
                    )
                    if canonical in period_fields[period_key]:
                        existing = period_fields[period_key][canonical]
                        # ── Additive fields (e.g. sga) ──────────────
                        # When two DIFFERENT labels both map to the same
                        # additive canonical (e.g. "Selling and marketing"
                        # + "General and administrative" → sga), SUM their
                        # values.  Same-constituent variants (detected by
                        # substring matching, e.g. "selling and marketing"
                        # vs "selling and marketing expenses") are discarded
                        # to prevent double-counting.
                        norm_lbl = self._alias_resolver._normalize(tf.label)
                        if self._alias_resolver.is_additive(canonical):
                            seen = additive_labels.get(
                                period_key, {}
                            ).get(canonical, set())
                            is_new = not any(
                                s in norm_lbl or norm_lbl in s
                                for s in seen
                            )
                            if is_new:
                                # New constituent label → accumulate
                                combined_value = existing.value + _normalize_sign(
                                    canonical, tf.label, tf.value
                                )
                                fr = FieldResult(
                                    value=combined_value,
                                    scale=existing.scale,
                                    source_filing=existing.source_filing,
                                    source_location=existing.source_location,
                                    confidence=existing.confidence,
                                )
                                fr._sort_key = existing._sort_key  # type: ignore[attr-defined]
                                period_fields[period_key][canonical] = fr
                                additive_labels.setdefault(
                                    period_key, {}
                                ).setdefault(canonical, set()).add(norm_lbl)
                                audit.accept(
                                    field_name=canonical,
                                    period=period_key,
                                    source_filing=filing_path.name,
                                    raw_label=tf.label,
                                    raw_value=tf.value,
                                    scale=scale,
                                )
                                continue
                            else:
                                # Same constituent variant → discard
                                audit.discard(
                                    field_name=canonical,
                                    period=period_key,
                                    reason="additive_duplicate_constituent",
                                    source_filing=filing_path.name,
                                    raw_label=tf.label,
                                    raw_value=tf.value,
                                    scale=scale,
                                )
                                continue
                        # ── Normal collision resolution ──────────────
                        old_sort_key = getattr(
                            existing, "_sort_key",
                            (999, 999, 0, ("", 0, 0, 0)),
                        )
                        if new_sort_key >= old_sort_key:
                            # New candidate is same or worse → discard
                            audit.discard(
                                field_name=canonical,
                                period=period_key,
                                reason="lower_priority_duplicate",
                                source_filing=filing_path.name,
                                raw_label=tf.label,
                                raw_value=tf.value,
                                scale=scale,
                            )
                            continue

                    fr = FieldResult(
                        value=_normalize_sign(canonical, tf.label, tf.value),
                        scale=scale,
                        source_filing=filing_path.name,
                        source_location=tf.source_location,
                        confidence=confidence,
                    )
                    fr._sort_key = new_sort_key  # type: ignore[attr-defined]
                    period_fields[period_key][canonical] = fr
                    # Seed additive_labels when first storing an additive field
                    if self._alias_resolver.is_additive(canonical):
                        norm_lbl = self._alias_resolver._normalize(tf.label)
                        additive_labels.setdefault(
                            period_key, {}
                        ).setdefault(canonical, set()).add(norm_lbl)
                    audit.accept(
                        field_name=canonical,
                        period=period_key,
                        source_filing=filing_path.name,
                        raw_label=tf.label,
                        raw_value=tf.value,
                        scale=scale,
                    )

                # ── Dividend per share from equity statement labels ──
                for dps_period, dps_value, dps_loc in _extract_dividends_per_share(
                    text, filing_path.name
                ):
                    canonical = "dividends_per_share"
                    if dps_period not in period_fields:
                        period_fields[dps_period] = {}
                    if canonical not in period_fields[dps_period]:
                        fr = FieldResult(
                            value=dps_value,
                            scale="raw",
                            source_filing=filing_path.name,
                            source_location=dps_loc,
                            confidence="high",
                        )
                        period_fields[dps_period][canonical] = fr
                        audit.accept(
                            field_name=canonical,
                            period=dps_period,
                            source_filing=filing_path.name,
                            raw_label="Dividend paid ($ per share)",
                            raw_value=dps_value,
                            scale="raw",
                        )

            else:
                # Space-aligned table extraction from .txt files
                # (e.g. pdfplumber output with column-preserving layout)
                txt_table_fields = extract_tables_from_text(
                    text, source_filename=filing_path.name,
                )
                _raw_table_fields = list(txt_table_fields)
                for tf in txt_table_fields:
                    canonical = self._alias_resolver.resolve(tf.label)
                    if canonical is None:
                        audit.discard(
                            field_name=tf.label,
                            period=tf.column_header,
                            reason="label_ambiguous",
                            source_filing=filing_path.name,
                            raw_label=tf.label,
                            raw_value=tf.value,
                        )
                        continue

                    # Scale inference
                    field_mult = self._alias_resolver.get_multiplier(canonical)
                    scale, confidence = infer_scale_cascade(
                        filing_scale, "", metadata.scale, field_mult
                    )

                    # Sanity check
                    if not validate_scale_sanity(tf.value, canonical, scale):
                        audit.discard(
                            field_name=canonical,
                            period=tf.column_header,
                            reason="scale_uncertain",
                            source_filing=filing_path.name,
                            raw_label=tf.label,
                            raw_value=tf.value,
                            scale=scale,
                        )
                        continue

                    period_key = tf.column_header
                    if not period_key or period_key == "unknown":
                        audit.discard(
                            field_name=canonical,
                            period="unknown",
                            reason="period_unknown",
                            source_filing=filing_path.name,
                            raw_label=tf.label,
                            raw_value=tf.value,
                            scale=scale,
                        )
                        continue

                    if period_key not in period_fields:
                        period_fields[period_key] = {}

                    # Collision resolution
                    new_label_priority = self._alias_resolver.label_priority(
                        canonical, tf.label
                    )
                    section_bonus = 0
                    loc_lower = tf.source_location.lower()
                    if "income_statement" in loc_lower:
                        section_bonus = 1
                    elif "balance_sheet" in loc_lower:
                        section_bonus = 1
                    elif "cash_flow" in loc_lower:
                        section_bonus = 1
                    new_sort_key = self.compute_sort_key(
                        period_key=period_key,
                        filing_type=metadata.filing_type,
                        source_type="table",
                        label_priority=new_label_priority,
                        section_bonus=section_bonus,
                        source_filing=filing_path.name,
                        source_location=tf.source_location,
                        rules=rules,
                    )

                    if canonical in period_fields[period_key]:
                        existing = period_fields[period_key][canonical]
                        # ── Additive fields ──────────────────────────
                        # Use label + source_location for dedup so same
                        # label from different table sections (e.g.
                        # non-current vs current) is accumulated.
                        norm_lbl = self._alias_resolver._normalize(tf.label)
                        dedup_key = norm_lbl + "|" + tf.source_location
                        if self._alias_resolver.is_additive(canonical):
                            seen = additive_labels.get(
                                period_key, {}
                            ).get(canonical, set())
                            is_new = dedup_key not in seen
                            if is_new:
                                combined_value = existing.value + _normalize_sign(
                                    canonical, tf.label, tf.value
                                )
                                fr = FieldResult(
                                    value=combined_value,
                                    scale=existing.scale,
                                    source_filing=existing.source_filing,
                                    source_location=existing.source_location,
                                    confidence=existing.confidence,
                                )
                                fr._sort_key = existing._sort_key  # type: ignore[attr-defined]
                                period_fields[period_key][canonical] = fr
                                additive_labels.setdefault(
                                    period_key, {}
                                ).setdefault(canonical, set()).add(dedup_key)
                                audit.accept(
                                    field_name=canonical,
                                    period=period_key,
                                    source_filing=filing_path.name,
                                    raw_label=tf.label,
                                    raw_value=tf.value,
                                    scale=scale,
                                )
                                continue
                            else:
                                audit.discard(
                                    field_name=canonical,
                                    period=period_key,
                                    reason="additive_duplicate_constituent",
                                    source_filing=filing_path.name,
                                    raw_label=tf.label,
                                    raw_value=tf.value,
                                    scale=scale,
                                )
                                continue
                        # ── Normal collision resolution ──────────────
                        old_sort_key = getattr(
                            existing, "_sort_key",
                            (999, 999, 0, ("", 0, 0, 0)),
                        )
                        if new_sort_key >= old_sort_key:
                            audit.discard(
                                field_name=canonical,
                                period=period_key,
                                reason="lower_priority_duplicate",
                                source_filing=filing_path.name,
                                raw_label=tf.label,
                                raw_value=tf.value,
                                scale=scale,
                            )
                            continue

                    fr = FieldResult(
                        value=_normalize_sign(canonical, tf.label, tf.value),
                        scale=scale,
                        source_filing=filing_path.name,
                        source_location=tf.source_location,
                        confidence=confidence,
                    )
                    fr._sort_key = new_sort_key  # type: ignore[attr-defined]
                    period_fields[period_key][canonical] = fr
                    # Seed additive_labels when first storing an additive field
                    if self._alias_resolver.is_additive(canonical):
                        dedup_seed = self._alias_resolver._normalize(tf.label) + "|" + tf.source_location
                        additive_labels.setdefault(
                            period_key, {}
                        ).setdefault(canonical, set()).add(dedup_seed)
                    audit.accept(
                        field_name=canonical,
                        period=period_key,
                        source_filing=filing_path.name,
                        raw_label=tf.label,
                        raw_value=tf.value,
                        scale=scale,
                    )

                # Narrative extraction from .txt files
                narrative_fields = extract_from_narrative(
                    text, source_filename=filing_path.name
                )
                for nf in narrative_fields:
                    canonical = self._alias_resolver.resolve(nf.label)
                    if canonical is None:
                        audit.discard(
                            field_name=nf.label,
                            period=nf.period_hint,
                            reason="label_ambiguous",
                            source_filing=filing_path.name,
                            raw_label=nf.label,
                            raw_value=nf.value,
                        )
                        continue

                    # Scale: use narrative's own scale if available
                    scale = nf.scale if nf.scale != "raw" else filing_scale
                    confidence = "medium" if nf.scale != "raw" else filing_scale_confidence

                    period_key = nf.period_hint
                    if not period_key:
                        # Discard: better to lose a field than assign wrong period
                        audit.discard(
                            field_name=canonical,
                            period="unknown",
                            reason="period_unknown",
                            source_filing=filing_path.name,
                            raw_label=nf.label,
                            raw_value=nf.value,
                            scale=scale,
                        )
                        continue

                    if period_key not in period_fields:
                        period_fields[period_key] = {}

                    # Collision resolution: narrative uses sort key too
                    new_label_priority = self._alias_resolver.label_priority(
                        canonical, nf.label
                    )
                    new_sort_key = self.compute_sort_key(
                        period_key=period_key,
                        filing_type=metadata.filing_type,
                        source_type="narrative",
                        label_priority=new_label_priority,
                        section_bonus=0,
                        source_filing=filing_path.name,
                        source_location=nf.source_location,
                        rules=rules,
                    )
                    if canonical in period_fields[period_key]:
                        existing = period_fields[period_key][canonical]
                        old_sort_key = getattr(
                            existing, "_sort_key",
                            (999, 999, 0, ("", 0, 0, 0)),
                        )
                        if new_sort_key >= old_sort_key:
                            audit.discard(
                                field_name=canonical,
                                period=period_key,
                                reason="lower_priority_duplicate",
                                source_filing=filing_path.name,
                                raw_label=nf.label,
                                raw_value=nf.value,
                                scale=scale,
                            )
                            continue

                    fr = FieldResult(
                        value=_normalize_sign(canonical, nf.label, nf.value),
                        scale=scale,
                        source_filing=filing_path.name,
                        source_location=nf.source_location,
                        confidence=confidence,
                    )
                    fr._sort_key = new_sort_key  # type: ignore[attr-defined]
                    period_fields[period_key][canonical] = fr
                    audit.accept(
                        field_name=canonical,
                        period=period_key,
                        source_filing=filing_path.name,
                        raw_label=nf.label,
                        raw_value=nf.value,
                        scale=scale,
                    )

            # ── Post-process: recover total_liabilities from sub-totals ──
            # IFRS filings often have "Total non-current liabilities" and
            # "Total current liabilities" without a standalone "Total
            # liabilities" line.  The \bcurrent\b rejection prevents these
            # from resolving via aliases to avoid double-counting in US GAAP
            # filings.  Recover by summing the sub-totals when the parent
            # total is missing.
            import re as _re
            _NC_LIAB_RE = _re.compile(
                r"total\s+non[- ]?current\s+liabilities", _re.I
            )
            _C_LIAB_RE = _re.compile(
                r"total\s+current\s+liabilities", _re.I
            )
            for pk in list(period_fields.keys()):
                if "total_liabilities" not in period_fields[pk]:
                    nc_val = None
                    c_val = None
                    nc_loc = ""
                    for rtf in _raw_table_fields:
                        if rtf.column_header != pk:
                            continue
                        if _NC_LIAB_RE.search(rtf.label):
                            nc_val = rtf.value
                            nc_loc = rtf.source_location
                        elif _C_LIAB_RE.search(rtf.label):
                            c_val = rtf.value
                    if nc_val is not None and c_val is not None:
                        period_fields[pk]["total_liabilities"] = FieldResult(
                            value=nc_val + c_val,
                            scale=filing_scale,
                            source_filing=filing_path.name,
                            source_location=nc_loc,
                            confidence=filing_scale_confidence,
                        )

            if period_fields:
                filing_extractions.append(
                    (metadata.filing_type, filing_path.name, period_fields)
                )

        # Post-process per-filing: "basic and diluted" EPS duplication.
        # When a filing reports a combined "basic and diluted" figure and
        # only eps_basic was resolved, copy the value to eps_diluted
        # (and vice versa) within the same filing extraction.
        for _ft, _fn, pf in filing_extractions:
            for _pk in pf:
                if "eps_basic" in pf[_pk] and "eps_diluted" not in pf[_pk]:
                    pf[_pk]["eps_diluted"] = FieldResult(
                        value=pf[_pk]["eps_basic"].value,
                        scale=pf[_pk]["eps_basic"].scale,
                        source_filing=pf[_pk]["eps_basic"].source_filing,
                        source_location=pf[_pk]["eps_basic"].source_location,
                        confidence=pf[_pk]["eps_basic"].confidence,
                    )
                elif "eps_diluted" in pf[_pk] and "eps_basic" not in pf[_pk]:
                    pf[_pk]["eps_basic"] = FieldResult(
                        value=pf[_pk]["eps_diluted"].value,
                        scale=pf[_pk]["eps_diluted"].scale,
                        source_filing=pf[_pk]["eps_diluted"].source_filing,
                        source_location=pf[_pk]["eps_diluted"].source_location,
                        confidence=pf[_pk]["eps_diluted"].confidence,
                    )

        # Merge all filing extractions
        result = merge_extractions(
            filing_extractions, ticker=ticker, currency=currency
        )

        # Update audit
        result.audit.fields_extracted += audit.accepted_count
        result.audit.fields_discarded += audit.discarded_count
        result.audit.discarded_reasons.extend(audit.discard_reasons)
        result.audit.discarded_reasons = list(
            set(result.audit.discarded_reasons)
        )

        return result

    # ── EVALUATE ─────────────────────────────────────────────────────

    def evaluate(self, case_dir: str) -> EvalReport:
        """Extract and evaluate against expected.json."""
        case_path = Path(case_dir)
        extraction = self.extract(case_dir)
        expected_path = str(case_path / "expected.json")

        report = evaluate(extraction, expected_path)

        # Add filings coverage from manifest
        manifest_path = case_path / "filings_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            report.filings_coverage_pct = manifest.get(
                "filings_coverage_pct", 0.0
            )

        return report

    # ── RUN ──────────────────────────────────────────────────────────

    def run(
        self, case_dir: str
    ) -> Tuple[AcquisitionResult, ExtractionResult, EvalReport]:
        """Full pipeline: acquire + extract + evaluate."""
        acq = self.acquire(case_dir)
        ext = self.extract(case_dir)
        evl = self.evaluate(case_dir)
        return acq, ext, evl

    # ── DASHBOARD ────────────────────────────────────────────────────

    def dashboard(self, cases_dir: str = "cases") -> DashboardReport:
        """Run evaluation on all cases, produce summary report."""
        cases_path = Path(cases_dir)
        report = DashboardReport()

        if not cases_path.exists():
            return report

        for case_subdir in sorted(cases_path.iterdir()):
            if not case_subdir.is_dir():
                continue
            case_json = case_subdir / "case.json"
            if not case_json.exists():
                continue

            config = json.loads(case_json.read_text(encoding="utf-8"))
            ticker = config.get("ticker", case_subdir.name)
            source = config.get("source_hint", "unknown")

            try:
                _, ext, evl = self.run(str(case_subdir))
            except Exception as exc:
                print(f"  [ERROR] {ticker}: {exc}")
                continue

            row = DashboardRow(
                ticker=ticker,
                source=source,
                filings=ext.filings_used,
                periods=len(ext.periods),
                expected=evl.total_expected,
                matched=evl.matched,
                score=evl.score,
            )
            report.rows.append(row)
            report.total_filings += row.filings
            report.total_periods += row.periods
            report.total_expected += row.expected
            report.total_matched += row.matched

        if report.total_expected > 0:
            report.total_score = round(
                report.total_matched / report.total_expected * 100, 1
            )

        return report
