#!/usr/bin/env python3
"""Financial table extractor for SEC HTML filings.

Parses HTML filings, locates financial statement sections (balance sheet,
income statement, cash flow, equity), converts their tables to Markdown,
and writes a compact .clean.md that fits within LLM context windows.

Per-section budget: 80k chars each for balance/income/cashflow, 40k equity.
Hard cap: 220k total chars.

Usage:
    python3 scripts/runners/clean_md_extractor.py <input.htm> <output.clean.md>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, Tag
try:
    from clean_md_quality import is_clean_md_useful as _is_clean_md_useful_common
except Exception:
    from scripts.runners.clean_md_quality import is_clean_md_useful as _is_clean_md_useful_common

# ── Section heading patterns ─────────────────────────────────────────
# Each tuple: (section_key, compiled regex for section heading)
# We search both text headings and table captions.

SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("balance_sheet", re.compile(
        r"(?:consolidated\s+)?balance\s+sheet|"
        r"(?:consolidated\s+)?statements?\s+of\s+financial\s+position|"
        r"estado[s]?\s+de\s+situaci[oó]n\s+financiera|"
        # V5.1 A4 — IFRS/FR additions
        r"bilan\s+consolid[ée]|"
        r"[ée]tat.*situation\s+financi[èe]re",
        re.IGNORECASE)),
    ("income_statement", re.compile(
        r"(?:consolidated\s+)?(?:statements?\s+of\s+)?(?:income|operations|"
        r"comprehensive\s+(?:income|loss)|earnings|profit\s+(?:and|or)\s+loss)|"
        r"(?:consolidated\s+)?(?:income|profit)\s+statement|"
        r"estado[s]?\s+de\s+resultados|"
        # V5.1 A4 — IFRS/FR additions
        r"compte\s+de\s+r[ée]sultat|"
        r"r[ée]sultat\s+consolid[ée]",
        re.IGNORECASE)),
    ("cash_flow", re.compile(
        r"(?:consolidated\s+)?statements?\s+of\s+cash[\s-]?flow|"
        r"(?:consolidated\s+)?cash[\s-]?flow\s+statement|"
        r"estado[s]?\s+de\s+flujos?\s+de\s+efectivo|"
        # V5.1 A4 — IFRS/FR additions
        r"flux\s+de\s+tr[ée]sorerie|"
        r"tableau\s+des\s+flux",
        re.IGNORECASE)),
    ("equity", re.compile(
        r"(?:consolidated\s+)?statements?\s+of\s+(?:stockholders|shareholders|changes\s+in)\s*(?:'s?)?\s*equity|"
        r"(?:consolidated\s+)?equity\s+statement|"
        r"estado[s]?\s+de\s+cambios\s+en\s+el\s+patrimonio|"
        # V5.1 A4 — IFRS/FR additions
        r"capitaux\s+propres|"
        r"variation.*capitaux",
        re.IGNORECASE)),
]

# Budget per section in characters
SECTION_BUDGETS: dict[str, int] = {
    "balance_sheet": 80_000,
    "income_statement": 80_000,
    "cash_flow": 80_000,
    "equity": 40_000,
}

HARD_CAP = 220_000


# ── Table → Markdown conversion ─────────────────────────────────────

def _table_to_markdown(table: Tag) -> str:
    """Convert an HTML <table> to Markdown, preserving structure and negatives."""
    rows = table.find_all("tr")
    if not rows:
        return ""

    md_rows: list[list[str]] = []
    for row in rows:
        cells = row.find_all(["td", "th"])
        md_cells: list[str] = []
        for cell in cells:
            text = cell.get_text(" ", strip=True)
            # Preserve parenthetical negatives as-is
            text = re.sub(r"\s+", " ", text)
            md_cells.append(text)
        if any(c.strip() for c in md_cells):
            md_rows.append(md_cells)

    if not md_rows:
        return ""

    # Determine max columns
    max_cols = max(len(r) for r in md_rows)

    # Pad rows
    for row in md_rows:
        while len(row) < max_cols:
            row.append("")

    # Build markdown table
    lines: list[str] = []
    # Header (first row)
    lines.append("| " + " | ".join(md_rows[0]) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in md_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ── Section extraction ───────────────────────────────────────────────

def _find_section_tables(soup: BeautifulSoup, pattern: re.Pattern) -> list[str]:
    """Find all tables that belong to a financial statement section.

    Strategy:
    1. Find all text nodes matching the section heading pattern
    2. From each match, collect subsequent tables until the next section heading
    """
    # Find all potential heading elements
    heading_tags = soup.find_all(
        lambda tag: tag.name in ("b", "p", "div", "span", "font", "td", "th",
                                 "h1", "h2", "h3", "h4", "h5", "h6")
        and pattern.search(tag.get_text(" ", strip=True))
        and len(tag.get_text(strip=True)) < 150  # Tight limit: real headings are short
        # Reject if the text looks like prose or narrative (not a heading)
        and not re.search(
            r"\b(?:the company|we |our |if |consumer|disposable|credit|risk|"
            r"market\s+(?:condition|environment|outlook)|economic|financial condition|"
            r"forward.looking|outlook|growth\s+(?:in|of)|depends?\s+on|subject\s+to)\b",
            tag.get_text(" ", strip=True), re.IGNORECASE)
    )

    if not heading_tags:
        return []

    tables_md: list[str] = []
    seen_tables: set[int] = set()

    for heading in heading_tags:
        heading_text = heading.get_text(" ", strip=True)

        # Walk siblings and descendants after the heading to find tables
        current = heading
        tables_found = 0
        max_walk = 50  # Don't walk too far

        for _ in range(max_walk):
            current = _next_element(current)
            if current is None:
                break

            # Stop if we hit another section heading
            if (isinstance(current, Tag)
                    and current.name in ("b", "p", "div", "span", "font", "h1", "h2", "h3", "h4")
                    and any(sp.search(current.get_text(" ", strip=True))
                            for _, sp in SECTION_PATTERNS
                            if sp is not pattern)
                    and len(current.get_text(strip=True)) < 300):
                break

            if isinstance(current, Tag) and current.name == "table":
                tid = id(current)
                if tid not in seen_tables:
                    seen_tables.add(tid)
                    md = _table_to_markdown(current)
                    if md and len(md) > 50:  # Skip trivially small tables
                        # Require at least 2 rows with numeric data (not just text tables)
                        num_rows = len(re.findall(r"^\|.*\d[\d,\.]*.*\|$", md, re.MULTILINE))
                        if num_rows >= 2:
                            tables_md.append(f"### {heading_text}\n\n{md}")
                            tables_found += 1

        if tables_found == 0:
            # The heading might be inside a table — try parent
            parent_table = heading.find_parent("table")
            if parent_table and id(parent_table) not in seen_tables:
                seen_tables.add(id(parent_table))
                md = _table_to_markdown(parent_table)
                if md and len(md) > 50:
                    num_rows = len(re.findall(r"^\|.*\d[\d,\.]*.*\|$", md, re.MULTILINE))
                    if num_rows >= 2:
                        tables_md.append(f"### {heading_text}\n\n{md}")

    return tables_md


def _next_element(tag: Tag) -> Optional[Tag]:
    """Get the next sibling or parent's next sibling element."""
    # Try next sibling
    sibling = tag.next_sibling
    while sibling is not None:
        if isinstance(sibling, Tag):
            return sibling
        sibling = sibling.next_sibling

    # Go up and try parent's next sibling
    parent = tag.parent
    if parent is not None:
        sibling = parent.next_sibling
        while sibling is not None:
            if isinstance(sibling, Tag):
                return sibling
            sibling = sibling.next_sibling

    return None


# ── Main extraction ──────────────────────────────────────────────────

def extract_financial_tables(html_path: Path) -> str:
    """Extract financial statement tables from an HTML filing.

    Returns Markdown text with sections separated by headings.
    Respects per-section budgets and hard cap.
    """
    raw = html_path.read_text(errors="replace")

    # Strip XBRL noise, scripts, styles for lighter parsing
    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)

    soup = BeautifulSoup(raw, "html.parser")

    sections: dict[str, str] = {}
    total_chars = 0

    for section_key, pattern in SECTION_PATTERNS:
        budget = SECTION_BUDGETS.get(section_key, 80_000)
        tables_md = _find_section_tables(soup, pattern)

        if not tables_md:
            sections[section_key] = f"## {section_key.upper().replace('_', ' ')}\n\n_Section not found in filing._\n"
            continue

        combined = "\n\n".join(tables_md)
        if len(combined) > budget:
            combined = combined[:budget] + "\n\n... [SECTION TRUNCATED at budget limit]"

        # Check hard cap
        if total_chars + len(combined) > HARD_CAP:
            remaining = HARD_CAP - total_chars
            if remaining > 200:
                combined = combined[:remaining] + "\n\n... [HARD CAP REACHED]"
            else:
                combined = f"## {section_key.upper().replace('_', ' ')}\n\n_Omitted: hard cap reached._\n"

        section_header = section_key.upper().replace("_", " ")
        sections[section_key] = f"## {section_header}\n\n{combined}\n"
        total_chars += len(sections[section_key])

    # Assemble
    parts = [
        f"# FINANCIAL STATEMENTS — {html_path.stem}",
        f"_Extracted from: {html_path.name}_",
        f"_Total chars: {total_chars:,}_",
        "",
    ]

    for key in ["income_statement", "balance_sheet", "cash_flow", "equity"]:
        if key in sections:
            parts.append(sections[key])

    assembled = "\n\n".join(parts)

    # Quality gate: return empty string if .clean.md would be useless
    if not _is_clean_md_useful_common(assembled, mode="html_table"):
        return ""

    return assembled


def _is_clean_md_useful(text: str) -> bool:
    """Backward-compatible wrapper around shared quality gate."""
    return _is_clean_md_useful_common(text, mode="html_table")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.htm> <output.clean.md>")
        sys.exit(1)

    htm_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not htm_path.exists():
        print(f"ERROR: {htm_path} not found")
        sys.exit(1)

    result = extract_financial_tables(htm_path)
    out_path.write_text(result, encoding="utf-8")
    print(f"[clean_md_extractor] Wrote {len(result):,} chars → {out_path}")
