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


def _is_subheader_row(cells: List[str]) -> bool:
    """Check if a row is a sub-header containing year/period identifiers.

    Detects rows like: | | 2024 | | 2023 | | | |
    or: | | (In thousands) | | | | | |
    These appear as the first data row after the separator in double-header tables.
    """
    first_cell = cells[0].strip() if cells else ""
    if first_cell and not re.match(r"^\s*$", first_cell):
        return False
    # Check if any non-first cell contains a year or scale indicator
    rest = [c.strip() for c in cells[1:] if c.strip()]
    has_year = any(re.fullmatch(r"20\d{2}", c) for c in rest)
    has_scale = any(
        c.lower().strip("()") in {"in thousands", "in millions", "in billions"}
        for c in rest
    )
    return has_year or has_scale


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

    # Double-header support: if the first data row is a sub-header with years,
    # merge it into headers and remove from data rows.
    rows = raw_rows
    if rows and _is_subheader_row(rows[0]):
        sub = rows[0]
        # Merge: for each column, if sub has a year and header is empty/generic,
        # adopt the sub value as the header.
        for idx in range(min(len(headers), len(sub))):
            sub_val = sub[idx].strip()
            if sub_val and re.fullmatch(r"20\d{2}", sub_val):
                headers[idx] = sub_val
        rows = rows[1:]
        # Also skip a second sub-header row if it's a scale indicator like "(In thousands)"
        if rows and _is_subheader_row(rows[0]):
            rows = rows[1:]

    return headers, rows


def _identify_period_columns(
    headers: List[str],
) -> Dict[int, str]:
    """Map column indices to period identifiers.

    E.g. headers = ["", "2024", "2023", "2022"]
    Returns {1: "FY2024", 2: "FY2023", 3: "FY2022"}
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
            month_name = m.group(1).lower()
            month_map = {
                "january": 1, "february": 2, "march": 3, "april": 4,
                "may": 5, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12,
            }
            month_num = month_map.get(month_name, 0)
            if month_num:
                q = (month_num - 1) // 3 + 1
                period_map[idx] = f"Q{q}-{m.group(2)}"
                continue

        # "Six Months Ended June 30, 2024" -> H1-2024
        m = re.search(
            r"six\s+months?\s+ended\s+([A-Za-z]+).*?(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            month_name = m.group(1).lower()
            month_map = {
                "january": 1, "february": 2, "march": 3, "april": 4,
                "may": 5, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12,
            }
            month_num = month_map.get(month_name, 0)
            if month_num:
                half = 1 if month_num <= 6 else 2
                period_map[idx] = f"H{half}-{m.group(2)}"
                continue

        # "December 31, 2024" -> FY2024
        m = re.search(
            r"(January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+\d{1,2},?\s+(\d{4})",
            header_clean,
            re.IGNORECASE,
        )
        if m:
            period_map[idx] = f"FY{m.group(2)}"
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
        table_idx: Zero-based index of this table within its sub-section.

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

    # Pre-compile row-level ignore patterns
    _IGNORE_LABELS = [
        re.compile(r"total\s+liabilities\s+and\s+stockholders", re.I),
        re.compile(r"total\s+liabilities\s+and\s+shareholders", re.I),
        re.compile(r"total\s+liabilities\s+and\s+equity", re.I),
    ]

    for row_idx, row in enumerate(rows):
        if not row:
            continue
        label = row[0].strip() if row else ""
        if not label:
            continue

        # Skip rows whose label matches an aggregate we never want
        if any(pat.search(label) for pat in _IGNORE_LABELS):
            continue

        # Skip header-like rows (all text, no numbers)
        has_number = any(
            parse_number(cell) is not None for cell in row[1:]
        )
        if not has_number:
            continue

        # Skip percentage rows: if any data cell contains "%", skip entire row.
        # This avoids extracting margin/ratio tables as monetary values.
        data_cells = row[1:]
        if any("%" in cell for cell in data_cells):
            continue

        for col_idx, period_key in period_map.items():
            if col_idx >= len(row):
                continue

            cell_text = row[col_idx].strip()
            value = parse_number(cell_text)

            # Sparse-column scan: if cell has no numeric value (empty or
            # currency symbol like "$"), scan forward through subsequent
            # columns until we find a number or hit another period column.
            # This handles EDGAR tables where each period spans multiple
            # columns: | $ | 83,902 | | | $ | 84,477 | |
            if value is None and re.fullmatch(r"[$€£¥]?", cell_text):
                for scan_idx in range(col_idx + 1, len(row)):
                    if scan_idx in period_map and scan_idx != col_idx:
                        break  # Don't cross into another period's columns
                    scan_val = parse_number(row[scan_idx].strip())
                    if scan_val is not None:
                        value = scan_val
                        break

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
