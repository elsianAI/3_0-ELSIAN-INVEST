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
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|"
    r"Oct|Nov|Dec)\.?\s+\d{1,2},?\s*(?:\d{4})?$",
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
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


def _resolve_month(token: str) -> int:
    """Normalize a month token and return its number, or 0 if unknown."""
    return _MONTH_TO_NUM.get(token.lower().rstrip("."), 0)


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
    filing_type: str = "",
) -> Dict[int, str]:
    """Map column indices to period identifiers.

    E.g. headers = ["", "2024", "2023", "2022"]
    Returns {1: "FY2024", 2: "FY2023", 3: "FY2022"}

    Standalone dates like "September 30, 2025" are mapped to their quarter
    (Q3-2025) unless the month matches fiscal_year_end_month (default 12).

    When filing_type is an annual filing (10-K, 20-F, annual_report) and
    there is no sub-period context in the headers, standalone-date Q labels
    are upgraded to FY.
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
            r"three\s+months?\s+ended\s+([A-Za-z]+\.?).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_num = _resolve_month(m.group(1))
            if month_num:
                q = (month_num - 1) // 3 + 1
                period_map[idx] = f"Q{q}-{m.group(2)}"
                continue

        # "Nine Months Ended September 30, 2024" -> 9M-2024
        m = re.search(
            r"nine\s+months?\s+ended\s+([A-Za-z]+\.?).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            period_map[idx] = f"9M-{m.group(2)}"
            continue

        # "Six Months Ended June 30, 2024" -> H1-2024
        m = re.search(
            r"six\s+months?\s+ended\s+([A-Za-z]+\.?).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_num = _resolve_month(m.group(1))
            if month_num:
                half = 1 if month_num <= 6 else 2
                period_map[idx] = f"H{half}-{m.group(2)}"
                continue

        # "Quarters Ended Dec. 31, 2019" -> Q4-2019
        m = re.search(
            r"quarters?\s+ended\s+([A-Za-z]+\.?).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_num = _resolve_month(m.group(1))
            if month_num:
                q = (month_num - 1) // 3 + 1
                period_map[idx] = f"Q{q}-{m.group(2)}"
                continue

        # Standalone date: "September 30, 2025", "Dec. 31, 2024"
        # Maps to quarter or FY depending on fiscal_year_end_month.
        m = re.search(
            r"(January|February|March|April|May|June|July|August|September|"
            r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|"
            r"Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_num = _resolve_month(m.group(1))
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

    # ── Annual-context upgrade ───────────────────────────────────────
    # When a table header row contains "Year Ended" or "Fiscal Year"
    # (typically a colspan in HTML that only survives in the first
    # column after Markdown conversion), standalone-date columns
    # mapped to Q labels should be upgraded to FY.  This handles
    # non-standard fiscal year ends (e.g. September/October for SONO).
    # Columns explicitly labelled "Three Months Ended" etc. are excluded.
    #
    # Also activates for annual filings (10-K, 20-F) when the table has
    # no sub-period headers at all, covering BS tables with only
    # standalone dates.
    _ANNUAL_FILING_TYPES = {"10-K", "20-F", "annual_report"}
    annual_context = any(
        re.search(r"year\s+ended|fiscal\s+year", h, re.IGNORECASE)
        for h in headers
    )
    if not annual_context and filing_type in _ANNUAL_FILING_TYPES:
        _SUB_PERIOD_HDR_RE = re.compile(
            r"three\s+months?|six\s+months?|nine\s+months?|quarters?\s+ended",
            re.IGNORECASE,
        )
        has_sub_period = any(_SUB_PERIOD_HDR_RE.search(h) for h in headers)
        if not has_sub_period:
            annual_context = True
    if annual_context:
        _SUB_PERIOD_RE = re.compile(
            r"three\s+months?|six\s+months?|nine\s+months?|quarters?\s+ended",
            re.IGNORECASE,
        )
        for idx in list(period_map.keys()):
            pk = period_map[idx]
            m_q = re.match(r"Q\d-(20\d{2})", pk)
            if m_q:
                hdr = headers[idx] if idx < len(headers) else ""
                if not _SUB_PERIOD_RE.search(hdr):
                    period_map[idx] = f"FY{m_q.group(1)}"

    return period_map


def extract_from_markdown_table(
    table_text: str, section_name: str = "", table_idx: int = 0,
    filing_type: str = "",
) -> List[TableField]:
    """Extract field-value pairs from a single markdown table.

    Args:
        table_text: Raw markdown table text.
        section_name: Section/sub-section label for source_location.
        table_idx: Zero-based index of this table within the file (global counter).
        filing_type: e.g. "10-K", "10-Q", "20-F" — used for annual-context period detection.

    Returns list of TableField with label, value, and period info.
    """
    headers, rows = _parse_markdown_table(table_text)
    if not headers or not rows:
        return []

    period_map = _identify_period_columns(headers, filing_type=filing_type)
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

    # ── Numeric-anchor calibration for sparse headers ─────────────
    # When period columns in the header row are sparse (gap >= 2 between
    # adjacent periods), the data values often sit at DIFFERENT columns
    # than the header years.  E.g.:
    #   header: | _ | 2025 | _ | 2024 | _ | 2023 | _ | _ | _ | _ |
    #   data:   | lbl | _ | val | _ | _ | val | _ | _ | val | _ |
    # Header years at [1,3,5], data at [2,5,8].  Without recalibration,
    # col5 (FY2023 by header) picks up FY2024's value.
    #
    # Fix: scan data rows for numeric column positions.  When >=3 rows
    # agree on a consistent N-column pattern (N = number of periods) that
    # differs from the header columns, recalibrate period_map.
    _pcols_sorted = sorted(period_map.keys())
    _min_gap = min(
        (_pcols_sorted[i + 1] - _pcols_sorted[i]
         for i in range(len(_pcols_sorted) - 1)),
        default=1,
    )
    _sparse_header = _min_gap >= 2
    if _sparse_header and period_map and rows and len(period_map) >= 2:
        from collections import Counter as _AnchorCounter
        _num_patterns: _AnchorCounter = _AnchorCounter()
        for _pr in rows:
            _ncols = tuple(
                i for i, cell in enumerate(_pr[1:], start=1)
                if parse_number(cell.strip()) is not None
            )
            if len(_ncols) == len(period_map):
                _num_patterns[_ncols] += 1
        if _num_patterns:
            _best_np, _best_nc = _num_patterns.most_common(1)[0]
            _sorted_periods = sorted(
                period_map.items(), key=lambda x: x[0]
            )
            _sorted_hcols = [c for c, _ in _sorted_periods]
            _max_drift = max(
                abs(nc - hc)
                for nc, hc in zip(_best_np, _sorted_hcols)
            )
            if (
                _best_nc >= 3
                and set(_best_np) != set(period_map.keys())
                and all(
                    _best_np[i] < _best_np[i + 1]
                    for i in range(len(_best_np) - 1)
                )
                and _max_drift <= 3
                # Boundary-crossing check: only recalibrate when at
                # least one data column sits AT or PAST the NEXT
                # period's header column.  This distinguishes cases
                # where the sparse scan would silently fail (TALO:
                # data at col5 = header col5 for a DIFFERENT period)
                # from cases where data is between headers and the
                # sparse scan bridges the gap correctly (GCT CF:
                # data at col4, next header at col5).
                and any(
                    _best_np[i] >= _sorted_hcols[i + 1]
                    for i in range(len(_sorted_hcols) - 1)
                )
            ):
                period_map = {
                    nc: pk
                    for nc, (_, pk) in zip(_best_np, _sorted_periods)
                }

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
    # rows AND has "$" markers), so pure monetary tables are never
    # affected by this secondary calibration.
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
        #
        # Also handles bare generic sub-labels ("Basic", "Diluted") under
        # a heading containing "per share" — these are EPS rows that lack
        # the em-dash prefix common in other filings.  The heading is
        # truncated at "per share" to keep the concatenated label short
        # enough for fuzzy alias matching.
        if label.startswith(("\u2014", "\u2013")) and last_heading:
            label = f"{last_heading}{label}"
        elif (
            last_heading
            and re.search(r"per\s+share", last_heading, re.IGNORECASE)
            and not re.search(
                r"shares\s+(?:used|of\s+common|outstanding)",
                last_heading, re.IGNORECASE,
            )
            and label.lower() in {"basic", "diluted", "basic and diluted"}
        ):
            m_ps = re.search(
                r"(.*?\bper\s+share)\b", last_heading, re.IGNORECASE
            )
            prefix = m_ps.group(1) if m_ps else last_heading
            label = f"{prefix}\u2014{label}"

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
    clean_md_text: str, source_filename: str = "",
    filing_type: str = "",
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
                fields = extract_from_markdown_table(
                    table_text, section_label,
                    table_idx=global_tbl_idx,
                    filing_type=filing_type,
                )
                global_tbl_idx += 1
                for f in fields:
                    f.source_location = (
                        f"{source_filename}:{f.source_location}"
                        if source_filename
                        else f.source_location
                    )
                all_fields.extend(fields)

    return all_fields


# ── Space-aligned table parser (for pdfplumber .txt output) ──────────

# Regex for a number token (possibly negative, possibly with commas)
_NUM_TOKEN_RE = re.compile(
    r"-?\d[\d,]*(?:\.\d+)?|"            # -1,234 or 1,234.56 (must have ≥1 digit)
    r"\(-?\d[\d,]*(?:\.\d+)?\)|"        # (1,234)
    r"−\d[\d,]*(?:\.\d+)?",             # −1,234 (unicode minus)
)

# Regex matching a year like 2025, 2024, etc.
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Regex matching a date-headed column like 12/31/2025
_DATE_COL_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/(20\d{2}))\b")

# Header patterns for financial statement sections
_SECTION_HEADER_RE = re.compile(
    r"(?:CONSOLIDATED\s+)?(?:INCOME\s+STATEMENTS?|BALANCE\s+SHEETS?|"
    r"CASH\s+FLOW\s+STATEMENTS?|STATEMENTS?\s+OF\s+(?:FINANCIAL\s+POSITION|"
    r"INCOME|OPERATIONS|CASH[-\s]?FLOWS?|"
    r"COMPREHENSIVE\s+(?:INCOME|LOSS))|"
    r"FINANCIAL\s+HIGHLIGHTS|KEY\s+(?:FINANCIAL\s+)?(?:DATA|FIGURES))",
    re.IGNORECASE,
)

# Section-type detection for source_location tagging
_IS_KEYWORDS = re.compile(
    r"INCOME\s+STATEMENTS?|STATEMENTS?\s+OF\s+(?:OPERATIONS|INCOME)|PROFIT\s+(?:AND|OR)\s+LOSS",
    re.IGNORECASE,
)
_BS_KEYWORDS = re.compile(
    r"BALANCE\s+SHEETS?|FINANCIAL\s+POSITION",
    re.IGNORECASE,
)
_CF_KEYWORDS = re.compile(
    r"CASH\s+FLOW|CASH[-\s]?FLOWS?",
    re.IGNORECASE,
)


def _detect_section_type(header: str) -> str:
    """Classify a section header into IS/BS/CF."""
    if _IS_KEYWORDS.search(header):
        return "income_statement"
    if _BS_KEYWORDS.search(header):
        return "balance_sheet"
    if _CF_KEYWORDS.search(header):
        return "cash_flow"
    return "unknown"


def _find_number_columns(lines: List[str]) -> List[int]:
    """Find consistent numeric column end-positions across multiple lines.

    Returns list of end-position anchors for value columns, sorted left-to-right.
    Each anchor is the position with the most hits within a cluster of
    right-aligned numbers.
    """
    from collections import Counter

    # Collect end-positions of all number tokens across lines
    end_positions: Counter = Counter()
    for line in lines:
        for m in _NUM_TOKEN_RE.finditer(line):
            end_positions[m.end()] += 1

    if not end_positions:
        return []

    # Cluster nearby end-positions (within 3 chars) — tight threshold to
    # keep columns that are only ~6-8 chars apart separate.
    sorted_positions = sorted(end_positions.keys())
    clusters: List[List[int]] = []
    current_cluster: List[int] = [sorted_positions[0]]

    for pos in sorted_positions[1:]:
        if pos - current_cluster[-1] <= 3:
            current_cluster.append(pos)
        else:
            clusters.append(current_cluster)
            current_cluster = [pos]
    clusters.append(current_cluster)

    # Keep clusters with enough hits (>=3 data lines)
    result: List[int] = []
    for cluster in clusters:
        total_hits = sum(end_positions[p] for p in cluster)
        if total_hits >= 3:
            # Pick the position with most hits
            best_pos = max(cluster, key=lambda p: end_positions[p])
            result.append(best_pos)

    return sorted(result)


def _guided_anchors_from_headers(
    data_lines: List[str], header_end_positions: List[int],
) -> List[int]:
    """Derive data-aligned column anchors guided by header end-positions.

    Raw header positions often don't coincide with data number end-positions
    (headers are centered or right-aligned differently from data).  Instead
    of using headers directly as anchors (which causes mis-assignment),
    partition the position space at midpoints between consecutive headers
    and pick the strongest data end-position in each partition.
    """
    from collections import Counter as _Counter

    end_positions: _Counter = _Counter()
    for line in data_lines:
        for m in _NUM_TOKEN_RE.finditer(line):
            end_positions[m.end()] += 1

    if not end_positions:
        return list(header_end_positions)

    n = len(header_end_positions)

    # Midpoints between consecutive headers define partition boundaries
    midpoints: List[float] = []
    for i in range(n - 1):
        midpoints.append(
            (header_end_positions[i] + header_end_positions[i + 1]) / 2.0
        )

    anchors: List[int] = []
    for i in range(n):
        lo = midpoints[i - 1] if i > 0 else -1e9
        hi = midpoints[i] if i < len(midpoints) else 1e9

        # Candidates: data positions within this partition with >= 2 hits
        candidates = [
            (pos, cnt)
            for pos, cnt in end_positions.items()
            if pos > lo and pos <= hi and cnt >= 2
        ]

        if not candidates:
            # No strong candidates: fall back to raw header position
            anchors.append(header_end_positions[i])
            continue

        # Best = most hits; tiebreak by proximity to header
        best = max(
            candidates,
            key=lambda pc: (pc[1], -abs(pc[0] - header_end_positions[i])),
        )
        anchors.append(best[0])

    return sorted(anchors)


def _extract_value_at_column(
    line: str, col_anchor: int, all_anchors: List[int],
) -> Optional[float]:
    """Extract the numeric value from a line closest to a column anchor.

    Uses nearest-number assignment: each number token on the line is assigned
    to the closest column anchor, and we return the one assigned to col_anchor.
    """
    matches = list(_NUM_TOKEN_RE.finditer(line))
    if not matches:
        # Check for dash-as-zero near the column
        # Look in a window around the anchor
        window_start = max(0, col_anchor - 10)
        window_end = min(len(line), col_anchor + 3)
        segment = line[window_start:window_end].strip()
        if segment in {"—", "–", "-"}:
            return 0.0
        return None

    # Assign each match to its nearest anchor
    best_match = None
    best_dist = float("inf")
    for m in matches:
        m_end = m.end()
        dist = abs(m_end - col_anchor)
        # Check this is closest to OUR anchor, not another one
        closest_anchor = min(all_anchors, key=lambda a: abs(m_end - a))
        if closest_anchor == col_anchor and dist < best_dist:
            best_dist = dist
            best_match = m

    if best_match is None:
        return None

    return parse_number(best_match.group())


def _extract_space_aligned_table(
    lines: List[str],
    section_name: str,
    table_idx: int,
    period_headers: Dict[int, str],
    col_anchors: List[int],
    source_filename: str,
) -> List[TableField]:
    """Extract fields from a block of space-aligned table lines."""
    results: List[TableField] = []

    for row_idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Find all number tokens on this line
        num_matches = list(_NUM_TOKEN_RE.finditer(line))
        if not num_matches:
            continue

        # The label is everything before the first number
        first_num_start = num_matches[0].start()
        label = line[:first_num_start].strip()
        if not label:
            continue

        # Skip lines that look like headers/section dividers
        if label.startswith("---") or label.startswith("==="):
            continue
        if _SECTION_HEADER_RE.match(label):
            continue
        # Skip lines that are just scale indicators
        if label.lower().strip("()€$ ") in {
            "in millions of euros", "in millions", "millions",
            "in thousands", "in billions", "€ millions",
        }:
            continue

        # Extract values at each column position
        extracted: Dict[int, Optional[float]] = {}
        for col_idx, anchor in enumerate(col_anchors):
            if col_idx not in period_headers:
                continue
            extracted[col_idx] = _extract_value_at_column(
                line, anchor, col_anchors,
            )

        # Fallback: when position-based assignment leaves columns empty
        # and the line has exactly N numbers matching N columns, use
        # left-to-right ordering (handles long-label lines where numbers
        # are shifted to the right of their expected positions).
        assigned_count = sum(1 for v in extracted.values() if v is not None)
        active_cols = [ci for ci in extracted]
        if (
            assigned_count < len(active_cols)
            and len(num_matches) == len(active_cols)
        ):
            for i, ci in enumerate(active_cols):
                v = parse_number(num_matches[i].group())
                if v is not None:
                    extracted[ci] = v

        for col_idx, value in extracted.items():
            if value is not None:
                period_key = period_headers[col_idx]
                location = (
                    f"{source_filename}:table:{section_name}:"
                    f"tbl{table_idx}:row{row_idx + 1}:col{col_idx}"
                )
                results.append(
                    TableField(
                        label=label,
                        value=value,
                        column_header=period_key,
                        source_location=location,
                    )
                )

    return results


def extract_tables_from_text(
    text: str, source_filename: str = "",
) -> List[TableField]:
    """Extract fields from space-aligned tables in plain text (pdfplumber output).

    Detects financial statement sections, identifies column positions from
    number alignment, and extracts label/value pairs with period assignment.
    """
    all_fields: List[TableField] = []
    lines = text.split("\n")

    # Detect parent-company financial statements zone: find the actual
    # section header (e.g. "5.2. Parent company financial statements") as
    # opposed to passing mentions in paragraphs.  We look for a standalone
    # line that is clearly a section header (section number + "parent company").
    # TOC entries (ending with a page number) are excluded.
    _PC_SECTION_RE = re.compile(
        r"^\d+\.\d+\.?\s+(?:parent\s+company|comptes\s+sociaux)"
        r"|^Schedule\s+I[.\s\u2014\u2013-]",
        re.IGNORECASE,
    )
    parent_company_zone_start = len(lines)  # default: no zone
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _PC_SECTION_RE.match(stripped):
            # Skip TOC entries that end with a page number
            if re.search(r"\b\d{1,4}\s*$", stripped):
                continue
            # Skip TOC entries where the next 1-2 lines contain a page
            # reference like "F-\n43" (SEC filing index format).
            is_toc_entry = False
            for offset in range(1, 3):
                if i + offset < len(lines):
                    next_stripped = lines[i + offset].strip()
                    if re.match(r"^[A-Z]-\s*\d*$", next_stripped):
                        is_toc_entry = True
                        break
            if is_toc_entry:
                continue
            parent_company_zone_start = i
            break

    # Detect notes zone: IFRS URDs have a "Notes to the consolidated
    # financial statements" section containing thousands of lines of
    # accounting policy descriptions that mention "balance sheet",
    # "income statement", etc. — these must NOT be parsed as tables.
    _NOTES_SECTION_RE = re.compile(
        r"^\d+\.\d+\.\d*\.?\s+notes\s+to\s+the\s+consolidated",
        re.IGNORECASE,
    )
    notes_zone_start = len(lines)  # default: no zone
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _NOTES_SECTION_RE.match(stripped):
            if re.search(r"\b\d{1,4}\s*$", stripped):
                continue  # Skip TOC entries
            notes_zone_start = i
            break

    # Use the earlier of the two exclusion zones
    exclusion_zone_start = min(parent_company_zone_start, notes_zone_start)

    # Find section boundaries: look for financial statement headers
    sections: List[Tuple[int, str, str]] = []  # (line_idx, header_text, section_type)
    for i, line in enumerate(lines):
        stripped = line.strip()
        m = _SECTION_HEADER_RE.search(stripped)
        if not m or len(stripped) > 120:
            continue
        # Require the match to start near the beginning of the line
        # (real headers have the keyword within the first ~15 chars;
        # notes paragraphs mention these terms much further in).
        if m.start() > 15:
            continue
        # Skip everything in the exclusion zones (notes + parent company)
        if i >= exclusion_zone_start:
            continue
        # Secondary check: skip if "parent company" appears in nearby context
        context_start = max(0, i - 20)
        context = " ".join(lines[j].lower() for j in range(context_start, i))
        if "parent company" in context or "comptes sociaux" in context:
            continue
        section_type = _detect_section_type(stripped)
        sections.append((i, stripped, section_type))

    # Secondary pass: detect headers split across two lines.
    # PDF-to-text conversion can break a word mid-line, producing
    # "CONSOLIDATED B\nALANCE SHEETS" instead of "CONSOLIDATED BALANCE
    # SHEETS".  Try joining consecutive non-empty lines (with and without
    # a separating space) and check the combined text.
    _existing_section_lines = {s[0] for s in sections}
    for i in range(1, len(lines)):
        if i >= exclusion_zone_start or (i - 1) >= exclusion_zone_start:
            continue
        prev_s = lines[i - 1].strip()
        curr_s = lines[i].strip()
        if not prev_s or not curr_s:
            continue
        # Skip if either line is already a detected section
        if (i - 1) in _existing_section_lines or i in _existing_section_lines:
            continue
        # Try concatenation without space (split word) and with space
        for combined in (prev_s + curr_s, prev_s + " " + curr_s):
            if len(combined) > 120:
                continue
            m = _SECTION_HEADER_RE.search(combined)
            if m and m.start() <= 15:
                context_start = max(0, i - 21)
                context = " ".join(
                    lines[j].lower() for j in range(context_start, i - 1)
                )
                if "parent company" in context or "comptes sociaux" in context:
                    break
                section_type = _detect_section_type(combined)
                sections.append((i - 1, combined, section_type))
                _existing_section_lines.add(i - 1)
                break

    # Re-sort sections by line number after adding split-header entries
    sections.sort(key=lambda s: s[0])

    if not sections:
        return []

    global_tbl_idx = 0

    for sec_idx, (start_line, header_text, section_type) in enumerate(sections):
        # Section ends at next section or end of file (max 120 lines)
        if sec_idx + 1 < len(sections):
            end_line = sections[sec_idx + 1][0]
        else:
            end_line = min(start_line + 120, len(lines))

        # Also stop at page separators (long dash sequences) to prevent
        # data from unrelated appendix tables being processed with wrong
        # column anchors.
        for check_idx in range(start_line + 1, end_line):
            if re.match(r"^-{20,}$", lines[check_idx].strip()):
                end_line = check_idx
                break

        # Stop at numbered sub-section headers (e.g. "5.1.5. Consolidated
        # statement of changes in equity") that indicate a new financial
        # statement the parser doesn't explicitly detect.  Skip the first
        # few lines to avoid matching the section's own header.
        for check_idx in range(start_line + 3, end_line):
            stripped_check = lines[check_idx].strip()
            if re.match(r"\d+\.\d+\.\d+\.?\s+\w", stripped_check):
                end_line = check_idx
                break

        section_lines = lines[start_line:end_line]

        # Find period headers within the section
        period_headers: Dict[int, str] = {}
        header_line_idx = -1
        header_end_positions: List[int] = []  # end positions of year/date headers

        for j, sline in enumerate(section_lines[:10]):  # Look in first 10 lines
            # Try date columns first: 12/31/2025  12/31/2024
            date_matches = list(_DATE_COL_RE.finditer(sline))
            if len(date_matches) >= 2:
                header_end_positions = []
                for dm_idx, dm in enumerate(date_matches):
                    year = dm.group(2)
                    month_day = dm.group(1).split("/")
                    month = int(month_day[0])
                    if month == 12:
                        period_headers[dm_idx] = f"FY{year}"
                    else:
                        q = (month - 1) // 3 + 1
                        period_headers[dm_idx] = f"Q{q}-{year}"
                    header_end_positions.append(dm.end())
                header_line_idx = j
                break

            # Try simple year columns: 2025    2024
            year_matches = list(_YEAR_RE.finditer(sline))
            # Filter to years that make sense (2019-2030) and are positioned
            # in the right half of the line (where data columns go)
            if len(year_matches) >= 2:
                # Check that years are in the data area (not in label text)
                label_area_end = len(sline) // 3  # rough: label takes first third
                data_years = [
                    ym for ym in year_matches
                    if ym.start() > label_area_end
                ]
                if len(data_years) >= 2:
                    header_end_positions = []
                    for dy_idx, dy in enumerate(data_years):
                        period_headers[dy_idx] = f"FY{dy.group(1)}"
                        header_end_positions.append(dy.end())
                    header_line_idx = j
                    break

        if not period_headers or header_line_idx < 0:
            continue

        # Data lines start after the header line
        data_lines = section_lines[header_line_idx + 1:]

        # Find column positions from number alignment
        col_anchors = _find_number_columns(data_lines[:50])
        if len(col_anchors) < len(period_headers):
            # Fallback: use header positions to derive data-aligned anchors
            if (
                header_end_positions
                and len(header_end_positions) == len(period_headers)
            ):
                col_anchors = _guided_anchors_from_headers(
                    data_lines[:50], header_end_positions,
                )
            else:
                continue

        # Match column anchors to period headers using header positions.
        if (
            header_end_positions
            and len(header_end_positions) == len(period_headers)
        ):
            if len(col_anchors) > len(period_headers):
                # More anchors than periods: proximity-match to header positions
                matched_anchors: List[int] = []
                used_anchors: set = set()
                for hpos in header_end_positions:
                    best = min(
                        (a for a in col_anchors if a not in used_anchors),
                        key=lambda a: abs(a - hpos),
                        default=None,
                    )
                    if best is not None:
                        matched_anchors.append(best)
                        used_anchors.add(best)
                if len(matched_anchors) == len(period_headers):
                    col_anchors = matched_anchors
                else:
                    col_anchors = col_anchors[:len(period_headers)]
            else:
                # Same number of anchors as periods: check alignment quality.
                # If anchors are far from headers (e.g. notes column detected
                # instead of a data column), use header positions directly.
                max_dist = max(
                    abs(col_anchors[i] - header_end_positions[i])
                    for i in range(len(period_headers))
                )
                if max_dist > 10:
                    col_anchors = _guided_anchors_from_headers(
                        data_lines[:50], header_end_positions,
                    )

        fields = _extract_space_aligned_table(
            data_lines,
            section_type,
            global_tbl_idx,
            period_headers,
            col_anchors,
            source_filename,
        )
        global_tbl_idx += 1
        all_fields.extend(fields)

    return all_fields
