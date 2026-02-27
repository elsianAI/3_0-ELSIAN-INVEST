"""Filing pre-flight metadata extractor (V6.2 — 1B.2).

100% determinista, <1ms por filing, 0 tokens LLM.

Detecta: idioma, estándar contable, moneda, año fiscal, secciones,
unidades por sección, restatement.  Inyecta al prompt solo señales
high/medium para guiar la extracción LLM.
"""

from __future__ import annotations

import re
from typing import Any


# ── Language detection ────────────────────────────────────────────────────────

_LANG_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("en", re.compile(r"\b(?:total\s+(?:assets|liabilities|equity)|net\s+income|revenue|cash\s+flow)\b", re.I), "high"),
    ("fr", re.compile(r"\b(?:résultat\s+net|chiffre\s+d['\u2019]affaires|total\s+(?:de\s+l['\u2019]actif|du\s+passif)|flux\s+de\s+trésorerie)\b", re.I), "high"),
    ("es", re.compile(r"\b(?:ingresos\s+totales|resultado\s+neto|flujo\s+de\s+(?:caja|efectivo))\b", re.I), "high"),
    ("de", re.compile(r"\b(?:Gesamtvermögen|Eigenkapital|Jahresüberschuss|Umsatzerlöse)\b", re.I), "medium"),
]


# ── Accounting standard detection ─────────────────────────────────────────────

_STANDARD_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("IFRS", re.compile(r"\bIFRS\b"), "high"),
    ("IFRS", re.compile(r"\bInternational\s+Financial\s+Reporting\s+Standards\b", re.I), "high"),
    ("US-GAAP", re.compile(r"\bU\.?S\.?\s*GAAP\b", re.I), "high"),
    ("US-GAAP", re.compile(r"\bGenerally\s+Accepted\s+Accounting\s+Principles\b", re.I), "medium"),
    ("FR-GAAP", re.compile(r"\bPlan\s+Comptable\s+Général\b", re.I), "medium"),
]


# ── Currency detection ────────────────────────────────────────────────────────

_CURRENCY_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("USD", re.compile(r"\b(?:United\s+States\s+dollars?|US\s*\$|USD)\b", re.I), "high"),
    ("EUR", re.compile(r"\b(?:euros?|EUR|€)\b", re.I), "high"),
    ("GBP", re.compile(r"\b(?:pounds?\s+sterling|GBP|£)\b", re.I), "high"),
    ("CAD", re.compile(r"\b(?:Canadian\s+dollars?|CAD|C\$)\b", re.I), "high"),
    ("AUD", re.compile(r"\b(?:Australian\s+dollars?|AUD|A\$)\b", re.I), "high"),
    ("JPY", re.compile(r"\b(?:Japanese\s+yen|JPY|¥)\b", re.I), "medium"),
    ("CHF", re.compile(r"\b(?:Swiss\s+francs?|CHF)\b", re.I), "medium"),
    ("CNY", re.compile(r"\b(?:Chinese\s+(?:yuan|renminbi)|CNY|RMB)\b", re.I), "medium"),
    ("HKD", re.compile(r"\b(?:Hong\s+Kong\s+dollars?|HKD|HK\$)\b", re.I), "medium"),
]


# ── Section detection ─────────────────────────────────────────────────────────

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("income_statement",  re.compile(r"\b(?:income\s+statements?|statements?\s+of\s+(?:income|operations|profit|earnings)|compte\s+de\s+résultat|profit\s+(?:and|or|&)\s+loss)\b", re.I)),
    ("balance_sheet",     re.compile(r"\b(?:balance\s+sheets?|statements?\s+of\s+financial\s+position|bilan\s+consolidé?)\b", re.I)),
    ("cash_flow",         re.compile(r"\b(?:cash\s+flows?|statements?\s+of\s+cash\s+flows?|flux\s+de\s+trésorerie|tableau\s+des\s+flux)\b", re.I)),
    ("equity",            re.compile(r"\b(?:statement\s+of\s+(?:stockholders|shareholders)['\u2019]?\s+equity|variation\s+des\s+capitaux\s+propres)\b", re.I)),
    ("notes",             re.compile(r"\b(?:notes\s+to\s+(?:the\s+)?(?:consolidated\s+)?financial\s+statements|notes\s+annexes)\b", re.I)),
    ("mda",               re.compile(r"\b(?:management['\u2019]?s?\s+discussion|MD&A|rapport\s+de\s+gestion)\b", re.I)),
]


# ── Units per section detection ───────────────────────────────────────────────

_UNIT_PATTERNS: list[tuple[str, int, re.Pattern[str]]] = [
    ("billions",     1_000_000_000, re.compile(r"\bin\s+billions?\b", re.I)),
    ("milliards",    1_000_000_000, re.compile(r"\ben\s+milliards?\b", re.I)),
    ("millions",     1_000_000,     re.compile(r"\bin\s+millions?\b", re.I)),
    ("millions_fr",  1_000_000,     re.compile(r"\ben\s+millions?\s+d['\u2019](?:euros?|dollars?|USD|EUR)\b", re.I)),
    ("millions_sym", 1_000_000,     re.compile(r"(?:\$|€|£)\s*millions?\b", re.I)),
    ("€_millions",   1_000_000,     re.compile(r"€\s*(?:M|millions?)\b", re.I)),
    ("thousands",    1_000,         re.compile(r"\bin\s+thousands?\b", re.I)),
    ("milliers",     1_000,         re.compile(r"\ben\s+milliers?\b", re.I)),
    ("k_dollars",    1_000,         re.compile(r"(?:\$|€|£)\s*(?:000s?|thousands?)\b", re.I)),
    ("units",        1,             re.compile(r"\bin\s+(?:USD|EUR|GBP)\b", re.I)),
]


# ── Restatement detection ─────────────────────────────────────────────────────

_RESTATEMENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bhave\s+been\s+restated\b", re.I), "high"),
    (re.compile(r"\brestatement\s+of\b", re.I), "high"),
    (re.compile(r"\brestated\s+(?:financial\s+)?(?:statements?|figures?|results?)\b", re.I), "high"),
    (re.compile(r"\bas\s+restated\b", re.I), "high"),
    (re.compile(r"\bréexprimé(?:s|es?)?\b", re.I), "high"),
    (re.compile(r"\bretrait(?:é|ées?)\b", re.I), "medium"),
    (re.compile(r"\*\s*restated\b", re.I), "medium"),
    (re.compile(r"\bpreviously\s+reported\b", re.I), "medium"),
    (re.compile(r"\breclassif(?:ied|ication)\b", re.I), "medium"),
]


# ── Fiscal year detection ─────────────────────────────────────────────────────

_FY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bfiscal\s+year\s+(?:ended?\s+)?(?:(?:December|June|March|September)\s+\d{1,2},?\s+)?(\d{4})\b", re.I), "high"),
    (re.compile(r"\byear\s+ended?\s+(?:(?:December|June|March|September)\s+\d{1,2},?\s+)?(\d{4})\b", re.I), "high"),
    (re.compile(r"\bFY\s*(\d{4})\b", re.I), "high"),
    (re.compile(r"\bexercice\s+(?:clos\s+le\s+)?(?:\d{1,2}\s+\w+\s+)?(\d{4})\b", re.I), "high"),
    (re.compile(r"\b(?:for\s+the\s+)?(?:twelve|six)\s+months?\s+ended?\b.*?(\d{4})\b", re.I), "medium"),
]


# ── Main preflight function ──────────────────────────────────────────────────


def preflight(text: str) -> dict[str, Any]:
    """Run deterministic pre-flight analysis on filing text.

    Args:
        text: The clean.md or raw text of a filing.

    Returns:
        Dictionary with detected metadata signals.
    """
    result: dict[str, Any] = {
        "language": None,
        "language_confidence": None,
        "accounting_standard": None,
        "accounting_standard_confidence": None,
        "currency": None,
        "currency_confidence": None,
        "fiscal_year": None,
        "fiscal_year_confidence": None,
        "sections_detected": [],
        "units_by_section": {},
        "units_global": None,
        "restatement_detected": False,
        "restatement_signals": [],
        "confidence_by_signal": {},
    }

    if not text:
        return result

    # Only analyze first 100K chars for performance
    text_sample = text[:100_000]

    # ── Language ──
    lang_scores: dict[str, int] = {}
    for lang, pattern, confidence in _LANG_PATTERNS:
        matches = pattern.findall(text_sample)
        if matches:
            lang_scores[lang] = lang_scores.get(lang, 0) + len(matches)
            result["confidence_by_signal"][f"lang:{lang}"] = confidence
    if lang_scores:
        best_lang = max(lang_scores, key=lang_scores.get)  # type: ignore
        result["language"] = best_lang
        result["language_confidence"] = "high" if lang_scores[best_lang] >= 3 else "medium"

    # ── Accounting standard ──
    for standard, pattern, confidence in _STANDARD_PATTERNS:
        if pattern.search(text_sample):
            result["accounting_standard"] = standard
            result["accounting_standard_confidence"] = confidence
            result["confidence_by_signal"][f"standard:{standard}"] = confidence
            break

    # ── Currency ──
    currency_scores: dict[str, int] = {}
    currency_conf: dict[str, str] = {}
    for currency, pattern, confidence in _CURRENCY_PATTERNS:
        matches = pattern.findall(text_sample)
        if matches:
            currency_scores[currency] = currency_scores.get(currency, 0) + len(matches)
            if currency not in currency_conf or confidence == "high":
                currency_conf[currency] = confidence
    if currency_scores:
        best_currency = max(currency_scores, key=currency_scores.get)  # type: ignore
        result["currency"] = best_currency
        result["currency_confidence"] = currency_conf.get(best_currency, "medium")
        result["confidence_by_signal"][f"currency:{best_currency}"] = result["currency_confidence"]

    # ── Fiscal year ──
    for pattern, confidence in _FY_PATTERNS:
        match = pattern.search(text_sample)
        if match:
            year_str = match.group(1)
            try:
                year = int(year_str)
                if 1990 <= year <= 2040:
                    result["fiscal_year"] = year
                    result["fiscal_year_confidence"] = confidence
                    result["confidence_by_signal"]["fiscal_year"] = confidence
                    break
            except ValueError:
                continue

    # ── Sections ──
    detected_sections = []
    for section_name, pattern in _SECTION_PATTERNS:
        match = pattern.search(text_sample)
        if match:
            detected_sections.append(section_name)
    result["sections_detected"] = detected_sections

    # ── Units by section ──
    # Split into rough sections and detect units per section
    section_boundaries = _find_section_boundaries(text_sample)
    global_unit = None
    global_unit_count = 0

    for section_name, start, end in section_boundaries:
        section_text = text_sample[start:end]
        for unit_name, multiplier, pattern in _UNIT_PATTERNS:
            if pattern.search(section_text[:2000]):  # Check only header area
                result["units_by_section"][section_name] = {
                    "unit": unit_name,
                    "multiplier": multiplier,
                }
                break

    # Global unit: most common unit in first 5K chars
    header_text = text_sample[:5000]
    for unit_name, multiplier, pattern in _UNIT_PATTERNS:
        matches = pattern.findall(header_text)
        if matches and len(matches) > global_unit_count:
            global_unit = {"unit": unit_name, "multiplier": multiplier}
            global_unit_count = len(matches)
    result["units_global"] = global_unit

    # ── Restatement ──
    restatement_signals = []
    for pattern, confidence in _RESTATEMENT_PATTERNS:
        matches = list(pattern.finditer(text_sample))
        if matches:
            signal = {
                "pattern": pattern.pattern[:60],
                "confidence": confidence,
                "count": len(matches),
                "sample": matches[0].group(0)[:80],
            }
            restatement_signals.append(signal)
    if restatement_signals:
        result["restatement_detected"] = True
        result["restatement_signals"] = restatement_signals
        result["confidence_by_signal"]["restatement"] = max(
            s["confidence"] for s in restatement_signals
        )

    return result


def _find_section_boundaries(text: str) -> list[tuple[str, int, int]]:
    """Find approximate boundaries of financial sections in text."""
    boundaries: list[tuple[str, int, int]] = []
    for section_name, pattern in _SECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 200)
            # Estimate section end: next section or +50K chars
            end = min(len(text), match.start() + 50_000)
            boundaries.append((section_name, start, end))

    # Sort by position
    boundaries.sort(key=lambda x: x[1])

    # Trim overlapping ends
    for i in range(len(boundaries) - 1):
        if boundaries[i][2] > boundaries[i + 1][1]:
            boundaries[i] = (boundaries[i][0], boundaries[i][1], boundaries[i + 1][1])

    return boundaries


def format_prompt_block(metadata: dict[str, Any]) -> str | None:
    """Format preflight metadata as a prompt injection block.

    Only includes high/medium confidence signals. Returns None if
    no useful signals detected (degradation graceful).
    """
    lines = []

    if metadata.get("language") and metadata.get("language_confidence") in ("high", "medium"):
        lines.append(f"- Document language: {metadata['language']}")

    if metadata.get("accounting_standard") and metadata.get("accounting_standard_confidence") in ("high", "medium"):
        lines.append(f"- Accounting standard: {metadata['accounting_standard']}")

    if metadata.get("currency") and metadata.get("currency_confidence") in ("high", "medium"):
        lines.append(f"- Primary currency: {metadata['currency']}")

    if metadata.get("fiscal_year") and metadata.get("fiscal_year_confidence") in ("high", "medium"):
        lines.append(f"- Fiscal year: {metadata['fiscal_year']}")

    # Units by section (critical for non-US filings)
    units = metadata.get("units_by_section", {})
    if units:
        unit_lines = []
        for section, info in units.items():
            unit_lines.append(f"  - {section}: {info['unit']} (×{info['multiplier']:,})")
        if unit_lines:
            lines.append("- Units by section:")
            lines.extend(unit_lines)
    elif metadata.get("units_global"):
        ug = metadata["units_global"]
        lines.append(f"- Units (global): {ug['unit']} (×{ug['multiplier']:,})")

    # Restatement warning
    if metadata.get("restatement_detected"):
        signals = metadata.get("restatement_signals", [])
        high_signals = [s for s in signals if s["confidence"] == "high"]
        if high_signals:
            sample = high_signals[0]["sample"]
            lines.append(f"- ⚠ RESTATEMENT DETECTED: \"{sample}\" — compare periods carefully")
        elif signals:
            lines.append("- ⚠ Possible restatement detected — compare periods carefully")

    if not lines:
        return None

    block = "# METADATA DEL DOCUMENTO (pre-flight determinista)\n\n"
    block += "\n".join(lines)
    block += "\n\nUsa esta información para guiar tu extracción. "
    block += "Presta especial atención a las unidades por sección para no cometer errores de escala."

    return block
