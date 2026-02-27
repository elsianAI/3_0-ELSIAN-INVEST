"""Merge extractions from multiple filings into a single ExtractionResult.

Priority: annual > quarterly > earnings.
When multiple filings report the same field for the same period,
take the value from the highest-priority source.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from deterministic.src.schemas import (
    ExtractionResult,
    FieldResult,
    PeriodResult,
    AuditRecord,
)


# Filing type priority (lower = higher priority)
_TYPE_PRIORITY = {
    "10-K": 1,
    "20-F": 1,
    "40-F": 1,
    "annual_report": 1,
    "10-Q": 2,
    "6-K": 2,
    "interim_report": 2,
    "8-K": 3,
    "earnings": 3,
    "unknown": 4,
}


def _filing_priority(filing_type: str) -> int:
    """Get priority for a filing type (lower = better)."""
    return _TYPE_PRIORITY.get(filing_type, 4)


def merge_extractions(
    filing_extractions: List[
        Tuple[str, str, Dict[str, Dict[str, FieldResult]]]
    ],
    ticker: str = "",
    currency: str = "USD",
) -> ExtractionResult:
    """Merge field extractions from multiple filings.

    Args:
        filing_extractions: List of (filing_type, filename, {period: {field: FieldResult}})
        ticker: Ticker symbol
        currency: Currency code

    Returns:
        Merged ExtractionResult
    """
    # Sort by priority (annual first)
    sorted_filings = sorted(
        filing_extractions, key=lambda x: _filing_priority(x[0])
    )

    merged_periods: Dict[str, Dict[str, FieldResult]] = {}
    fields_extracted = 0
    fields_discarded = 0
    discard_reasons: list[str] = []

    for filing_type, filename, periods_data in sorted_filings:
        for period_key, fields in periods_data.items():
            if period_key not in merged_periods:
                merged_periods[period_key] = {}

            for field_name, field_result in fields.items():
                if field_name not in merged_periods[period_key]:
                    # First time seeing this field for this period
                    merged_periods[period_key][field_name] = field_result
                    fields_extracted += 1
                else:
                    # Already have a value - check if we should update
                    existing = merged_periods[period_key][field_name]
                    existing_priority = _filing_priority(
                        _guess_type_from_source(existing.source_filing)
                    )
                    new_priority = _filing_priority(filing_type)

                    if new_priority < existing_priority:
                        # New source has higher priority
                        merged_periods[period_key][field_name] = field_result
                        fields_discarded += 1
                        discard_reasons.append("duplicate_conflict")
                    elif new_priority == existing_priority:
                        # Same priority: keep existing (first seen wins)
                        fields_discarded += 1
                        discard_reasons.append("duplicate_conflict")
                    else:
                        fields_discarded += 1
                        discard_reasons.append("duplicate_conflict")

    # Build result
    result = ExtractionResult(
        ticker=ticker,
        currency=currency,
        filings_used=len(filing_extractions),
    )

    for period_key, fields in sorted(merged_periods.items()):
        period = PeriodResult(
            fecha_fin=_infer_fecha_fin(period_key),
            tipo_periodo=_infer_tipo_periodo(period_key),
            fields=fields,
        )
        result.periods[period_key] = period

    result.audit = AuditRecord(
        fields_extracted=fields_extracted,
        fields_discarded=fields_discarded,
        discarded_reasons=list(set(discard_reasons)),
    )

    return result


def _guess_type_from_source(source_filing: str) -> str:
    """Guess filing type from source filename."""
    low = source_filing.lower()
    if "10-k" in low or "10k" in low:
        return "10-K"
    if "10-q" in low or "10q" in low:
        return "10-Q"
    if "20-f" in low or "20f" in low:
        return "20-F"
    if "8-k" in low or "8k" in low:
        return "8-K"
    if "6-k" in low or "6k" in low:
        return "6-K"
    return "unknown"


def _infer_fecha_fin(period_key: str) -> str:
    """Infer period end date from period key."""
    import re

    # FY2024 -> 2024-12-31
    m = re.match(r"FY(\d{4})", period_key)
    if m:
        return f"{m.group(1)}-12-31"

    # Q1-2024 -> 2024-03-31, Q2->06-30, Q3->09-30, Q4->12-31
    m = re.match(r"Q(\d)-(\d{4})", period_key)
    if m:
        q = int(m.group(1))
        year = m.group(2)
        ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
        return f"{year}-{ends.get(q, '12-31')}"

    # H1-2024 -> 2024-06-30, H2->12-31
    m = re.match(r"H(\d)-(\d{4})", period_key)
    if m:
        h = int(m.group(1))
        year = m.group(2)
        return f"{year}-{'06-30' if h == 1 else '12-31'}"

    return ""


def _infer_tipo_periodo(period_key: str) -> str:
    """Infer period type from period key."""
    if period_key.startswith("FY"):
        return "anual"
    if period_key.startswith("Q"):
        return "trimestral"
    if period_key.startswith("H"):
        return "semestral"
    return "unknown"
