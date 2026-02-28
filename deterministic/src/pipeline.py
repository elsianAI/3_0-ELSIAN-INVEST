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
        r":operating_income|:operating_profit|:consolidated_statements_of_operations",
        re.I,
    )
    _DEPRIORITIZED_SECTION = re.compile(
        r":loss_from_operations|:discontinued|:net_income_\(loss\)",
        re.I,
    )

    @staticmethod
    def _section_bonus(source_location: str) -> int:
        """Return a priority bonus based on the table's sub-section."""
        if DeterministicPipeline._PRIMARY_IS_SECTION.search(source_location):
            return 5
        if DeterministicPipeline._DEPRIORITIZED_SECTION.search(source_location):
            return -5
        return 0

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

            if is_clean_md:
                # Table extraction from markdown
                table_fields = extract_tables_from_clean_md(
                    text, source_filename=filing_path.name
                )
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

                    # Collision resolution: if field already present, prefer
                    # the candidate with higher label-semantic priority.
                    # Section-based bonus adjusts priority for primary vs note
                    # sub-sections. Tiebreaker (equal priority): keep higher
                    # absolute value (consolidated > segment).
                    new_priority = self._alias_resolver.label_priority(
                        canonical, tf.label
                    ) + self._section_bonus(tf.source_location)
                    if canonical in period_fields[period_key]:
                        existing = period_fields[period_key][canonical]
                        old_priority = getattr(existing, "_label_priority", 0)
                        if new_priority < old_priority:
                            # New has strictly lower priority → discard
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
                        if new_priority == old_priority:
                            # Equal priority → prefer larger absolute value
                            if abs(tf.value) <= abs(existing.value):
                                audit.discard(
                                    field_name=canonical,
                                    period=period_key,
                                    reason="lower_value_duplicate",
                                    source_filing=filing_path.name,
                                    raw_label=tf.label,
                                    raw_value=tf.value,
                                    scale=scale,
                                )
                                continue

                    fr = FieldResult(
                        value=tf.value,
                        scale=scale,
                        source_filing=filing_path.name,
                        source_location=tf.source_location,
                        confidence=confidence,
                    )
                    fr._label_priority = new_priority  # type: ignore[attr-defined]
                    period_fields[period_key][canonical] = fr
                    audit.accept(
                        field_name=canonical,
                        period=period_key,
                        source_filing=filing_path.name,
                        raw_label=tf.label,
                        raw_value=tf.value,
                        scale=scale,
                    )

            else:
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

                    # Only add if we don't already have this field from tables
                    if canonical not in period_fields[period_key]:
                        period_fields[period_key][canonical] = FieldResult(
                            value=nf.value,
                            scale=scale,
                            source_filing=filing_path.name,
                            source_location=nf.source_location,
                            confidence=confidence,
                        )
                        audit.accept(
                            field_name=canonical,
                            period=period_key,
                            source_filing=filing_path.name,
                            raw_label=nf.label,
                            raw_value=nf.value,
                            scale=scale,
                        )

            if period_fields:
                filing_extractions.append(
                    (metadata.filing_type, filing_path.name, period_fields)
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
