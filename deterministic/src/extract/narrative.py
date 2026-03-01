"""Narrative extraction from prose financial text.

Extracts financial data from narrative/prose sections of filings.
Patterns: "revenue amounted to EUR10,280M", "net income of $523 million",
comparative "versus $8,345M in FY2023".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class NarrativeField:
    """A single field extracted from narrative text."""

    label: str
    value: float
    currency: str = ""
    scale: str = "raw"  # raw | thousands | millions | billions
    period_hint: str = ""  # e.g. "FY2024", "2024"
    source_location: str = ""
    confidence: str = "medium"


# ── Scale keywords ───────────────────────────────────────────────────

_SCALE_WORDS = {
    "billion": "billions",
    "billions": "billions",
    "bn": "billions",
    "b": "billions",
    "million": "millions",
    "millions": "millions",
    "mn": "millions",
    "m": "millions",
    "thousand": "thousands",
    "thousands": "thousands",
    "k": "thousands",
}

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "CHF": "CHF",
    "HK$": "HKD",
}


def _parse_narrative_number(text: str) -> Optional[float]:
    """Parse a number from narrative context."""
    text = text.strip()
    if not text:
        return None

    is_negative = False
    if text.startswith("(") and text.endswith(")"):
        is_negative = True
        text = text[1:-1].strip()
    elif text.startswith("-") or text.startswith("−"):
        is_negative = True
        text = text[1:].strip()

    text = re.sub(r"[$€£¥]", "", text).strip()
    text = text.replace(",", "")

    try:
        value = float(text)
        return -value if is_negative else value
    except ValueError:
        return None


# ── Main Extraction Patterns ────────────────────────────────────────

# Pattern 1: "{label} {verb} {currency}{value} {scale}"
# e.g. "Revenue amounted to €10,280 million"
_PATTERN_LABEL_VERB_VALUE = re.compile(
    r"(?P<label>"
    r"(?:total\s+)?(?:net\s+)?"
    r"(?:revenue|revenues|sales|turnover|"
    r"(?:operating\s+)?(?:income|profit|loss|earnings)|"
    r"ebitda|ebit|"
    r"(?:net\s+)?(?:income|profit|loss|earnings)|"
    r"gross\s+(?:profit|margin)|"
    r"(?:operating\s+)?cash\s+flow|"
    r"(?:capital\s+)?expenditure|capex|"
    r"free\s+cash\s+flow|"
    r"total\s+(?:assets|liabilities|equity|debt)|"
    r"(?:cash\s+and\s+)?(?:cash\s+)?equivalents|"
    r"chiffre\s+d['\u2019]affaires|"
    r"r[ée]sultat\s+(?:net|op[ée]rationnel)|"
    r"b[ée]n[ée]fice\s+(?:net|brut)|"
    r"ingresos|beneficio\s+neto|resultado)"
    r")"
    r"\s+"
    r"(?:amounted?\s+to|(?:was|were|is|are|of|reached?|totale?d?|stood\s+at)\s*)"
    r"\s*"
    r"(?P<currency>[$€£¥]|(?:USD|EUR|GBP|HKD|CHF)\s*)?"
    r"(?P<value>[\-\(]?[\d,]+\.?\d*\)?)"
    r"\s*"
    r"(?P<scale>billion|billions|bn|million|millions|mn|thousand|thousands)?",
    re.IGNORECASE,
)

# Pattern 2: Comparative "versus {currency}{value} {scale} in {period}"
# e.g. "versus €8,345M in 2023"
_PATTERN_COMPARATIVE = re.compile(
    r"(?:versus|compared\s+(?:to|with)|vs\.?|from)\s+"
    r"(?P<currency>[$€£¥]|(?:USD|EUR|GBP|HKD|CHF)\s*)?"
    r"(?P<value>[\-\(]?[\d,]+\.?\d*\)?)"
    r"\s*"
    r"(?P<scale>billion|billions|bn|million|millions|mn|thousand|thousands|[MBK])?"
    r"\s*"
    r"(?:in\s+)?(?P<period>(?:FY\s?)?20\d{2}|Q[1-4][\s-]?20\d{2}|[HS][12][\s-]?20\d{2})?",
    re.IGNORECASE,
)

# Pattern 3: "{currency}{value} {scale} {label}" (reversed)
# e.g. "$185.2 million in revenue"
_PATTERN_VALUE_LABEL = re.compile(
    r"(?P<currency>[$€£¥]|(?:USD|EUR|GBP|HKD|CHF)\s*)"
    r"(?P<value>[\-\(]?[\d,]+\.?\d*\)?)"
    r"\s*"
    r"(?P<scale>billion|billions|bn|million|millions|mn|thousand|thousands)?"
    r"\s+(?:in|of)\s+"
    r"(?P<label>"
    r"(?:total\s+)?(?:net\s+)?"
    r"(?:revenue|revenues|sales|turnover|"
    r"(?:operating\s+)?(?:income|profit|loss)|"
    r"ebitda|ebit|"
    r"(?:net\s+)?(?:income|profit|loss)|"
    r"gross\s+(?:profit|margin)|"
    r"(?:operating\s+)?cash\s+flow|"
    r"(?:capital\s+)?expenditure|capex|"
    r"free\s+cash\s+flow|"
    r"total\s+(?:assets|liabilities|equity|debt))"
    r")",
    re.IGNORECASE,
)


def _resolve_scale(scale_text: str) -> str:
    """Resolve a scale keyword to canonical scale name."""
    if not scale_text:
        return "raw"
    low = scale_text.strip().lower()
    return _SCALE_WORDS.get(low, "raw")


def _resolve_currency(currency_text: str) -> str:
    """Resolve a currency symbol/code to ISO code."""
    if not currency_text:
        return ""
    text = currency_text.strip()
    return _CURRENCY_SYMBOLS.get(text, text.upper())


def _detect_surrounding_period(text: str, match_start: int) -> str:
    """Try to detect a period from text surrounding a match.

    Trims the suffix at the first comparative keyword so that periods
    from comparative clauses (e.g. "compared to $18M in 2023") are not
    attributed to the primary value.
    """
    prefix = text[max(0, match_start - 200):match_start]
    suffix = text[match_start:match_start + 200]

    # Trim suffix at the first comparative keyword to avoid picking up
    # the comparative period (e.g. "compared to $18M in 2023")
    comp_match = _COMPARATIVE_CONTEXT.search(suffix)
    if comp_match:
        suffix = suffix[:comp_match.start()]

    window = prefix + suffix

    # FY pattern
    m = re.search(r"\bFY\s?(\d{4})\b", window, re.IGNORECASE)
    if m:
        return f"FY{m.group(1)}"

    # "in 2024" or "for 2024"
    m = re.search(r"(?:in|for)\s+(20\d{2})\b", window, re.IGNORECASE)
    if m:
        return f"FY{m.group(1)}"

    # Quarter
    m = re.search(r"Q([1-4])[\s-]?(20\d{2})", window, re.IGNORECASE)
    if m:
        return f"Q{m.group(1)}-{m.group(2)}"

    return ""


_NON_GAAP_CONTEXT = re.compile(
    r"non[\s-]?gaap|adjusted|pro\s*forma|\bsegment\b|constant\s+currency",
    re.IGNORECASE,
)

_COMPARATIVE_CONTEXT = re.compile(
    r"compared\s+to|versus|vs\.?\s|prior[\s-]year|year[\s-]ago|from\s+\$",
    re.IGNORECASE,
)


def extract_from_narrative(
    text: str, source_filename: str = ""
) -> List[NarrativeField]:
    """Extract financial fields from narrative/prose text.

    Returns list of NarrativeField with label, value, currency, scale, period.
    """
    results: List[NarrativeField] = []

    # Pattern 1: label verb value
    for m in _PATTERN_LABEL_VERB_VALUE.finditer(text):
        value = _parse_narrative_number(m.group("value"))
        if value is None:
            continue
        context = text[max(0, m.start() - 100):m.end() + 100]
        if _NON_GAAP_CONTEXT.search(context):
            continue
        prefix = text[max(0, m.start() - 60):m.start()]
        if _COMPARATIVE_CONTEXT.search(prefix):
            continue
        period = _detect_surrounding_period(text, m.start())
        results.append(
            NarrativeField(
                label=m.group("label").strip(),
                value=value,
                currency=_resolve_currency(m.group("currency") or ""),
                scale=_resolve_scale(m.group("scale") or ""),
                period_hint=period,
                source_location=f"{source_filename}:narrative:char{m.start()}",
                confidence="medium",
            )
        )

    # Pattern 3: value label (reversed order)
    for m in _PATTERN_VALUE_LABEL.finditer(text):
        value = _parse_narrative_number(m.group("value"))
        if value is None:
            continue
        context = text[max(0, m.start() - 100):m.end() + 100]
        if _NON_GAAP_CONTEXT.search(context):
            continue
        prefix = text[max(0, m.start() - 60):m.start()]
        if _COMPARATIVE_CONTEXT.search(prefix):
            continue
        period = _detect_surrounding_period(text, m.start())
        results.append(
            NarrativeField(
                label=m.group("label").strip(),
                value=value,
                currency=_resolve_currency(m.group("currency") or ""),
                scale=_resolve_scale(m.group("scale") or ""),
                period_hint=period,
                source_location=f"{source_filename}:narrative:char{m.start()}",
                confidence="medium",
            )
        )

    return results


def extract_comparatives(
    text: str, context_label: str = "", source_filename: str = ""
) -> List[NarrativeField]:
    """Extract comparative values ("versus X in Y") from narrative text."""
    results: List[NarrativeField] = []

    for m in _PATTERN_COMPARATIVE.finditer(text):
        value = _parse_narrative_number(m.group("value"))
        if value is None:
            continue

        period = ""
        if m.group("period"):
            raw_period = m.group("period").strip()
            # Normalize period
            pm = re.match(r"(?:FY\s?)?(\d{4})$", raw_period, re.IGNORECASE)
            if pm:
                period = f"FY{pm.group(1)}"
            else:
                period = raw_period.replace(" ", "-")

        results.append(
            NarrativeField(
                label=context_label or "comparative",
                value=value,
                currency=_resolve_currency(m.group("currency") or ""),
                scale=_resolve_scale(m.group("scale") or ""),
                period_hint=period,
                source_location=f"{source_filename}:comparative:char{m.start()}",
                confidence="low",
            )
        )

    return results
