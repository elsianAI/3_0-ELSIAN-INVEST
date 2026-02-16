#!/usr/bin/env python3
"""Deterministic iXBRL fact extractor for SEC inline XBRL filings.

Parses <ix:nonFraction> tags from SEC .htm filings and extracts
machine-readable financial data with full provenance.  Zero LLM tokens.

Output: .ixbrl.json per filing with extracted facts grouped by concept.

Usage:
    python3 scripts/runners/ixbrl_extractor.py <input.htm> <output.ixbrl.json>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag


# ── Concept synonym map ──────────────────────────────────────────────
# Maps our canonical field names to the set of US-GAAP / IFRS tags
# that represent that concept.  Order matters: first match wins for
# disambiguation when multiple synonyms are present.

CONCEPT_SYNONYMS: dict[str, list[str]] = {
    "revenue": [
        "us-gaap:Revenues",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:SalesRevenueNet",
        "us-gaap:SalesRevenueGoodsNet",
        "ifrs-full:Revenue",
    ],
    "net_income": [
        "us-gaap:NetIncomeLoss",
        "us-gaap:ProfitLoss",
        "us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic",
        "ifrs-full:ProfitLoss",
    ],
    "operating_income": [
        "us-gaap:OperatingIncomeLoss",
        "us-gaap:IncomeLossFromContinuingOperations",
        "ifrs-full:ProfitLossFromOperatingActivities",
    ],
    "cash": [
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:CashCashEquivalentsAndShortTermInvestments",
        "ifrs-full:CashAndCashEquivalents",
    ],
    "total_assets": [
        "us-gaap:Assets",
        "ifrs-full:Assets",
    ],
    "total_liabilities": [
        "us-gaap:Liabilities",
        "ifrs-full:Liabilities",
    ],
    "equity": [
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "ifrs-full:Equity",
    ],
    "cfo": [
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    ],
    "capex": [
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "us-gaap:PaymentsToAcquireProductiveAssets",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    ],
    "eps_basic": [
        "us-gaap:EarningsPerShareBasic",
        "ifrs-full:BasicEarningsLossPerShare",
    ],
    "eps_diluted": [
        "us-gaap:EarningsPerShareDiluted",
        "ifrs-full:DilutedEarningsLossPerShare",
    ],
}

# Reverse map: gaap_tag → canonical name
_TAG_TO_CANONICAL: dict[str, str] = {}
for _canon, _tags in CONCEPT_SYNONYMS.items():
    for _tag in _tags:
        _TAG_TO_CANONICAL.setdefault(_tag, _canon)


# ── Scale / decimals helpers ─────────────────────────────────────────

_SCALE_FACTORS = {
    "-2": 0.01, "-1": 0.1, "0": 1, "1": 10, "2": 100,
    "3": 1_000, "4": 10_000, "5": 100_000, "6": 1_000_000,
    "7": 10_000_000, "8": 100_000_000, "9": 1_000_000_000,
}


def _parse_numeric(text: str) -> Optional[float]:
    """Parse a numeric value from iXBRL text content.

    Handles: plain numbers, comma-separated, parenthetical negatives,
    en-dash / em-dash for zero.
    """
    if not text:
        return None
    text = text.strip()
    if text in ("—", "–", "-", ""):
        return 0.0

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    # Strip currency symbols, commas, spaces
    text = re.sub(r"[,$€£¥\s]", "", text)
    try:
        val = float(text)
    except ValueError:
        return None
    return -val if negative else val


def _normalize_value(raw_val: float, scale: Optional[str], sign: Optional[str]) -> float:
    """Apply scale factor and sign attribute to raw value."""
    factor = _SCALE_FACTORS.get(str(scale or "0"), 1)
    result = raw_val * factor
    if sign and sign.strip() == "-":
        result = -abs(result)
    return result


# ── Context parsing ──────────────────────────────────────────────────

def _parse_contexts(soup: BeautifulSoup) -> dict[str, dict]:
    """Parse all <xbrli:context> elements.

    Returns {context_id: {"period": {...}, "has_segment": bool}}
    where period is {"instant": "YYYY-MM-DD"} or
    {"startDate": "...", "endDate": "..."}.
    """
    contexts: dict[str, dict] = {}
    for ctx in soup.find_all(re.compile(r"(?:xbrli:)?context", re.IGNORECASE)):
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue

        # Check for dimensional segment (= not consolidated total)
        segment = ctx.find(re.compile(r"(?:xbrli:)?segment", re.IGNORECASE))
        has_segment = segment is not None and len(segment.find_all()) > 0

        # Parse period
        period_tag = ctx.find(re.compile(r"(?:xbrli:)?period", re.IGNORECASE))
        period_info: dict[str, str] = {}
        if period_tag:
            instant = period_tag.find(re.compile(r"(?:xbrli:)?instant", re.IGNORECASE))
            if instant:
                period_info["instant"] = instant.get_text(strip=True)
            else:
                start = period_tag.find(re.compile(r"(?:xbrli:)?startDate", re.IGNORECASE))
                end = period_tag.find(re.compile(r"(?:xbrli:)?endDate", re.IGNORECASE))
                if start:
                    period_info["startDate"] = start.get_text(strip=True)
                if end:
                    period_info["endDate"] = end.get_text(strip=True)

        contexts[ctx_id] = {
            "period": period_info,
            "has_segment": has_segment,
        }
    return contexts


def _period_end_date(period_info: dict) -> Optional[str]:
    """Get the end date from a period info dict."""
    return period_info.get("instant") or period_info.get("endDate")


# ── Main extraction ──────────────────────────────────────────────────

def extract_ixbrl_facts(html_path: Path) -> dict[str, Any]:
    """Extract iXBRL facts from an SEC inline XBRL filing.

    Returns a dict with:
      - "facts": {canonical_name: [list of fact dicts sorted by period]}
      - "consolidated": {canonical_name: {period_end: value}} for non-segment facts
      - "meta": extraction metadata
      - "taxonomy": "us-gaap" | "ifrs" | "mixed" | "unknown"
    """
    raw = html_path.read_text(errors="replace")
    soup = BeautifulSoup(raw, "html.parser")

    # Parse contexts
    contexts = _parse_contexts(soup)

    # Find all ix:nonFraction tags
    all_facts: list[dict] = []
    seen_taxonomies: set[str] = set()

    for tag in soup.find_all(re.compile(r"ix:nonfraction", re.IGNORECASE)):
        name = tag.get("name", "")
        if not name:
            continue

        # Track taxonomy
        if name.startswith("us-gaap:"):
            seen_taxonomies.add("us-gaap")
        elif name.startswith("ifrs-full:") or name.startswith("ifrs:"):
            seen_taxonomies.add("ifrs")

        canonical = _TAG_TO_CANONICAL.get(name)
        if canonical is None:
            continue

        context_ref = tag.get("contextref", "")
        scale = tag.get("scale")
        sign = tag.get("sign")
        decimals = tag.get("decimals")
        ix_id = tag.get("id", "")

        # Parse raw text value
        raw_text = tag.get_text(strip=True)
        raw_val = _parse_numeric(raw_text)
        if raw_val is None:
            continue

        normalized = _normalize_value(raw_val, scale, sign)

        # Resolve context
        ctx = contexts.get(context_ref, {})
        period = ctx.get("period", {})
        has_segment = ctx.get("has_segment", False)
        period_end = _period_end_date(period)

        fact: dict[str, Any] = {
            "canonical": canonical,
            "gaap_tag": name,
            "contextRef": context_ref,
            "period": period,
            "period_end": period_end,
            "has_segment": has_segment,
            "scale": scale,
            "sign": sign,
            "decimals": decimals,
            "raw_text": raw_text,
            "raw_value": raw_val,
            "normalized_value": normalized,
            "ix_id": ix_id,
            "file": html_path.name,
        }
        all_facts.append(fact)

    # Group by canonical name
    by_canonical: dict[str, list[dict]] = {}
    for fact in all_facts:
        by_canonical.setdefault(fact["canonical"], []).append(fact)

    # Build consolidated view: only non-segment facts (= totals)
    consolidated: dict[str, dict[str, float]] = {}
    for canonical, facts in by_canonical.items():
        periods: dict[str, float] = {}
        for f in facts:
            if f["has_segment"]:
                continue  # Skip dimensional/segment values
            pe = f["period_end"]
            if pe and pe not in periods:
                periods[pe] = f["normalized_value"]
        if periods:
            consolidated[canonical] = periods

    # Determine taxonomy
    if len(seen_taxonomies) == 0:
        taxonomy = "unknown"
    elif len(seen_taxonomies) == 1:
        taxonomy = seen_taxonomies.pop()
    else:
        taxonomy = "mixed"

    return {
        "facts": {k: sorted(v, key=lambda f: f.get("period_end") or "")
                  for k, v in by_canonical.items()},
        "consolidated": consolidated,
        "meta": {
            "source_file": html_path.name,
            "total_relevant_tags": len(all_facts),
            "canonical_concepts_found": list(by_canonical.keys()),
            "taxonomy": taxonomy,
            "contexts_parsed": len(contexts),
            "consolidated_contexts": sum(1 for c in contexts.values() if not c["has_segment"]),
        },
    }


def get_most_recent_consolidated(ixbrl_data: dict, canonical: str) -> Optional[dict]:
    """Get the most recent consolidated (non-segment) value for a concept.

    Returns {"value": float, "period_end": str, "provenance": dict} or None.
    """
    consolidated = ixbrl_data.get("consolidated", {})
    periods = consolidated.get(canonical, {})
    if not periods:
        return None

    # Most recent period
    most_recent = max(periods.keys())
    value = periods[most_recent]

    # Find the full fact entry for provenance
    facts = ixbrl_data.get("facts", {}).get(canonical, [])
    provenance = {}
    for f in facts:
        if f.get("period_end") == most_recent and not f.get("has_segment"):
            provenance = {
                "gaap_tag": f["gaap_tag"],
                "contextRef": f["contextRef"],
                "scale": f["scale"],
                "ix_id": f["ix_id"],
                "file": f["file"],
            }
            break

    return {"value": value, "period_end": most_recent, "provenance": provenance}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.htm> <output.ixbrl.json>")
        sys.exit(1)

    htm_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not htm_path.exists():
        print(f"ERROR: {htm_path} not found")
        sys.exit(1)

    result = extract_ixbrl_facts(htm_path)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[ixbrl_extractor] Extracted {result['meta']['total_relevant_tags']} facts "
          f"({len(result['meta']['canonical_concepts_found'])} concepts) → {out_path}")
