"""Detection utilities: currency, scale, periods, sections, language.

Analyzes a filing's text/markdown to determine metadata needed before extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class FilingMetadata:
    """Detected metadata for a single filing."""

    filename: str = ""
    language: str = "en"  # en | fr | es | de
    currency: str = "USD"
    scale: str = "raw"  # raw | thousands | millions | billions
    scale_confidence: str = "low"  # high | medium | low
    sections_found: List[str] = field(default_factory=list)
    periods_visible: List[str] = field(default_factory=list)
    filing_type: str = ""  # 10-K, 10-Q, 8-K, annual_report, etc.
    period_end_date: str = ""  # e.g. "2024-12-31"


# ── Currency Detection ───────────────────────────────────────────────

_CURRENCY_PATTERNS = [
    (r"\$\s*[\d,]+", "USD"),
    (r"USD\s*[\d,]+", "USD"),
    (r"[\d,]+\s*USD", "USD"),
    (r"€\s*[\d,]+", "EUR"),
    (r"EUR\s*[\d,]+", "EUR"),
    (r"[\d,]+\s*EUR", "EUR"),
    (r"£\s*[\d,]+", "GBP"),
    (r"GBP\s*[\d,]+", "GBP"),
    (r"HK\$\s*[\d,]+", "HKD"),
    (r"¥\s*[\d,]+", "JPY"),
    (r"CHF\s*[\d,]+", "CHF"),
    (r"SEK\s*[\d,]+", "SEK"),
    (r"NOK\s*[\d,]+", "NOK"),
    (r"DKK\s*[\d,]+", "DKK"),
    (r"CAD\s*[\d,]+", "CAD"),
    (r"AUD\s*[\d,]+", "AUD"),
]


def detect_currency(text: str) -> str:
    """Detect the predominant currency in a text sample."""
    counts: dict[str, int] = {}
    sample = text[:20_000]
    for pattern, currency in _CURRENCY_PATTERNS:
        hits = len(re.findall(pattern, sample))
        if hits > 0:
            counts[currency] = counts.get(currency, 0) + hits
    if not counts:
        return "USD"
    return max(counts, key=counts.get)  # type: ignore[arg-type]


# ── Scale Detection ──────────────────────────────────────────────────

_SCALE_PATTERNS: list[Tuple[re.Pattern, str, str]] = [
    (
        re.compile(
            r"\(\s*in\s+billions\b|\bin\s+billions\b",
            re.IGNORECASE,
        ),
        "billions",
        "high",
    ),
    (
        re.compile(
            r"\(\s*in\s+millions\b|\bin\s+millions\b|"
            r"\(\s*en\s+millions\b|en\s+millions\b|"
            r"\(\s*€\s*M\b|\(\s*\$\s*M\b|"
            r"amounts?\s+in\s+millions|"
            r"cifras?\s+en\s+millones|"
            r"expressed\s+in\s+millions|"
            r"in\s+EUR\s+millions|in\s+USD\s+millions",
            re.IGNORECASE,
        ),
        "millions",
        "high",
    ),
    (
        re.compile(
            r"\(\s*in\s+thousands\b|\bin\s+thousands\b|"
            r"\(\s*en\s+milliers\b|en\s+milliers\b|"
            r"amounts?\s+in\s+thousands|"
            r"cifras?\s+en\s+miles|"
            r"expressed\s+in\s+thousands",
            re.IGNORECASE,
        ),
        "thousands",
        "high",
    ),
    (
        re.compile(r"\bM€\b|\b€M\b|\b\$M\b|\bM\$\b", re.IGNORECASE),
        "millions",
        "medium",
    ),
    (
        re.compile(r"\bk€\b|\b€k\b|\b\$k\b|\bk\$\b", re.IGNORECASE),
        "thousands",
        "medium",
    ),
]


def detect_scale(text: str) -> Tuple[str, str]:
    """Detect the numeric scale used in a text.

    Returns (scale, confidence).
    Cascada DT-1: raw_notes -> header -> preflight -> uncertainty.
    """
    sample = text[:30_000]
    for pattern, scale, confidence in _SCALE_PATTERNS:
        if pattern.search(sample):
            return scale, confidence
    return "raw", "low"


# ── Language Detection ───────────────────────────────────────────────

_LANG_MARKERS = {
    "fr": [
        "chiffre d'affaires",
        "résultat",
        "bénéfice",
        "exercice",
        "comptes consolidés",
        "flux de trésorerie",
    ],
    "es": [
        "ingresos",
        "beneficio",
        "resultado",
        "ejercicio",
        "flujo de caja",
        "estados financieros",
    ],
    "de": [
        "umsatz",
        "gewinn",
        "ergebnis",
        "geschäftsjahr",
        "konzernabschluss",
    ],
}


def detect_language(text: str) -> str:
    """Detect language from financial text markers."""
    sample = text[:10_000].lower()
    scores: dict[str, int] = {}
    for lang, markers in _LANG_MARKERS.items():
        hits = sum(1 for m in markers if m in sample)
        if hits > 0:
            scores[lang] = hits
    if not scores:
        return "en"
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best if scores[best] >= 2 else "en"


# ── Period Detection ─────────────────────────────────────────────────

_PERIOD_PATTERNS = [
    # "For the Year Ended December 31, 2024"
    re.compile(
        r"(?:for\s+the\s+)?(?:fiscal\s+)?year\s+ended\s+"
        r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE,
    ),
    # "Three Months Ended September 30, 2024"
    re.compile(
        r"(?:three|six|nine)\s+months?\s+ended\s+"
        r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE,
    ),
    # "FY2024", "FY 2024"
    re.compile(r"\bFY\s?(\d{4})\b", re.IGNORECASE),
    # "Q3 2024", "Q3-2024"
    re.compile(r"\bQ([1-4])[\s-]?(\d{4})\b", re.IGNORECASE),
    # "December 31, 2024"
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    # "2024-12-31"
    re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"),
    # "H1 2024", "S1 2024"
    re.compile(r"\b[HS]([12])[\s-]?(\d{4})\b", re.IGNORECASE),
]

_MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def detect_periods(text: str) -> List[str]:
    """Detect fiscal periods mentioned in text.

    Returns list of period strings like "FY2024", "Q3-2024", "H1-2024".
    """
    sample = text[:50_000]
    periods: set[str] = set()

    # FY patterns
    for m in re.finditer(r"\bFY\s?(\d{4})\b", sample, re.IGNORECASE):
        periods.add(f"FY{m.group(1)}")

    # Quarterly patterns
    for m in re.finditer(r"\bQ([1-4])[\s-]?(\d{4})\b", sample, re.IGNORECASE):
        periods.add(f"Q{m.group(1)}-{m.group(2)}")

    # Half-year patterns
    for m in re.finditer(r"\b[HS]([12])[\s-]?(\d{4})\b", sample, re.IGNORECASE):
        periods.add(f"H{m.group(1)}-{m.group(2)}")

    # "Year Ended December 31, 2024" -> FY2024
    for m in re.finditer(
        r"(?:for\s+the\s+)?(?:fiscal\s+)?year\s+ended\s+"
        r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})",
        sample,
        re.IGNORECASE,
    ):
        year = m.group(3)
        periods.add(f"FY{year}")

    # "Three Months Ended Sep 30, 2024" -> Q3-2024
    for m in re.finditer(
        r"three\s+months?\s+ended\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})",
        sample,
        re.IGNORECASE,
    ):
        month_name = m.group(1).lower()
        month_num = _MONTH_MAP.get(month_name, 0)
        year = m.group(3)
        if month_num:
            q = (month_num - 1) // 3 + 1
            periods.add(f"Q{q}-{year}")

    # "Six Months Ended June 30, 2024" -> H1-2024
    for m in re.finditer(
        r"six\s+months?\s+ended\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})",
        sample,
        re.IGNORECASE,
    ):
        month_name = m.group(1).lower()
        month_num = _MONTH_MAP.get(month_name, 0)
        year = m.group(3)
        if month_num:
            half = 1 if month_num <= 6 else 2
            periods.add(f"H{half}-{year}")

    return sorted(periods)


# ── Period End Date Detection ────────────────────────────────────────

def detect_period_end_date(text: str) -> Optional[str]:
    """Detect the primary period end date (ISO format)."""
    sample = text[:20_000]

    # "Year Ended December 31, 2024"
    m = re.search(
        r"(?:for\s+the\s+)?(?:fiscal\s+)?year\s+ended\s+"
        r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})",
        sample,
        re.IGNORECASE,
    )
    if m:
        month_name = m.group(1).lower()
        day = int(m.group(2))
        year = int(m.group(3))
        month_num = _MONTH_MAP.get(month_name, 0)
        if month_num:
            return f"{year}-{month_num:02d}-{day:02d}"

    # ISO date "2024-12-31"
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", sample)
    if m:
        return m.group(0)

    return None


# ── Section Detection ────────────────────────────────────────────────

_SECTION_NAMES = {
    "income_statement": re.compile(
        r"(?:consolidated\s+)?(?:statements?\s+of\s+)?(?:income|operations|"
        r"comprehensive\s+(?:income|loss)|earnings|profit\s+(?:and|or)\s+loss)|"
        r"income\s+statement|profit\s+statement",
        re.IGNORECASE,
    ),
    "balance_sheet": re.compile(
        r"(?:consolidated\s+)?balance\s+sheet|"
        r"(?:consolidated\s+)?statements?\s+of\s+financial\s+position",
        re.IGNORECASE,
    ),
    "cash_flow": re.compile(
        r"(?:consolidated\s+)?statements?\s+of\s+cash[\s-]?flow|"
        r"(?:consolidated\s+)?cash[\s-]?flow\s+statement",
        re.IGNORECASE,
    ),
    "equity": re.compile(
        r"statements?\s+of\s+(?:stockholders|shareholders|changes\s+in)\s*(?:'s?)?\s*equity",
        re.IGNORECASE,
    ),
}


def detect_sections(text: str) -> List[str]:
    """Detect which financial statement sections are present."""
    found: List[str] = []
    for section_name, pattern in _SECTION_NAMES.items():
        if pattern.search(text[:50_000]):
            found.append(section_name)
    return found


# ── Filing Type Detection ────────────────────────────────────────────

def detect_filing_type(filename: str) -> str:
    """Infer filing type from filename."""
    low = filename.lower()
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
    if "def14a" in low or "proxy" in low:
        return "DEF14A"
    if "annual" in low:
        return "annual_report"
    if "interim" in low or "half" in low:
        return "interim_report"
    return "unknown"


# ── Full Detection ───────────────────────────────────────────────────

def analyze_filing(filename: str, text: str) -> FilingMetadata:
    """Run all detections on a filing's text content."""
    scale, scale_conf = detect_scale(text)
    return FilingMetadata(
        filename=filename,
        language=detect_language(text),
        currency=detect_currency(text),
        scale=scale,
        scale_confidence=scale_conf,
        sections_found=detect_sections(text),
        periods_visible=detect_periods(text),
        filing_type=detect_filing_type(filename),
        period_end_date=detect_period_end_date(text) or "",
    )
