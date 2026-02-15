"""
TP_EXTRACTOR_MERGER: Fusiona outputs de TP_EXTRACTOR por filing.
100% determinista, 0 tokens LLM.

Lógica:
  1. Lee N partial extractions (1 por filing)
  2. Organiza por periodo
  3. Resuelve conflictos por prioridad de filing type
  4. Balance sheet: usa el filing más reciente
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone


FILING_PRIORITY = {
    "10-K": 1, "20-F": 1,
    "10-Q": 2, "6-K": 2,
    "8-K": 3,
    "TRANSCRIPT": 4,
    "PRESENTATION": 5,
    "DEF14A": 6,
}


def merge(partial_extractions: list[dict]) -> dict:
    """
    Fusiona N partial TruthPacks de filing-level en uno solo.
    Retorna Partial TruthPack unificado listo para TP_CALCULATOR.
    """
    if not partial_extractions:
        return {"error": "No partial extractions to merge"}

    if len(partial_extractions) == 1:
        return partial_extractions[0]

    # Use first extraction as base template
    base = dict(partial_extractions[0])

    # Merge sections
    base["historico_anual"] = _merge_annual(partial_extractions)
    base["historico_trimestral"] = _merge_quarterly(partial_extractions)
    base["balance_sheet_ultimo"] = _merge_balance_sheet(partial_extractions)
    base["lease_data"] = _merge_lease_data(partial_extractions)

    # Merge log/sources
    all_sources = []
    all_conversions = []
    all_limitations = []
    for pe in partial_extractions:
        log = pe.get("log", {})
        all_sources.extend(log.get("fuentes_consultadas", log.get("source_filing", [])) if isinstance(log.get("fuentes_consultadas", log.get("source_filing", [])), list) else [log.get("source_filing", "unknown")])
        all_conversions.extend(log.get("conversiones_aplicadas", []))
        all_limitations.extend(log.get("limitaciones", []))

    base["log"] = {
        "fuentes_consultadas": list(set(all_sources)),
        "conversiones_aplicadas": list(set(all_conversions)),
        "limitaciones": list(set(all_limitations)),
        "merger_note": f"Merged {len(partial_extractions)} filings at {datetime.now(timezone.utc).isoformat()}",
    }

    return base


def _merge_annual(extractions: list[dict]) -> list:
    """Fusiona historico_anual por periodo."""
    by_period = {}

    for ext in extractions:
        filing_type = ext.get("filing_type", ext.get("log", {}).get("source_filing", "UNKNOWN"))
        priority = FILING_PRIORITY.get(filing_type, 99)

        for entry in ext.get("historico_anual", []):
            periodo = entry.get("periodo")
            if not periodo:
                continue

            if periodo not in by_period:
                by_period[periodo] = {"data": dict(entry), "priority": priority, "source": filing_type}
            else:
                existing = by_period[periodo]
                # Merge fields: fill nulls from lower-priority, resolve conflicts by priority
                merged = _merge_period_entries(existing["data"], entry, existing["priority"], priority)
                by_period[periodo]["data"] = merged

    # Sort by period
    periods = sorted(by_period.keys())
    return [by_period[p]["data"] for p in periods]


def _merge_quarterly(extractions: list[dict]) -> list:
    """Fusiona historico_trimestral por periodo."""
    by_period = {}

    for ext in extractions:
        filing_type = ext.get("filing_type", "UNKNOWN")
        priority = FILING_PRIORITY.get(filing_type, 99)

        for entry in ext.get("historico_trimestral", []):
            periodo = entry.get("periodo")
            if not periodo:
                continue

            if periodo not in by_period:
                by_period[periodo] = {"data": dict(entry), "priority": priority}
            else:
                existing = by_period[periodo]
                merged = _merge_period_entries(existing["data"], entry, existing["priority"], priority)
                by_period[periodo]["data"] = merged

    periods = sorted(by_period.keys())
    return [by_period[p]["data"] for p in periods]


def _merge_balance_sheet(extractions: list[dict]) -> dict:
    """Usa el filing más reciente con datos de balance."""
    best = {}
    best_priority = 999

    for ext in extractions:
        bs = ext.get("balance_sheet_ultimo", {})
        if not bs or all(v is None for k, v in bs.items() if not k.startswith("_")):
            continue

        filing_type = ext.get("filing_type", "UNKNOWN")
        priority = FILING_PRIORITY.get(filing_type, 99)

        if priority < best_priority:
            best = bs
            best_priority = priority

    return best


def _merge_lease_data(extractions: list[dict]) -> dict:
    """Usa el filing más reciente con datos de lease."""
    best = {}
    best_priority = 999

    for ext in extractions:
        ld = ext.get("lease_data", {})
        if not ld or all(v is None for k, v in ld.items() if not k.startswith("_")):
            continue

        filing_type = ext.get("filing_type", "UNKNOWN")
        priority = FILING_PRIORITY.get(filing_type, 99)

        if priority < best_priority:
            best = ld
            best_priority = priority

    return best


def _merge_period_entries(existing: dict, new_entry: dict, existing_priority: int, new_priority: int) -> dict:
    """Merge two period entries, resolving conflicts by priority."""
    merged = dict(existing)

    for key, new_val in new_entry.items():
        if key in ("periodo", "fecha_fin", "fuente_refs"):
            continue

        existing_val = merged.get(key)

        if existing_val is None and new_val is not None:
            # Fill null with new data
            merged[key] = new_val
        elif existing_val is not None and new_val is not None and existing_val != new_val:
            # Conflict — use higher priority (lower number)
            if new_priority < existing_priority:
                merged[key] = new_val

    return merged


def _resolve_conflict(values: list[tuple], field: str):
    """Resuelve conflicto entre valores de diferentes filings por prioridad."""
    if not values:
        return None
    # Sort by priority (lower = better)
    values.sort(key=lambda x: x[1])
    return values[0][0]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input_dir> <output.json>")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    partials = [
        json.loads(f.read_text())
        for f in sorted(input_dir.glob("_tmp_tp_filing_*.json"))
    ]

    if not partials:
        print(f"[merger] No _tmp_tp_filing_*.json files found in {input_dir}")
        sys.exit(1)

    result = merge(partials)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[merger] Merged {len(partials)} filings → {output_path}")
