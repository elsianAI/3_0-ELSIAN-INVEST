#!/usr/bin/env python3
"""Shared semantic quality gates for .clean.md content."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

CORE_SECTIONS = ("INCOME STATEMENT", "BALANCE SHEET", "CASH FLOW")
_MODE_HEADER_RE = re.compile(r"_Extractor mode:\s*([a-z_]+)_", re.IGNORECASE)
_TABLE_NUMERIC_ROW_RE = re.compile(r"^\|.*\d[\d,\.]*.*\|$", re.MULTILINE)
_NUMERIC_TOKEN_RE = re.compile(r"(?<!\w)[\(\-]?\$?\d[\d,]*(?:\.\d+)?%?\)?")

_PDF_FIN_HINTS = (
    "revenue",
    "net revenue",
    "income",
    "profit",
    "loss",
    "cash flow",
    "operating activities",
    "investing activities",
    "financing activities",
    "assets",
    "liabilities",
    "equity",
    "ebit",
    "ebitda",
    "capex",
    "chiffre d'affaires",
    "résultat net",
    "resultat net",
    "flux de trésorerie",
    "actifs",
    "passifs",
    "capitaux propres",
)


def detect_clean_md_mode(text: str) -> str:
    """Detect clean.md mode from explicit header or structural heuristics."""
    if not text:
        return "pdf_text"
    match = _MODE_HEADER_RE.search(text)
    if match:
        mode = match.group(1).lower().strip()
        if mode in {"html_table", "pdf_text"}:
            return mode
    # Legacy files without extractor header:
    # markdown-table heavy files are html_table; otherwise treat as pdf_text.
    numeric_rows = len(_TABLE_NUMERIC_ROW_RE.findall(text))
    return "html_table" if numeric_rows >= 5 else "pdf_text"


def _section_text(text: str, section_name: str) -> str:
    idx = text.find(f"## {section_name}")
    if idx < 0:
        return ""
    next_section = text.find("\n## ", idx + 1)
    if next_section > idx:
        return text[idx:next_section]
    return text[idx:]


def _evaluate_html_table(text: str) -> Dict[str, Any]:
    numeric_rows = len(_TABLE_NUMERIC_ROW_RE.findall(text))
    missing_sections = text.count("_Section not found in filing._")
    section_numeric_rows: Dict[str, int] = {}
    valid_core_sections = 0
    for section_name in CORE_SECTIONS:
        section = _section_text(text, section_name)
        if not section or "_Section not found" in section:
            section_numeric_rows[section_name] = 0
            continue
        count = len(_TABLE_NUMERIC_ROW_RE.findall(section))
        section_numeric_rows[section_name] = count
        if count >= 3:
            valid_core_sections += 1

    if missing_sections >= 4:
        return {
            "useful": False,
            "reason": "ALL_SECTIONS_MISSING",
            "stats": {
                "numeric_rows": numeric_rows,
                "missing_sections": missing_sections,
                "valid_core_sections": valid_core_sections,
                "section_numeric_rows": section_numeric_rows,
            },
        }

    if numeric_rows < 5:
        return {
            "useful": False,
            "reason": "LOW_NUMERIC_ROWS",
            "stats": {
                "numeric_rows": numeric_rows,
                "missing_sections": missing_sections,
                "valid_core_sections": valid_core_sections,
                "section_numeric_rows": section_numeric_rows,
            },
        }

    if valid_core_sections < 1:
        return {
            "useful": False,
            "reason": "NO_VALID_CORE_SECTION",
            "stats": {
                "numeric_rows": numeric_rows,
                "missing_sections": missing_sections,
                "valid_core_sections": valid_core_sections,
                "section_numeric_rows": section_numeric_rows,
            },
        }

    return {
        "useful": True,
        "reason": "OK",
        "stats": {
            "numeric_rows": numeric_rows,
            "missing_sections": missing_sections,
            "valid_core_sections": valid_core_sections,
            "section_numeric_rows": section_numeric_rows,
        },
    }


def _evaluate_pdf_text(text: str) -> Dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text.lower())
    chars = len(text)
    signal_hits: List[str] = sorted({h for h in _PDF_FIN_HINTS if h in normalized})
    signal_hit_count = len(signal_hits)
    numeric_token_count = len(_NUMERIC_TOKEN_RE.findall(text))
    core_sections = 0
    for section_name in CORE_SECTIONS:
        section = _section_text(text, section_name)
        if not section or "_Section not found" in section:
            continue
        section_numeric = len(_NUMERIC_TOKEN_RE.findall(section))
        if section_numeric >= 20:
            core_sections += 1

    if text.startswith("[PDF original"):
        return {
            "useful": False,
            "reason": "PDF_PLACEHOLDER",
            "stats": {
                "chars": chars,
                "signal_hits": signal_hits,
                "signal_hit_count": signal_hit_count,
                "numeric_token_count": numeric_token_count,
                "core_sections": core_sections,
            },
        }

    if signal_hit_count < 6:
        return {
            "useful": False,
            "reason": "LOW_SIGNAL",
            "stats": {
                "chars": chars,
                "signal_hits": signal_hits,
                "signal_hit_count": signal_hit_count,
                "numeric_token_count": numeric_token_count,
                "core_sections": core_sections,
            },
        }

    if chars < 8_000:
        return {
            "useful": False,
            "reason": "LOW_TEXT",
            "stats": {
                "chars": chars,
                "signal_hits": signal_hits,
                "signal_hit_count": signal_hit_count,
                "numeric_token_count": numeric_token_count,
                "core_sections": core_sections,
            },
        }

    if numeric_token_count < 80:
        return {
            "useful": False,
            "reason": "LOW_NUMERIC_DENSITY",
            "stats": {
                "chars": chars,
                "signal_hits": signal_hits,
                "signal_hit_count": signal_hit_count,
                "numeric_token_count": numeric_token_count,
                "core_sections": core_sections,
            },
        }

    if core_sections < 2:
        # V5.1 A5 — Relaxed gate for high-signal European filings (Codex Adj #5)
        _stats = {
            "chars": chars,
            "signal_hits": signal_hits,
            "signal_hit_count": signal_hit_count,
            "numeric_token_count": numeric_token_count,
            "core_sections": core_sections,
        }
        relaxed = os.environ.get("ELSIAN_ENABLE_RELAXED_PDF_GATE", "0") == "1"
        if relaxed and core_sections >= 1 and signal_hit_count >= 10 and numeric_token_count >= 150:
            return {"useful": True, "reason": "OK_RELAXED_CORE_SECTIONS", "stats": _stats}
        return {"useful": False, "reason": "LOW_CORE_SECTIONS", "stats": _stats}

    return {
        "useful": True,
        "reason": "OK",
        "stats": {
            "chars": chars,
            "signal_hits": signal_hits,
            "signal_hit_count": signal_hit_count,
            "numeric_token_count": numeric_token_count,
            "core_sections": core_sections,
        },
    }


def evaluate_clean_md(text: str, mode: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate clean.md quality under html_table or pdf_text gates."""
    selected_mode = (mode or detect_clean_md_mode(text)).strip().lower()
    if selected_mode not in {"html_table", "pdf_text"}:
        selected_mode = detect_clean_md_mode(text)
    if not text:
        return {"mode": selected_mode, "useful": False, "reason": "EMPTY", "stats": {}}

    if selected_mode == "html_table":
        result = _evaluate_html_table(text)
    else:
        result = _evaluate_pdf_text(text)
    result["mode"] = selected_mode
    return result


def is_clean_md_useful(text: str, mode: Optional[str] = None) -> bool:
    return bool(evaluate_clean_md(text, mode=mode).get("useful"))
