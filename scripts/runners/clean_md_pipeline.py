#!/usr/bin/env python3
"""Unified clean.md generation pipeline for HTML/PDF/TXT financial filings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from clean_md_quality import evaluate_clean_md
except Exception:
    from scripts.runners.clean_md_quality import evaluate_clean_md


_PDF_SECTION_RULES: List[Tuple[str, int, List[re.Pattern[str]]]] = [
    (
        "INCOME STATEMENT",
        70_000,
        [
            re.compile(r"\b(?:consolidated\s+)?income\s+statement\b", re.IGNORECASE),
            re.compile(r"\bstatement\s+of\s+operations\b", re.IGNORECASE),
            re.compile(r"\bstatement\s+of\s+profit\s+or\s+loss\b", re.IGNORECASE),
            re.compile(r"\bcompte\s+de\s+r[ée]sultat\b", re.IGNORECASE),
            # V5.1 A4 — IFRS/European additions
            re.compile(r"\bconsolidated\s+statement\s+of\s+(?:comprehensive\s+)?income\b", re.IGNORECASE),
            re.compile(r"\br[ée]sultat\s+(?:net\s+)?consolid[ée]\b", re.IGNORECASE),
        ],
    ),
    (
        "BALANCE SHEET",
        70_000,
        [
            re.compile(r"\b(?:consolidated\s+)?balance\s+sheets?\b", re.IGNORECASE),
            re.compile(r"\bstatement\s+of\s+financial\s+position\b", re.IGNORECASE),
            re.compile(r"\bbilan\s+consolid[ée]\b", re.IGNORECASE),
            re.compile(r"\btotal\s+de\s+l[\’’]?\s*actif(?:s)?\b", re.IGNORECASE),
            re.compile(r"\btotal\s+du\s+passif(?:s)?\b", re.IGNORECASE),
            # V5.1 A4 — IFRS/European additions
            re.compile(r"\b[ée]tat\s+(?:consolid[ée]\s+)?de\s+la\s+situation\s+financi[èe]re\b", re.IGNORECASE),
            re.compile(r"\bsituation\s+financi[èe]re\s+consolid[ée]e\b", re.IGNORECASE),
        ],
    ),
    (
        "CASH FLOW",
        70_000,
        [
            re.compile(r"\b(?:consolidated\s+)?cash\s+flows?\b", re.IGNORECASE),
            re.compile(r"\bstatement\s+of\s+cash\s+flows?\b", re.IGNORECASE),
            re.compile(r"\bflux\s+de\s+tr[ée]sorerie\b", re.IGNORECASE),
            re.compile(r"\btableau\s+des\s+flux\s+de\s+tr[ée]sorerie\b", re.IGNORECASE),
            # V5.1 A4 — IFRS/European additions
            re.compile(r"\bconsolidated\s+statement\s+of\s+cash[\s-]?flows?\b", re.IGNORECASE),
            re.compile(r"\btableau\s+(?:consolid[ée]\s+)?des\s+flux\b", re.IGNORECASE),
        ],
    ),
    (
        "EQUITY",
        30_000,
        [
            re.compile(r"\bstatement\s+of\s+changes?\s+in\s+equity\b", re.IGNORECASE),
            re.compile(r"\bstatement\s+of\s+stockholders[‘’]?\s+equity\b", re.IGNORECASE),
            re.compile(r"\bcapitaux\s+propres\b", re.IGNORECASE),
            # V5.1 A4 — IFRS/European additions
            re.compile(r"\bconsolidated\s+statement\s+of\s+changes?\s+in\s+equity\b", re.IGNORECASE),
            re.compile(r"\bvariation\s+des\s+capitaux\s+propres\b", re.IGNORECASE),
            re.compile(r"\b[ée]tat\s+des\s+variations?\s+des\s+capitaux\s+propres\b", re.IGNORECASE),
        ],
    ),
]

_PDF_HARD_CAP = 220_000
_PDF_WINDOW_BEFORE = 500
_PDF_WINDOW_AFTER = 55_000
_PDF_MAX_WINDOWS_PER_SECTION = 2


def _resolve_html_extractor() -> Any:
    extract_financial_tables = None
    errors: List[str] = []
    try:
        from clean_md_extractor import extract_financial_tables as _extract_financial_tables

        extract_financial_tables = _extract_financial_tables
    except Exception as exc:
        errors.append(f"clean_md_extractor.extract_financial_tables: {exc!r}")
    if extract_financial_tables is None:
        try:
            from scripts.runners.clean_md_extractor import extract_financial_tables as _extract_financial_tables

            extract_financial_tables = _extract_financial_tables
        except Exception as exc:
            errors.append(f"scripts.runners.clean_md_extractor.extract_financial_tables: {exc!r}")
    if extract_financial_tables is None:
        raise RuntimeError("; ".join(errors) if errors else "clean_md HTML extractor import failed")
    return extract_financial_tables


def _normalize_pdf_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _merge_ranges(ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: item[0])
    merged: List[Tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _extract_section_chunk(text: str, patterns: List[re.Pattern[str]], budget: int) -> str:
    ranges: List[Tuple[int, int]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            start = max(0, match.start() - _PDF_WINDOW_BEFORE)
            end = min(len(text), match.end() + _PDF_WINDOW_AFTER)
            ranges.append((start, end))
            if len(ranges) >= _PDF_MAX_WINDOWS_PER_SECTION:
                break
        if len(ranges) >= _PDF_MAX_WINDOWS_PER_SECTION:
            break
    if not ranges:
        return ""
    chunks: List[str] = []
    for start, end in _merge_ranges(ranges):
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
    if not chunks:
        return ""
    merged = "\n\n".join(chunks)
    if len(merged) > budget:
        merged = merged[:budget] + "\n\n... [SECTION TRUNCATED at budget limit]"
    return merged


def _build_pdf_clean_md(source_path: Path, txt_content: str) -> str:
    text = _normalize_pdf_text(txt_content)
    sections: List[str] = []
    total_chars = 0
    for section_name, budget, patterns in _PDF_SECTION_RULES:
        chunk = _extract_section_chunk(text, patterns, budget)
        if not chunk:
            block = f"## {section_name}\n\n_Section not found in filing._\n"
        else:
            block = f"## {section_name}\n\n{chunk}\n"
        sections.append(block)
        total_chars += len(block)
        if total_chars >= _PDF_HARD_CAP:
            break

    assembled_parts = [
        f"# FINANCIAL STATEMENTS — {source_path.stem}",
        f"_Extracted from: {source_path.name}_",
        "_Extractor mode: pdf_text_",
        f"_Total chars: {total_chars:,}_",
        "",
        "\n\n".join(sections),
    ]
    assembled = "\n\n".join(assembled_parts)
    if len(assembled) > _PDF_HARD_CAP:
        assembled = assembled[:_PDF_HARD_CAP] + "\n\n... [HARD CAP REACHED]"
    return assembled


def _ensure_mode_header(clean_text: str, mode: str) -> str:
    if re.search(r"_Extractor mode:\s*[a-z_]+_", clean_text, re.IGNORECASE):
        return clean_text
    lines = clean_text.splitlines()
    insert_at = 1 if lines else 0
    lines.insert(insert_at, f"_Extractor mode: {mode}_")
    return "\n".join(lines)


def generate_clean_md(
    source_path: Path,
    txt_content: str,
    filing_type: str,
    source_id: str,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Generate clean.md content and metadata for a filing source."""
    ext = source_path.suffix.lower()
    meta: Dict[str, Any] = {
        "source_id": source_id,
        "source_path": str(source_path),
        "filing_type": filing_type,
        "mode": "unknown",
        "status": "SKIPPED",
        "reason": "",
        "input_chars": len(txt_content or ""),
        "output_chars": 0,
    }

    if ext in {".htm", ".html"}:
        meta["mode"] = "html_table"
        try:
            extract_financial_tables = _resolve_html_extractor()
            clean_text = extract_financial_tables(source_path)
        except Exception as exc:
            meta["status"] = "ERROR"
            meta["reason"] = f"HTML_EXTRACTOR_ERROR: {exc}"
            return None, meta
        if not clean_text:
            meta["status"] = "REJECTED_QUALITY"
            meta["reason"] = "HTML_EXTRACTOR_EMPTY_OR_LOW_QUALITY"
            return None, meta
        clean_text = _ensure_mode_header(clean_text, "html_table")
        quality = evaluate_clean_md(clean_text, mode="html_table")
        meta["quality"] = quality
        if not quality.get("useful"):
            meta["status"] = "REJECTED_QUALITY"
            meta["reason"] = str(quality.get("reason") or "LOW_QUALITY")
            return None, meta
        meta["status"] = "GENERATED"
        meta["reason"] = "OK"
        meta["output_chars"] = len(clean_text)
        return clean_text, meta

    if ext in {".pdf", ".txt"}:
        meta["mode"] = "pdf_text"
        normalized = _normalize_pdf_text(txt_content)
        meta["input_chars"] = len(normalized)
        if not normalized:
            meta["status"] = "REJECTED_QUALITY"
            meta["reason"] = "EMPTY_TEXT"
            return None, meta
        if normalized.startswith("[PDF original"):
            meta["status"] = "REJECTED_QUALITY"
            meta["reason"] = "PDF_PLACEHOLDER"
            return None, meta
        clean_text = _build_pdf_clean_md(source_path, normalized)
        quality = evaluate_clean_md(clean_text, mode="pdf_text")
        meta["quality"] = quality
        if not quality.get("useful"):
            meta["status"] = "REJECTED_QUALITY"
            meta["reason"] = str(quality.get("reason") or "LOW_QUALITY")
            return None, meta
        meta["status"] = "GENERATED"
        meta["reason"] = "OK"
        meta["output_chars"] = len(clean_text)
        return clean_text, meta

    meta["status"] = "SKIPPED"
    meta["reason"] = f"UNSUPPORTED_EXTENSION:{ext or 'none'}"
    return None, meta

