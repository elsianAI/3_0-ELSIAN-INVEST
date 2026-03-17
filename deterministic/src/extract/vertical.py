"""Vertical-format balance sheet extraction from EDGAR .txt filings.

EDGAR 10-K filings often render the consolidated balance sheet in a
vertical format in .txt: one label per line, followed by values on
subsequent lines (possibly with ``$`` signs on separate lines).  This
module detects that pattern and extracts key BS totals plus specific
line items (cash, debt components).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from deterministic.src.extract.tables import TableField, parse_number


# ── Target labels in the consolidated BS ─────────────────────────────
# Each tuple: (compiled regex matching the label line, canonical name,
#              is_debt_component flag).
# Debt components are accumulated to synthesise ``total_debt``.
_TARGET_LABELS: List[Tuple[re.Pattern, str, bool]] = [
    (re.compile(r"^cash and cash equivalents$", re.I),
     "cash_and_equivalents", False),
    (re.compile(r"^total\s+assets$", re.I),
     "total_assets", False),
    (re.compile(r"^total\s+liabilities$", re.I),
     "total_liabilities", False),
    (re.compile(
        r"^total\s+(?:stockholders|shareholders).{0,10}equity$"
        r"|^total\s+equity$",
        re.I,
    ), "total_equity", False),
    (re.compile(r"^current\s+portion\s+of\s+long[\s-]term\s+debt$", re.I),
     "_debt_current", True),
    (re.compile(r"^long[\s-]term\s+debt\b", re.I),
     "_debt_long_term", True),
]

# ── Section boundary detection ───────────────────────────────────────
_SCHEDULE_I_RE = re.compile(
    r"Schedule\s+I"
    r"|Condensed\s+Financial\s+Information"
    r"|Financial\s+Information\s+of\s+(?:the\s+)?Registrant",
    re.I,
)
_BS_END_RE = re.compile(
    r"^See accompanying notes"
    r"|^Notes to Consolidated"
    r"|^Table of Contents"
    r"|^CONSOLIDATED\s+S",
    re.I,
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_ASSETS_LINE_RE = re.compile(r"^ASSETS\s*$", re.I)
# Matches "CONSOLIDATED" (possibly split: "CONSOLIDATED B\nALANCE SHEETS")
_CONSOLIDATED_FRAG_RE = re.compile(r"\bCONSOLIDATED\b", re.I)


def _collect_values(
    lines: List[str], label_idx: int, n_periods: int,
) -> List[Optional[float]]:
    """Read up to *n_periods* numeric values from lines after *label_idx*.

    Skips blank lines and standalone ``$`` tokens.  Stops when it
    encounters a line that looks like another label (contains alpha
    characters and is not a parenthetical-negative number).
    """
    values: List[Optional[float]] = []
    i = label_idx + 1
    limit = min(label_idx + 4 * n_periods + 6, len(lines))
    while i < limit and len(values) < n_periods:
        raw = lines[i].strip()
        i += 1
        if not raw or raw == "$":
            continue
        # Dash-as-zero
        if raw in ("\u2014", "\u2013", "-", "\u2014\u2014", "--"):
            values.append(0.0)
            continue
        # Try parse number (handles commas, parens, minus)
        cleaned = raw.replace("$", "").strip()
        val = parse_number(cleaned)
        if val is not None:
            values.append(val)
            continue
        # If the line has letters (not just punctuation/digits), it is
        # probably the next label -> stop scanning.
        if re.search(r"[A-Za-z]", raw):
            break
    return values


def extract_vertical_bs(
    text: str,
    source_filename: str,
) -> List[TableField]:
    """Extract consolidated BS fields from vertical-format .txt content.

    Returns :class:`TableField` entries for ``total_assets``,
    ``total_liabilities``, ``total_equity``, ``cash_and_equivalents``
    and synthesised ``total_debt`` (current + long-term debt
    components).

    Only extracts from the *consolidated* balance sheet section,
    skipping Schedule I / condensed parent-only sections.
    """
    lines = text.split("\n")
    n = len(lines)

    # ── Step 1: Find consolidated BS section boundaries ──────────
    # Strategy: locate standalone "ASSETS" lines, then verify the
    # context is "CONSOLIDATED ... BALANCE SHEETS" (not Schedule I).
    # The EDGAR .txt often splits headers across lines, e.g.:
    #   "CONSOLIDATED B"
    #   "ALANCE SHEETS"
    # so we join a small window of preceding lines to check context.

    bs_start: Optional[int] = None
    for i, line in enumerate(lines):
        if not _ASSETS_LINE_RE.match(line.strip()):
            continue
        # Check backward context (up to 15 lines) for "CONSOLIDATED"
        # and absence of "Schedule I" — the consolidated BS section
        # always has "CONSOLIDATED ... BALANCE SHEETS" in the heading
        # area, while Schedule I sections do not.
        ctx_start = max(0, i - 15)
        context = " ".join(l.strip() for l in lines[ctx_start:i])
        if not _CONSOLIDATED_FRAG_RE.search(context):
            continue
        if _SCHEDULE_I_RE.search(context):
            continue
        bs_start = i
        break

    if bs_start is None:
        return []

    # Find end of BS section
    bs_end: Optional[int] = None
    for i in range(bs_start + 10, min(bs_start + 500, n)):
        if _BS_END_RE.match(lines[i].strip()):
            bs_end = i
            break
    if bs_end is None:
        bs_end = min(bs_start + 400, n)

    # ── Step 2: Detect period years ──────────────────────────────
    # Look backward from ASSETS for year headers.  EDGAR may put
    # years on a single line ("2025   2024") or on separate lines.
    period_years: List[str] = []
    for i in range(bs_start - 1, max(bs_start - 10, 0), -1):
        stripped = lines[i].strip()
        years = _YEAR_RE.findall(stripped)
        if len(years) >= 2:
            period_years = [f"FY{y}" for y in years[:2]]
            break
        if len(years) == 1:
            # Single-year lines: collect backwards (nearest first)
            period_years.insert(0, f"FY{years[0]}")
            if len(period_years) >= 2:
                break
    # Ensure correct order: most recent year first (= column 1)
    if len(period_years) >= 2:
        y0 = int(period_years[0][2:])
        y1 = int(period_years[1][2:])
        if y0 < y1:
            period_years = [period_years[1], period_years[0]]
    n_periods = max(len(period_years), 2)

    # ── Step 3: Scan for target labels and extract values ────────
    results: List[TableField] = []
    debt_by_period: Dict[str, float] = {}

    for j in range(bs_start, bs_end):
        stripped = lines[j].strip()
        if not stripped:
            continue

        for pat, canonical, is_debt in _TARGET_LABELS:
            if not pat.match(stripped):
                continue

            values = _collect_values(lines, j, n_periods)
            for vi, val in enumerate(values):
                if val is None:
                    continue
                period = (
                    period_years[vi]
                    if vi < len(period_years)
                    else f"period_{vi}"
                )
                if is_debt:
                    debt_by_period[period] = (
                        debt_by_period.get(period, 0.0) + val
                    )
                else:
                    results.append(TableField(
                        label=stripped,
                        value=val,
                        column_header=period,
                        source_location=(
                            f"{source_filename}:vertical_bs"
                            f":consolidated:{canonical}"
                        ),
                    ))
            break  # matched a pattern, move to next line

    # ── Step 4: Synthesise total_debt ────────────────────────────
    for period, debt_total in debt_by_period.items():
        results.append(TableField(
            label="Total debt (current + long-term)",
            value=debt_total,
            column_header=period,
            source_location=(
                f"{source_filename}:vertical_bs"
                ":consolidated:total_debt"
            ),
        ))

    return results
