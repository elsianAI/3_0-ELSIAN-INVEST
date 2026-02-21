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
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

try:
    from tp_normalizer import normalize as _normalize_tp
    _HAS_NORMALIZER = True
except ImportError:
    try:
        from scripts.runners.tp_normalizer import normalize as _normalize_tp
        _HAS_NORMALIZER = True
    except ImportError:
        _HAS_NORMALIZER = False


def _dedup(items: list) -> list:
    """Deduplicate a list that may contain unhashable types (dicts)."""
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


FILING_PRIORITY = {
    "10-K": 1, "20-F": 1, "ANNUAL_REPORT": 1,
    "10-Q": 2, "6-K": 2, "INTERIM_REPORT": 2,
    "8-K": 3, "REGULATORY_FILING": 3,
    "TRANSCRIPT": 4,
    "PRESENTATION": 5, "INVESTOR_PRESENTATION": 5,
    "DEF14A": 6,
    "IR_NEWS": 7, "OTHER": 8,
}

# Patterns to detect filing type from filenames / source_filing strings
_FILING_TYPE_PATTERNS = [
    (re.compile(r"(?:10-K|10K)", re.IGNORECASE), "10-K"),
    (re.compile(r"(?:20-F|20F)", re.IGNORECASE), "20-F"),
    (re.compile(r"(?:10-Q|10Q)", re.IGNORECASE), "10-Q"),
    (re.compile(r"(?:6-K|6K)", re.IGNORECASE), "6-K"),
    (re.compile(r"8-K", re.IGNORECASE), "8-K"),
    (re.compile(r"DEF14A", re.IGNORECASE), "DEF14A"),
    (re.compile(r"TRANSCRIPT|earnings.?call", re.IGNORECASE), "TRANSCRIPT"),
    (re.compile(r"PRESENT", re.IGNORECASE), "PRESENTATION"),
]


def _resolve_filing_type(ext: dict) -> str:
    """Extract filing type from extraction metadata.

    Tries multiple heuristics to map source identifiers to a known
    filing type so that FILING_PRIORITY produces a meaningful value
    instead of defaulting to 99.
    """
    # 1) Explicit field
    ft = ext.get("filing_type", "")
    if ft:
        return ft

    # 2) Search in log.source_filing, log.fuentes_consultadas, etc.
    candidates = [ft]
    log = ext.get("log", {})
    sf = log.get("source_filing", "")
    if isinstance(sf, str):
        candidates.append(sf)
    elif isinstance(sf, list):
        candidates.extend(str(s) for s in sf)
    fc = log.get("fuentes_consultadas", [])
    if isinstance(fc, list):
        candidates.extend(str(c) for c in fc)

    combined = " ".join(candidates)
    for pattern, ftype in _FILING_TYPE_PATTERNS:
        if pattern.search(combined):
            return ftype

    return "UNKNOWN"


def merge(partial_extractions: list[dict]) -> dict:
    """
    Fusiona N partial TruthPacks de filing-level en uno solo.
    Retorna Partial TruthPack unificado listo para TP_CALCULATOR.
    """
    if not partial_extractions:
        return {"error": "No partial extractions to merge"}

    # Normalize ALL partials BEFORE merging so that field names are
    # standardised (e.g. "revenue" → "ingresos_usd", "cfo" → "cfo_usd").
    # Without this, the merge logic can't find values sitting under
    # non-standard keys and the merged result ends up with NULLs.
    normalized_extractions = [_apply_normalization(pe) for pe in partial_extractions]

    if len(normalized_extractions) == 1:
        return normalized_extractions[0]

    # Use first extraction as base template
    base = dict(normalized_extractions[0])

    # Merge sections
    base["historico_anual"] = _merge_annual(normalized_extractions)
    base["historico_trimestral"] = _merge_quarterly(normalized_extractions)
    base["balance_sheet_ultimo"] = _merge_balance_sheet(normalized_extractions)
    base["lease_data"] = _merge_lease_data(normalized_extractions)

    # Merge log/sources
    all_sources = []
    all_conversions = []
    all_limitations = []
    for pe in normalized_extractions:
        log = pe.get("log", {})
        all_sources.extend(log.get("fuentes_consultadas", log.get("source_filing", [])) if isinstance(log.get("fuentes_consultadas", log.get("source_filing", [])), list) else [log.get("source_filing", "unknown")])
        all_conversions.extend(log.get("conversiones_aplicadas", []))
        all_limitations.extend(log.get("limitaciones", []))

    base["log"] = {
        "fuentes_consultadas": _dedup(all_sources),
        "conversiones_aplicadas": _dedup(all_conversions),
        "limitaciones": _dedup(all_limitations),
        "merger_note": f"Merged {len(partial_extractions)} filings at {datetime.now(timezone.utc).isoformat()}",
    }

    return base  # already normalized per-partial


def _apply_normalization(tp: dict) -> dict:
    """Aplica normalización con fallback seguro a datos sin modificar."""
    if not _HAS_NORMALIZER:
        return tp
    try:
        return _normalize_tp(tp)
    except Exception as e:
        print(f"[merger] WARNING: Normalización falló ({e}), usando datos sin normalizar")
        return tp


def _merge_annual(extractions: list[dict]) -> list:
    """Fusiona historico_anual por periodo."""
    by_period = {}

    for ext in extractions:
        filing_type = _resolve_filing_type(ext)
        priority = FILING_PRIORITY.get(filing_type, 99)

        for entry in ext.get("historico_anual", []):
            periodo = entry.get("periodo")
            if not periodo:
                continue

            if periodo not in by_period:
                seeded = _seed_field_sources(dict(entry), filing_type)
                by_period[periodo] = {"data": seeded, "priority": priority, "source": filing_type}
            else:
                existing = by_period[periodo]
                merged = _merge_period_entries(existing["data"], entry,
                                              existing["priority"], priority, filing_type)
                by_period[periodo]["data"] = merged

    # Sort by chronological key, not alphabetical period string
    periods = sorted(by_period.keys(), key=lambda p: _period_sort_key(p, by_period[p]["data"]))
    return [by_period[p]["data"] for p in periods]


def _merge_quarterly(extractions: list[dict]) -> list:
    """Fusiona historico_trimestral por periodo."""
    by_period = {}

    for ext in extractions:
        filing_type = _resolve_filing_type(ext)
        priority = FILING_PRIORITY.get(filing_type, 99)

        for entry in ext.get("historico_trimestral", []):
            periodo = entry.get("periodo")
            if not periodo:
                continue

            if periodo not in by_period:
                seeded = _seed_field_sources(dict(entry), filing_type)
                by_period[periodo] = {"data": seeded, "priority": priority}
            else:
                existing = by_period[periodo]
                merged = _merge_period_entries(existing["data"], entry,
                                              existing["priority"], priority, filing_type)
                by_period[periodo]["data"] = merged

    periods = sorted(by_period.keys(), key=lambda p: _period_sort_key(p, by_period[p]["data"]))
    return [by_period[p]["data"] for p in periods]


_BS_METADATA_KEYS = {
    "escala", "scale", "source_filing", "filing_type", "periodo",
    "fecha_fin", "fecha_corte", "moneda", "currency", "fuente_refs",
    "tipo_periodo", "duracion", "is_preliminary",
}


def _is_bs_data_field(key: str, value) -> bool:
    """Return True if this BS field represents real financial data (not metadata/noise)."""
    if key.startswith("_"):
        return False
    if key.lower() in _BS_METADATA_KEYS:
        return False
    # Exclude comparativo_* fields (prior-year comparatives, not current BS)
    if key.lower().startswith("comparativo"):
        return False
    # Exclude nested dicts that aren't numeric data
    if isinstance(value, dict):
        return False
    return True


def _merge_balance_sheet(extractions: list[dict]) -> dict:
    """Usa el filing más reciente con datos de balance."""
    best = {}
    best_priority = 999
    best_filing = "UNKNOWN"

    for ext in extractions:
        bs = ext.get("balance_sheet_ultimo", {})
        if not bs or all(
            v is None for k, v in bs.items()
            if _is_bs_data_field(k, v)
        ):
            continue

        filing_type = _resolve_filing_type(ext)
        priority = FILING_PRIORITY.get(filing_type, 99)

        if priority < best_priority:
            best = bs
            best_priority = priority
            best_filing = filing_type

    if best:
        best = _seed_field_sources(dict(best), best_filing)
    return best


def _merge_lease_data(extractions: list[dict]) -> dict:
    """Usa el filing más reciente con datos de lease."""
    best = {}
    best_priority = 999

    for ext in extractions:
        ld = ext.get("lease_data", {})
        if not ld or all(v is None for k, v in ld.items() if not k.startswith("_")):
            continue

        filing_type = _resolve_filing_type(ext)
        priority = FILING_PRIORITY.get(filing_type, 99)

        if priority < best_priority:
            best = ld
            best_priority = priority

    return best


def _period_sort_key(periodo: str, entry: dict) -> str:
    """Return an ISO-date sort key for chronological ordering."""
    fecha_fin = entry.get("fecha_fin")
    if fecha_fin and re.match(r"\d{4}-\d{2}-\d{2}", str(fecha_fin)):
        return str(fecha_fin)
    m = re.search(r"(?:FY)?(\d{4})", periodo)
    if m:
        year = m.group(1)
        qm = re.match(r"Q([1-4])", periodo)
        if qm:
            q = int(qm.group(1))
            month = q * 3
            return f"{year}-{month:02d}-28"
        return f"{year}-12-31"
    return periodo


def _seed_field_sources(entry: dict, filing_type: str) -> dict:
    """Seed _field_sources for the first filing that introduces a period."""
    _SKIP = {"periodo", "fecha_fin", "fuente_refs", "_field_sources", "_periodo_parcial"}
    provenance = {}
    for k, v in entry.items():
        if k.startswith("_") or k in _SKIP:
            continue
        if v is not None:
            provenance[k] = filing_type
    entry["_field_sources"] = provenance
    return entry


def _merge_period_entries(existing: dict, new_entry: dict,
                         existing_priority: int, new_priority: int,
                         new_source: str = "UNKNOWN") -> dict:
    """Merge two period entries, resolving conflicts by priority.

    Rules:
      - Null-fill is ONLY allowed when new source has equal or better
        (lower) priority.  A TRANSCRIPT (4) cannot fill a null that
        a 20-F (1) correctly left empty.
      - Conflicts use higher priority (lower number wins).
      - Provenance tracked in _field_sources.
    """
    merged = dict(existing)
    provenance = dict(merged.get("_field_sources", {}))

    for key, new_val in new_entry.items():
        if key in ("periodo", "fecha_fin", "fuente_refs", "_field_sources"):
            continue

        existing_val = merged.get(key)

        if existing_val is None and new_val is not None:
            # Null-fill: only if new source is same or better priority
            if new_priority <= existing_priority:
                merged[key] = new_val
                provenance[key] = new_source
        elif existing_val is not None and new_val is not None and existing_val != new_val:
            # Conflict — use higher priority (lower number)
            if new_priority < existing_priority:
                merged[key] = new_val
                provenance[key] = new_source

    merged["_field_sources"] = provenance
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
