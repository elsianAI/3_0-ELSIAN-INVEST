"""Table extraction from markdown financial statements.

Parses markdown tables (from .clean.md files) and extracts field->value mappings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class TableField:
    """A single field extracted from a table row."""

    label: str  # Original label from the table
    value: float
    column_header: str = ""  # The column header (e.g. year/period)
    source_location: str = ""  # e.g. "table:income_statement:row5"


def parse_number(text: str) -> Optional[float]:
    """Parse a number from table cell text.

    Handles: 1,234.56 | (1,234.56) | -1,234.56 | 1234 | —/- (dash = 0)
    """
    text = text.strip()
    if not text or text in {"—", "–", "-", "N/A", "n/a", "NM", "nm"}:
        return None

    # Check for parenthetical negatives: (1,234)
    is_negative = False
    if text.startswith("(") and text.endswith(")"):
        is_negative = True
        text = text[1:-1].strip()
    elif text.startswith("(") and not text.endswith(")"):
        # Split-cell parenthetical: SEC filings often put ')' in the next cell.
        # Treat "( 1,234" as negative.
        is_negative = True
        text = text[1:].strip()
    elif text.startswith("-") or text.startswith("−"):
        is_negative = True
        text = text[1:].strip()

    # Remove currency symbols and whitespace
    text = re.sub(r"[$€£¥]", "", text).strip()
    # Remove percent signs (we'll track separately)
    text = text.rstrip("%").strip()

    if not text:
        return None

    # Handle European number format: 1.234,56 -> 1234.56
    # Detect if comma is decimal separator: pattern like "123,45" (2 digits after comma, no dots)
    if re.match(r"^[\d.]+,\d{1,2}$", text):
        # European: dots are thousands, comma is decimal
        text = text.replace(".", "").replace(",", ".")
    else:
        # US/standard: commas are thousands
        text = text.replace(",", "")

    try:
        value = float(text)
        return -value if is_negative else value
    except ValueError:
        return None


_MONTH_NAME_RE = re.compile(
    r"^(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?$",
    re.IGNORECASE,
)

_PERIOD_INDICATOR_RE = re.compile(
    r"^(?:Three|Six|Nine)\s+Months?\s+Ended$",
    re.IGNORECASE,
)


def _is_subheader_row(cells: List[str]) -> bool:
    """Check if a row is a sub-header containing year/period/date fragments.

    Detects rows like:
    - | | 2024 | | 2023 | | | |              (year sub-header)
    - | | (In thousands) | | | | | |         (scale sub-header)
    - | | September 30, | | December 31, |   (date fragment sub-header)
    - | | Three Months Ended | | Nine ... |  (period indicator sub-header)
    These appear as data rows after the separator in multi-header tables.
    """
    first_cell = cells[0].strip() if cells else ""
    if first_cell and not re.match(r"^\s*$", first_cell):
        return False
    # Check if any non-first cell contains a year or scale indicator
    rest = [c.strip() for c in cells[1:] if c.strip()]
    if not rest:
        return False
    has_year = any(re.fullmatch(r"20\d{2}", c) for c in rest)
    has_scale = any(
        c.lower().strip("()") in {"in thousands", "in millions", "in billions"}
        for c in rest
    )
    # Detect date fragments: "September 30," or "December 31,"
    has_date_fragment = any(_MONTH_NAME_RE.match(c) for c in rest)
    # Detect period indicators: "Three Months Ended", "Nine Months Ended"
    has_period_indicator = any(_PERIOD_INDICATOR_RE.match(c) for c in rest)
    return has_year or has_scale or has_date_fragment or has_period_indicator


def _parse_markdown_table(table_text: str) -> Tuple[List[str], List[List[str]]]:
    """Parse a markdown table into headers and rows.

    Supports double-header tables where the first data row after the separator
    contains year identifiers (e.g. "| | 2024 | | 2023 | |").
    In that case, the sub-header years are merged into the header row.
    """
    lines = [
        line.strip()
        for line in table_text.strip().splitlines()
        if line.strip()
    ]

    if len(lines) < 3:  # header + separator + at least 1 data row
        return [], []

    # Parse header
    header_line = lines[0]
    headers = [
        cell.strip() for cell in header_line.strip("|").split("|")
    ]

    # Skip separator line (lines[1])

    # Parse data rows
    raw_rows: List[List[str]] = []
    for line in lines[2:]:
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            raw_rows.append(cells)

    # Double-header support: consume consecutive sub-header rows and merge
    # their content into ``headers``.  This handles 10-Q tables where headers
    # span 2-3 rows, e.g.:
    #   Row 0 (header):     | | Three Months Ended | | Nine Months Ended |
    #   Row 1 (sub-header): | | September 30, | | September 30, |
    #   Row 2 (sub-header): | | 2025 | | 2024 | | 2025 | | 2024 |
    rows = raw_rows
    while rows and _is_subheader_row(rows[0]):
        sub = rows[0]
        for idx in range(min(len(headers), len(sub))):
            sub_val = sub[idx].strip()
            if not sub_val:
                continue
            hdr_val = headers[idx].strip()
            if hdr_val:
                # Concatenate: "Three Months Ended" + " " + "September 30,"
                headers[idx] = f"{hdr_val} {sub_val}"
            else:
                headers[idx] = sub_val
        rows = rows[1:]

    return headers, rows


_MONTH_TO_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _date_to_period(month_num: int, year: str,
                    fiscal_year_end_month: int = 12) -> str:
    """Map a month/year to a period label.

    If the month matches the fiscal year end, returns FY{year}.
    Otherwise returns Q{quarter}-{year}.
    """
    if month_num == fiscal_year_end_month:
        return f"FY{year}"
    q = (month_num - 1) // 3 + 1
    return f"Q{q}-{year}"


def _identify_period_columns(
    headers: List[str],
    fiscal_year_end_month: int = 12,
) -> Dict[int, str]:
    """Map column indices to period identifiers.

    E.g. headers = ["", "2024", "2023", "2022"]
    Returns {1: "FY2024", 2: "FY2023", 3: "FY2022"}

    Standalone dates like "September 30, 2025" are mapped to their quarter
    (Q3-2025) unless the month matches fiscal_year_end_month (default 12).
    """
    period_map: Dict[int, str] = {}
    for idx, header in enumerate(headers):
        header_clean = header.strip()
        if not header_clean:
            continue

        # "Year Ended December 31, 2024" -> FY2024
        m = re.search(
            r"(?:year\s+ended|fiscal\s+year)\s+.*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            period_map[idx] = f"FY{m.group(1)}"
            continue

        # "Three Months Ended Sep 30, 2024" -> Q3-2024
        m = re.search(
            r"three\s+months?\s+ended\s+([A-Za-z]+).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_num = _MONTH_TO_NUM.get(m.group(1).lower(), 0)
            if month_num:
                q = (month_num - 1) // 3 + 1
                period_map[idx] = f"Q{q}-{m.group(2)}"
                continue

        # "Nine Months Ended September 30, 2024" -> 9M-2024
        m = re.search(
            r"nine\s+months?\s+ended\s+([A-Za-z]+).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            period_map[idx] = f"9M-{m.group(2)}"
            continue

        # "Six Months Ended June 30, 2024" -> H1-2024
        m = re.search(
            r"six\s+months?\s+ended\s+([A-Za-z]+).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_num = _MONTH_TO_NUM.get(m.group(1).lower(), 0)
            if month_num:
                half = 1 if month_num <= 6 else 2
                period_map[idx] = f"H{half}-{m.group(2)}"
                continue

        # Standalone date: "September 30, 2025" or "December 31, 2024"
        # Maps to quarter or FY depending on fiscal_year_end_month.
        m = re.search(
            r"(January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+\d{1,2},?\s+(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_num = _MONTH_TO_NUM.get(m.group(1).lower(), 0)
            if month_num:
                period_map[idx] = _date_to_period(
                    month_num, m.group(2), fiscal_year_end_month
                )
                continue

        # Simple year: "2024"
        m = re.fullmatch(r"\s*(20\d{2})\s*", header_clean)
        if m:
            period_map[idx] = f"FY{m.group(1)}"
            continue

        # "Q3 2024" or "Q3-2024"
        m = re.search(r"Q([1-4])[\s-]?(\d{4})", header_clean, re.IGNORECASE)
        if m:
            period_map[idx] = f"Q{m.group(1)}-{m.group(2)}"
            continue

    return period_map


def extract_from_markdown_table(
    table_text: str, section_name: str = "", table_idx: int = 0
) -> List[TableField]:
    """Extract field-value pairs from a single markdown table.

    Args:
        table_text: Raw markdown table text.
        section_name: Section/sub-section label for source_location.
        table_idx: Zero-based index of this table within the file (global counter).

    Returns list of TableField with label, value, and period info.
    """
    headers, rows = _parse_markdown_table(table_text)
    if not headers or not rows:
        return []

    period_map = _identify_period_columns(headers)
    if not period_map:
        # Try: first column is label, second is value (no period headers)
        if len(headers) >= 2:
            period_map = {1: "unknown"}

    results: List[TableField] = []

    # ── Percentage-table filter ──────────────────────────────────────
    # Skip tables that are pure percentage breakdowns (e.g. MD&A common-
    # size IS with "100.0 %", "12.5", etc.).  Detected when ≥2 data rows
    # contain a standalone "%" cell AND no row contains a "$" marker.
    # The "$" exception keeps mixed tables (monetary + margin columns)
    # alive — the dollar-column calibration below ensures the period map
    # points at the monetary columns, and the per-row "%" skip (below)
    # filters individual percentage rows.
    pct_row_count = sum(
        1 for r in rows
        if any(c.strip() == "%" for c in r[1:])
    )
    has_dollar_any = any(
        cell.strip() == "$" for r in rows for cell in r[1:]
    )
    if pct_row_count >= 2 and not has_dollar_any:
        return []

    # ── Dollar-column calibration (mixed pct/monetary tables only) ───
    # Some filings (e.g. IFRS 20-F) embed a "% of revenue" sub-column
    # next to each monetary sub-column under the same period header.
    # The header-based period detection may land on the percentage sub-
    # column, while the actual monetary data is offset to a "$"-marked
    # column.  For rows WITH "$" markers, the row-level calibration
    # below handles this.  For rows WITHOUT "$", the sparse-scan would
    # pick up the percentage value instead of the monetary one.
    #
    # Guard: only apply when the table is confirmed as mixed (≥2 pct
    # rows AND has "$" markers), so pure monetary tables (GCT, TZOO)
    # are never affected.
    if pct_row_count >= 2 and has_dollar_any and period_map and rows:
        from collections import Counter
        dollar_signatures: Counter = Counter()
        for _probe_row in rows:
            dcols = tuple(
                i for i, cell in enumerate(_probe_row[1:], start=1)
                if cell.strip() == "$"
            )
            if dcols and len(dcols) == len(period_map):
                dollar_signatures[dcols] += 1
        if dollar_signatures:
            best_sig, best_count = dollar_signatures.most_common(1)[0]
            # Only recalibrate if ≥2 rows agree AND positions differ
            # from the current header-based period_map
            if best_count >= 2 and set(best_sig) != set(period_map.keys()):
                sorted_periods = sorted(
                    period_map.items(), key=lambda x: x[0]
                )
                period_map = {
                    dc: pk
                    for dc, (_, pk) in zip(best_sig, sorted_periods)
                }

    # Track last section-heading row for parent-label concatenation.
    # Heading rows have a non-empty label but no numeric data cells.
    last_heading = ""

    for row_idx, row in enumerate(rows):
        if not row:
            continue
        label = row[0].strip() if row else ""
        if not label:
            continue

        # Skip header-like rows (all text, no numbers) — but track as heading
        has_number = any(
            parse_number(cell) is not None for cell in row[1:]
        )
        if not has_number:
            last_heading = label
            continue

        # Parent-label concatenation: if label starts with an em-dash or
        # en-dash sub-label marker (e.g. "—Basic", "—Diluted"), prepend
        # the last section heading for context.  This turns:
        #   heading: "Net income per ordinary share"
        #   sub-label: "—Basic"
        # into: "Net income per ordinary share—Basic", which resolves via
        # the alias table to eps_basic.
        if label.startswith(("\u2014", "\u2013")) and last_heading:
            label = f"{last_heading}{label}"

        # Skip percentage rows: if any data cell contains "%", skip entire row.
        # This avoids extracting margin/ratio tables as monetary values.
        data_cells = row[1:]
        if any("%" in cell for cell in data_cells):
            continue

        # Row-level period column adjustment for $-annotated rows.
        # EDGAR tables often have sub-header years at positions that
        # don't match the actual data columns.  When a data row has
        # "$" markers whose count equals the number of detected periods,
        # use the "$" positions as the real period column starts.
        row_period_map = period_map
        dollar_cols = [
            i for i, cell in enumerate(row[1:], start=1)
            if cell.strip() == "$"
        ]
        if dollar_cols and len(dollar_cols) == len(period_map):
            sorted_periods = sorted(period_map.items(), key=lambda x: x[0])
            candidate = {
                dc: pk for dc, (_, pk) in zip(dollar_cols, sorted_periods)
            }
            if candidate != period_map:
                row_period_map = candidate

        for col_idx, period_key in row_period_map.items():
            if col_idx >= len(row):
                continue

            cell_text = row[col_idx].strip()
            value = parse_number(cell_text)

            # Sparse-column scan: if cell has no numeric value (empty,
            # currency symbol like "$", or stray closing paren from split-
            # paren negatives), scan forward through subsequent columns
            # until we find a number or hit another period column.
            # This handles EDGAR tables where each period spans multiple
            # columns: | $ | 83,902 | | | $ | 84,477 | |
            if value is None and re.fullmatch(r"[$€£¥)]?", cell_text):
                for scan_idx in range(col_idx + 1, len(row)):
                    if scan_idx in row_period_map and scan_idx != col_idx:
                        break  # Don't cross into another period's columns
                    scan_text = row[scan_idx].strip()
                    scan_val = parse_number(scan_text)
                    if scan_val is not None:
                        value = scan_val
                        break
                    # Dash-as-zero inside sparse scan: a dash in
                    # a period's span means 0, not "no data".
                    if scan_text in {"\u2014", "\u2013", "-"}:
                        value = 0.0
                        break

            # Dash-as-zero: if the period column itself contains a
            # dash, treat as 0.  Handles rows like
            # "Long-term debt | - | 99,072" where "-" means zero.
            if value is None and cell_text in {"\u2014", "\u2013", "-"}:
                value = 0.0

            if value is not None:
                location = f"table:{section_name}:tbl{table_idx}:row{row_idx + 1}:col{col_idx}"
                results.append(
                    TableField(
                        label=label,
                        value=value,
                        column_header=period_key,
                        source_location=location,
                    )
                )

    return results


def extract_tables_from_clean_md(
    clean_md_text: str, source_filename: str = ""
) -> List[TableField]:
    """Extract all fields from a .clean.md file containing financial tables.

    Splits by section headings, processes each table, returns all fields.
    Uses ### sub-sections within each ## section for finer-grained context.
    """
    all_fields: List[TableField] = []

    # Global table counter across the entire file — ensures every table
    # gets a unique tbl index regardless of section/subsection boundaries.
    global_tbl_idx = 0

    # Split by section (## SECTION NAME)
    section_pattern = re.compile(
        r"^##\s+(.+?)$", re.MULTILINE
    )
    subsection_pattern = re.compile(
        r"^###\s+(.+?)$", re.MULTILINE
    )
    sections = section_pattern.split(clean_md_text)

    # sections alternates: [pre-text, section_name, section_content, ...]
    current_section = ""
    for i, part in enumerate(sections):
        if i % 2 == 1:
            current_section = part.strip().lower().replace(" ", "_")
            continue

        # Further split by ### sub-sections within this ## section
        sub_parts = subsection_pattern.split(part)
        current_subsection = ""
        for j, sub_part in enumerate(sub_parts):
            if j % 2 == 1:
                current_subsection = sub_part.strip().lower().replace(" ", "_")
                continue

            section_label = current_section
            if current_subsection:
                section_label = f"{current_section}:{current_subsection}"

            # Find markdown tables in this sub-part
            table_blocks = re.findall(
                r"((?:^\|.+\|$\n?)+)",
                sub_part,
                re.MULTILINE,
            )

            for table_text in table_blocks:
                fields = extract_from_markdown_table(table_text, section_label, table_idx=global_tbl_idx)
                global_tbl_idx += 1
                for f in fields:
                    f.source_location = (
                        f"{source_filename}:{f.source_location}"
                        if source_filename
                        else f.source_location
                    )
                all_fields.extend(fields)

    return all_fields
