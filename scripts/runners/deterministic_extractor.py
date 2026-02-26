"""Deterministic filing extractor (Phase 2, Layer 1).

Python-first helper for:
1) Extracting anchor financial fields from filing text without LLM.
2) Splitting long filings into semantic chunks by detected sections.

Design goals:
- Fail-open: return partial hints, never raise to caller by default.
- Traceability: each extracted hint carries section and line number.
- Currency/unit agnostic extraction: values stay in reported currency scale.
"""

from __future__ import annotations

import re
from typing import Any


_FIELD_RULES: list[dict[str, Any]] = [
    {
        "field": "ingresos_usd",
        "sections": {"income_statement", "notes"},
        "patterns": [
            re.compile(r"\b(?:total\s+revenue|net\s+revenue|revenues?|sales)\b", re.I),
            re.compile(r"\b(?:chiffre\s+d['’]affaires|produits)\b", re.I),
        ],
    },
    {
        "field": "net_income_usd",
        "sections": {"income_statement"},
        "patterns": [
            re.compile(r"\b(?:net\s+income|net\s+earnings?|profit\s+for\s+the\s+year)\b", re.I),
            re.compile(r"\b(?:résultat\s+net)\b", re.I),
        ],
    },
    {
        "field": "ebit_usd",
        "sections": {"income_statement"},
        "patterns": [
            re.compile(r"\b(?:operating\s+income|income\s+from\s+operations|EBIT)\b", re.I),
            re.compile(r"\b(?:résultat\s+opérationnel)\b", re.I),
        ],
    },
    {
        "field": "cfo_usd",
        "sections": {"cash_flow"},
        "patterns": [
            re.compile(r"\b(?:net\s+cash\s+(?:provided\s+by|from)\s+operating)\b", re.I),
            re.compile(r"\b(?:cash\s+flows?\s+from\s+operating\s+activities)\b", re.I),
            re.compile(r"\b(?:flux\s+de\s+trésorerie.*activités\s+opérationnelles)\b", re.I),
        ],
    },
    {
        "field": "capex_usd",
        "sections": {"cash_flow", "notes"},
        "patterns": [
            re.compile(r"\b(?:capital\s+expenditures?|capex)\b", re.I),
            re.compile(r"\b(?:acquisitions?\s+of\s+property)\b", re.I),
            re.compile(r"\b(?:investissements?\s+corporels?)\b", re.I),
        ],
    },
    {
        "field": "activos_totales_usd",
        "sections": {"balance_sheet"},
        "patterns": [
            re.compile(r"\b(?:total\s+assets?)\b", re.I),
            re.compile(r"\b(?:total\s+de\s+l['’]actif)\b", re.I),
        ],
    },
    {
        "field": "pasivos_totales_usd",
        "sections": {"balance_sheet"},
        "patterns": [
            re.compile(r"\b(?:total\s+liabilit(?:y|ies))\b", re.I),
            re.compile(r"\b(?:total\s+du\s+passif)\b", re.I),
        ],
    },
    {
        "field": "patrimonio_usd",
        "sections": {"balance_sheet"},
        "patterns": [
            re.compile(r"\b(?:total\s+equity|stockholders['’]?\s+equity|shareholders['’]?\s+equity)\b", re.I),
            re.compile(r"\b(?:capitaux?\s+propres)\b", re.I),
        ],
    },
    {
        "field": "caja_usd",
        "sections": {"balance_sheet", "cash_flow"},
        "patterns": [
            re.compile(r"\b(?:cash\s+and\s+cash\s+equivalents?)\b", re.I),
            re.compile(r"\b(?:trésorerie\s+et\s+équivalents?)\b", re.I),
        ],
    },
    {
        "field": "deuda_largo_plazo_usd",
        "sections": {"balance_sheet", "notes"},
        "patterns": [
            re.compile(r"\b(?:long[-\s]?term\s+debt|non[-\s]?current\s+borrowings?)\b", re.I),
            re.compile(r"\b(?:emprunts?\s+non\s+courants?)\b", re.I),
        ],
    },
    {
        "field": "deuda_corto_plazo_usd",
        "sections": {"balance_sheet", "notes"},
        "patterns": [
            re.compile(r"\b(?:short[-\s]?term\s+debt|current\s+borrowings?)\b", re.I),
            re.compile(r"\b(?:emprunts?\s+courants?)\b", re.I),
        ],
    },
]

_SECTION_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("income_statement", re.compile(r"\b(?:income\s+statement|statements?\s+of\s+(?:income|operations|profit)|compte\s+de\s+résultat)\b", re.I)),
    ("balance_sheet", re.compile(r"\b(?:balance\s+sheet|statement\s+of\s+financial\s+position|bilan)\b", re.I)),
    ("cash_flow", re.compile(r"\b(?:cash\s+flow|statement\s+of\s+cash\s+flows?|flux\s+de\s+trésorerie|tableau\s+des\s+flux)\b", re.I)),
    ("equity", re.compile(r"\b(?:equity|capitaux?\s+propres)\b", re.I)),
    ("notes", re.compile(r"\b(?:notes\s+to\s+financial\s+statements|notes\s+annexes?)\b", re.I)),
]

_UNIT_RULES: list[tuple[str, float, re.Pattern[str]]] = [
    ("billions", 1_000_000_000.0, re.compile(r"\b(?:in|en)\s+billions?\b", re.I)),
    ("millions", 1_000_000.0, re.compile(r"\b(?:in|en)\s+millions?\b", re.I)),
    ("thousands", 1_000.0, re.compile(r"\b(?:in|en)\s+thousands?\b", re.I)),
    ("units", 1.0, re.compile(r"\b(?:in|en)\s+(?:usd|eur|gbp)\b", re.I)),
]

_NUM_TOKEN_RE = re.compile(r"\(?-?\d[\d\s,.'’]*\)?")


def _section_from_heading(line: str) -> str | None:
    txt = (line or "").strip()
    if not txt:
        return None
    for name, pattern in _SECTION_RULES:
        if pattern.search(txt):
            return name
    return None


def _clean_numeric_token(token: str) -> str:
    t = token.strip().replace("’", "").replace("'", "")
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    t = t.replace(" ", "")
    return t


def _parse_number(token: str) -> float | None:
    t = _clean_numeric_token(token)
    if not t:
        return None
    if t in {"-", ".", ",", "-.", "-,"}:
        return None

    has_comma = "," in t
    has_dot = "." in t

    if has_comma and has_dot:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "")
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
    elif has_comma:
        tail = t.split(",")[-1]
        if len(tail) in (1, 2):
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
    elif has_dot:
        tail = t.split(".")[-1]
        if len(tail) not in (1, 2):
            t = t.replace(".", "")

    try:
        return float(t)
    except ValueError:
        return None


def _looks_like_year(token: str) -> bool:
    t = _clean_numeric_token(token)
    if not re.fullmatch(r"-?\d{4}", t):
        return False
    try:
        y = int(t)
    except ValueError:
        return False
    return 1900 <= y <= 2100


def _extract_numeric_value(line: str, multiplier: float) -> float | None:
    for match in _NUM_TOKEN_RE.finditer(line):
        token = match.group(0)
        if _looks_like_year(token):
            continue
        value = _parse_number(token)
        if value is None:
            continue
        return value * multiplier
    return None


def _confidence_for(field_sections: set[str], current_section: str) -> str:
    if current_section in field_sections:
        return "high"
    if current_section == "unknown":
        return "medium"
    return "low"


def _confidence_rank(conf: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(conf, 0)


def _scan_units(lines: list[str], sections_by_line: list[str]) -> tuple[float, dict[str, float]]:
    global_multiplier = 1.0
    per_section: dict[str, float] = {}

    head_text = "\n".join(lines[:80])
    for _, multiplier, pattern in _UNIT_RULES:
        if pattern.search(head_text):
            global_multiplier = multiplier
            break

    for idx, line in enumerate(lines):
        section = sections_by_line[idx]
        for _, multiplier, pattern in _UNIT_RULES:
            if pattern.search(line):
                per_section[section] = multiplier
                break

    return global_multiplier, per_section


def extract_deterministic_facts(text: str, *, max_hits_per_field: int = 5) -> dict[str, Any]:
    """Extract anchor financial hints from filing text.

    Returns:
      {
        "entries": [{field, value, section, line, matched_text, unit_applied, confidence}],
        "best_by_field": {field: {...}},
        "stats": {...}
      }
    """
    if not text:
        return {"entries": [], "best_by_field": {}, "stats": {"entries": 0, "fields": 0}}

    lines = text.splitlines()
    current_section = "unknown"
    sections_by_line: list[str] = []
    for line in lines:
        found = _section_from_heading(line)
        if found:
            current_section = found
        sections_by_line.append(current_section)

    global_multiplier, per_section_multiplier = _scan_units(lines, sections_by_line)

    entries: list[dict[str, Any]] = []
    hits_per_field: dict[str, int] = {}

    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        section = sections_by_line[idx - 1]
        multiplier = per_section_multiplier.get(section, global_multiplier)

        for rule in _FIELD_RULES:
            field = rule["field"]
            if hits_per_field.get(field, 0) >= max_hits_per_field:
                continue
            matched = next((p for p in rule["patterns"] if p.search(line)), None)
            if not matched:
                continue
            value = _extract_numeric_value(line, multiplier)
            if value is None:
                continue
            conf = _confidence_for(rule["sections"], section)
            entries.append(
                {
                    "field": field,
                    "value": value,
                    "section": section,
                    "line": idx,
                    "matched_text": line.strip()[:240],
                    "unit_applied": multiplier,
                    "confidence": conf,
                }
            )
            hits_per_field[field] = hits_per_field.get(field, 0) + 1

    best_by_field: dict[str, dict[str, Any]] = {}
    for item in entries:
        field = item["field"]
        prev = best_by_field.get(field)
        if prev is None:
            best_by_field[field] = item
            continue
        prev_rank = _confidence_rank(str(prev.get("confidence", "")))
        cur_rank = _confidence_rank(str(item.get("confidence", "")))
        if cur_rank > prev_rank:
            best_by_field[field] = item
        elif cur_rank == prev_rank and abs(float(item["value"])) > abs(float(prev["value"])):
            best_by_field[field] = item

    return {
        "entries": entries,
        "best_by_field": best_by_field,
        "stats": {
            "entries": len(entries),
            "fields": len(best_by_field),
            "global_unit_multiplier": global_multiplier,
            "sections_with_units": sorted(per_section_multiplier.keys()),
        },
    }


def format_deterministic_hints_block(extraction: dict[str, Any], *, max_fields: int = 12) -> str | None:
    """Format deterministic extraction as compact prompt hints."""
    if not isinstance(extraction, dict):
        return None
    best_by_field = extraction.get("best_by_field", {})
    if not isinstance(best_by_field, dict) or not best_by_field:
        return None

    ordered = sorted(
        best_by_field.items(),
        key=lambda kv: (-_confidence_rank(str(kv[1].get("confidence", ""))), str(kv[0])),
    )[:max_fields]

    lines = ["# DATOS PRE-EXTRAIDOS (CAPA 1 DETERMINISTA)\n"]
    for field, item in ordered:
        value = item.get("value")
        section = item.get("section", "unknown")
        line = item.get("line", "?")
        conf = item.get("confidence", "low")
        lines.append(f"- {field}: {value} (section={section}, line={line}, conf={conf})")
    lines.append(
        "\nUsa estos valores como HINTS de alta cobertura. "
        "Si el filing muestra un valor distinto claramente en tabla, prioriza el filing."
    )
    return "\n".join(lines)


def _fixed_window_chunks(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int,
    max_chunks: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    stride = max(1, max_chars - max(0, overlap_chars))
    pos = 0
    cid = 1
    while pos < len(text) and len(chunks) < max_chunks:
        end = min(len(text), pos + max_chars)
        chunks.append(
            {
                "id": cid,
                "label": "window",
                "start": pos,
                "end": end,
                "text": text[pos:end],
            }
        )
        if end >= len(text):
            break
        pos += stride
        cid += 1
    return chunks


def split_semantic_chunks(
    text: str,
    *,
    target_chars: int,
    max_chars: int,
    overlap_chars: int,
    max_chunks: int,
) -> list[dict[str, Any]]:
    """Split filing text into semantic chunks by section headings first.

    Falls back to fixed windows when headings are not detectable.
    """
    if not text:
        return []
    target_chars = max(4_000, int(target_chars))
    max_chars = max(target_chars, int(max_chars))
    overlap_chars = max(0, int(overlap_chars))
    max_chunks = max(1, int(max_chunks))

    lines = text.splitlines(keepends=True)
    starts: list[tuple[str, int]] = []
    cursor = 0
    for line in lines:
        raw = line.strip()
        is_heading = raw.startswith("##") or raw.isupper()
        if is_heading:
            sec = _section_from_heading(raw)
            if sec:
                starts.append((sec, cursor))
        cursor += len(line)

    if not starts:
        return _fixed_window_chunks(
            text, max_chars=max_chars, overlap_chars=overlap_chars, max_chunks=max_chunks
        )

    starts.sort(key=lambda x: x[1])
    sections: list[dict[str, Any]] = []
    for i, (label, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        if end <= start:
            continue
        sections.append({"label": label, "start": start, "end": end, "text": text[start:end]})
    if not sections:
        return _fixed_window_chunks(
            text, max_chars=max_chars, overlap_chars=overlap_chars, max_chunks=max_chunks
        )

    chunks: list[dict[str, Any]] = []
    cid = 1
    cur_parts: list[str] = []
    cur_labels: list[str] = []
    cur_start: int | None = None
    cur_end: int | None = None

    def flush_current() -> None:
        nonlocal cid, cur_parts, cur_labels, cur_start, cur_end
        if not cur_parts:
            return
        chunk_text = "".join(cur_parts)
        chunks.append(
            {
                "id": cid,
                "label": "+".join(sorted(set(cur_labels)))[:80] or "section",
                "start": int(cur_start or 0),
                "end": int(cur_end or 0),
                "text": chunk_text,
            }
        )
        cid += 1
        cur_parts, cur_labels, cur_start, cur_end = [], [], None, None

    for section in sections:
        sec_text = section["text"]
        sec_len = len(sec_text)
        sec_label = section["label"]
        sec_start = int(section["start"])
        sec_end = int(section["end"])

        if sec_len > max_chars:
            flush_current()
            stride = max(1, max_chars - overlap_chars)
            pos = 0
            while pos < sec_len and len(chunks) < max_chunks:
                end = min(sec_len, pos + max_chars)
                chunk_start = sec_start + pos
                chunk_end = sec_start + end
                chunks.append(
                    {
                        "id": cid,
                        "label": f"{sec_label}_part",
                        "start": chunk_start,
                        "end": chunk_end,
                        "text": sec_text[pos:end],
                    }
                )
                cid += 1
                if end >= sec_len:
                    break
                pos += stride
            continue

        current_len = sum(len(p) for p in cur_parts)
        if cur_parts and current_len + sec_len > target_chars:
            flush_current()
        cur_parts.append(sec_text)
        cur_labels.append(sec_label)
        if cur_start is None:
            cur_start = sec_start
        cur_end = sec_end

    flush_current()

    if not chunks:
        return _fixed_window_chunks(
            text, max_chars=max_chars, overlap_chars=overlap_chars, max_chunks=max_chunks
        )

    if len(chunks) > max_chunks:
        merged_tail = "\n".join(c["text"] for c in chunks[max_chunks - 1:])
        trimmed = chunks[: max_chunks - 1]
        last_start = chunks[max_chunks - 1]["start"]
        last_end = chunks[-1]["end"]
        trimmed.append(
            {
                "id": max_chunks,
                "label": "merged_tail",
                "start": last_start,
                "end": last_end,
                "text": merged_tail[:max_chars],
            }
        )
        chunks = trimmed

    for idx, chunk in enumerate(chunks, start=1):
        chunk["id"] = idx
    return chunks

