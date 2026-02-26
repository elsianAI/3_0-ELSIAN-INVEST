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
import math
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


# V6.2: Maximum periods per filing (enforced in merger, not just prompt)
MAX_PERIODS_PER_FILING = 10

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
    merger_warnings: list[str] = []

    # V6.2: Enforce max_periods_per_filing and drop partial annual periods
    # before any merge, including single-filing path.
    for ext in normalized_extractions:
        annual_entries = ext.get("historico_anual", [])
        if isinstance(annual_entries, list):
            ext["historico_anual"] = [
                e for e in annual_entries
                if isinstance(e, dict) and not e.get("_periodo_parcial")
            ]
        for section_key in ("historico_anual", "historico_trimestral"):
            entries = ext.get(section_key, [])
            if not isinstance(entries, list):
                continue
            if len(entries) > MAX_PERIODS_PER_FILING:
                ext[section_key] = sorted(
                    entries,
                    key=lambda e: _period_sort_key(e.get("periodo", ""), e),
                    reverse=True,
                )[:MAX_PERIODS_PER_FILING]

    if len(normalized_extractions) == 1:
        merged = dict(normalized_extractions[0])
        local_warnings: list[str] = []
        merged["balance_sheet_ultimo"] = _normalize_balance_sheet(
            merged.get("balance_sheet_ultimo"),
            filing_index=1,
            warnings=local_warnings,
        )
        # ── Imputation pass for single-filing (V5.1, Codex Adj #3) ──
        bs = merged.get("balance_sheet_ultimo", {})
        if bs and isinstance(bs, dict):
            # Ensure _field_sources exists before imputation
            if "_field_sources" not in bs:
                ft = _resolve_filing_type(merged)
                _seed_field_sources(bs, str(ft))
            prov = dict(bs.get("_field_sources", {}))
            _impute_balance_identity(bs, prov, local_warnings)
            _impute_deuda_total(bs, prov, local_warnings)
            bs["_field_sources"] = prov
        _warn_lease_only_debt_missing(merged, local_warnings)
        if local_warnings:
            log_payload = merged.setdefault("log", {})
            if isinstance(log_payload, dict):
                log_payload["merger_warnings"] = _dedup(local_warnings)
            else:
                merged["log"] = {"merger_warnings": local_warnings}
        return merged

    # Use first extraction as base template
    base = dict(normalized_extractions[0])

    # Merge sections
    base["historico_anual"] = _merge_annual(normalized_extractions)
    base["historico_trimestral"] = _merge_quarterly(normalized_extractions)
    base["balance_sheet_ultimo"] = _merge_balance_sheet(normalized_extractions, merger_warnings)
    base["lease_data"] = _merge_lease_data(normalized_extractions)
    _warn_lease_only_debt_missing(base, merger_warnings)

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
        "merger_warnings": _dedup(merger_warnings),
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
    """Fusiona historico_anual por periodo.

    V6.2: Uses normalized merge key. Tie-break by filing recency (index).
    """
    by_period: dict[str, dict] = {}

    for ext_idx, ext in enumerate(extractions):
        filing_type = _resolve_filing_type(ext)
        priority = FILING_PRIORITY.get(filing_type, 99)

        for entry in ext.get("historico_anual", []):
            if entry.get("_periodo_parcial"):
                continue
            periodo = entry.get("periodo")
            if not periodo:
                continue

            # V6.2: use normalized merge key for dedup
            merge_key = _normalize_merge_key(entry)

            if merge_key not in by_period:
                seeded = _seed_field_sources(dict(entry), filing_type)
                by_period[merge_key] = {
                    "data": seeded, "priority": priority,
                    "source": filing_type, "recency": ext_idx,
                }
            else:
                existing = by_period[merge_key]
                merged = _merge_period_entries(
                    existing["data"], entry,
                    existing["priority"], priority, filing_type,
                    new_recency=ext_idx,
                    existing_recency=existing.get("recency", 0),
                )
                by_period[merge_key]["data"] = merged

    # Sort by chronological key
    periods = sorted(by_period.keys(),
                     key=lambda p: _period_sort_key(
                         by_period[p]["data"].get("periodo", p),
                         by_period[p]["data"]))
    return [by_period[p]["data"] for p in periods]


def _merge_quarterly(extractions: list[dict]) -> list:
    """Fusiona historico_trimestral por periodo.

    V6.2: Uses normalized merge key. Tie-break by filing recency (index).
    """
    by_period: dict[str, dict] = {}

    for ext_idx, ext in enumerate(extractions):
        filing_type = _resolve_filing_type(ext)
        priority = FILING_PRIORITY.get(filing_type, 99)

        for entry in ext.get("historico_trimestral", []):
            periodo = entry.get("periodo")
            if not periodo:
                continue

            merge_key = _normalize_merge_key(entry)

            if merge_key not in by_period:
                seeded = _seed_field_sources(dict(entry), filing_type)
                by_period[merge_key] = {
                    "data": seeded, "priority": priority, "recency": ext_idx,
                }
            else:
                existing = by_period[merge_key]
                merged = _merge_period_entries(
                    existing["data"], entry,
                    existing["priority"], priority, filing_type,
                    new_recency=ext_idx,
                    existing_recency=existing.get("recency", 0),
                )
                by_period[merge_key]["data"] = merged

    periods = sorted(by_period.keys(),
                     key=lambda p: _period_sort_key(
                         by_period[p]["data"].get("periodo", p),
                         by_period[p]["data"]))
    return [by_period[p]["data"] for p in periods]


_BS_METADATA_KEYS = {
    "escala", "scale", "source_filing", "filing_type", "periodo",
    "fecha_fin", "fecha_corte", "moneda", "currency", "fuente_refs",
    "tipo_periodo", "duracion", "is_preliminary",
}
_CRITICAL_BS_FIELDS = (
    "activos_totales_usd",
    "pasivos_totales_usd",
    "patrimonio_usd",
    "deuda_total_usd",
    "caja_usd",
)


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


def _bs_sort_key(entry: dict) -> tuple[int, str]:
    """Sort helper for balance sheet snapshots (latest preferred)."""
    if not isinstance(entry, dict):
        return (0, "0000-00-00")

    fecha_fin = entry.get("fecha_fin") or entry.get("fecha_fin_utc")
    if isinstance(fecha_fin, str):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", fecha_fin)
        if m:
            return (1, m.group(1))

    periodo = entry.get("periodo")
    if isinstance(periodo, str):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", periodo)
        if m:
            return (1, m.group(1))
        y = re.search(r"(\d{4})", periodo)
        if y:
            return (1, f"{y.group(1)}-12-31")

    return (1, "0000-00-00")


def _bs_date_rank(entry: dict) -> int:
    _, date_str = _bs_sort_key(entry)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(date_str))
    if not m:
        return 0
    return int(f"{m.group(1)}{m.group(2)}{m.group(3)}")


def _bs_period_key(entry: dict):
    """Deterministic period key for BS fallback guards.

    Priority:
      1) fecha_fin (YYYY-MM-DD)
      2) fecha_corte (YYYY-MM-DD)
      3) periodo normalized (FY2024 / Q1-2024)
    """
    for date_field in ("fecha_fin", "fecha_corte"):
        raw = entry.get(date_field)
        if isinstance(raw, str):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
            if m:
                return m.group(1)

    periodo = entry.get("periodo")
    if not isinstance(periodo, str):
        return None
    normalized = re.sub(r"\s+", "", periodo.upper())
    m = re.search(r"(\d{4}-\d{2}-\d{2})", normalized)
    if m:
        return m.group(1)
    m = re.match(r"Q([1-4])[-_/]?(20\d{2})$", normalized)
    if m:
        return f"Q{m.group(1)}-{m.group(2)}"
    m = re.match(r"([1-4])Q[-_/]?(20\d{2})$", normalized)
    if m:
        return f"Q{m.group(1)}-{m.group(2)}"
    m = re.match(r"Q([1-4])[-_/]?FY[-_/]?(20\d{2})$", normalized)
    if m:
        return f"Q{m.group(1)}-{m.group(2)}"
    m = re.match(r"FY[-_/]?(20\d{2})$", normalized)
    if m:
        return f"FY{m.group(1)}"
    m = re.match(r"(20\d{2})$", normalized)
    if m:
        return f"FY{m.group(1)}"
    return None


def _coerce_finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
    elif isinstance(value, str):
        raw = value.strip().replace(",", "")
        if not raw:
            return None
        try:
            candidate = float(raw)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(candidate):
        return None
    return candidate


def _is_valid_critical_bs_value(value) -> bool:
    candidate = _coerce_finite_number(value)
    if candidate is None:
        return False
    return candidate >= 0


def _normalize_balance_sheet(value, filing_index: int, warnings: list[str]) -> dict:
    """Normaliza balance_sheet_ultimo a dict, ignorando entradas no válidas."""
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        candidates = [x for x in value if isinstance(x, dict)]
        if not candidates:
            warnings.append(
                f"balance_sheet_ultimo en filing #{filing_index} es list sin dicts; se ignora"
            )
            return {}
        # Prefer latest by fecha_fin / periodo; fallback to input order
        sorted_candidates = sorted(candidates, key=_bs_sort_key)
        selected = sorted_candidates[-1]
        selected_fecha = selected.get("fecha_fin") or selected.get("periodo") or "(sin fecha)"
        warnings.append(
            f"balance_sheet_ultimo en filing #{filing_index} venía en formato list; "
            f"se normalizó al entry más reciente ({selected_fecha})"
        )
        return selected

    warnings.append(
        f"balance_sheet_ultimo en filing #{filing_index} es tipo {type(value).__name__}; se ignora"
    )
    return {}


def _merge_balance_sheet(extractions: list[dict], warnings: list[str]) -> dict:
    """Pick best balance sheet and null-fill critical fields from lower-priority sources."""
    snapshots: list[dict] = []
    for idx, ext in enumerate(extractions, start=1):
        bs = _normalize_balance_sheet(
            ext.get("balance_sheet_ultimo"),
            filing_index=idx,
            warnings=warnings,
        )
        if not bs or all(v is None for k, v in bs.items() if _is_bs_data_field(k, v)):
            continue
        filing_type = _resolve_filing_type(ext)
        priority = FILING_PRIORITY.get(filing_type, 99)
        snapshots.append(
            {
                "bs": bs,
                "filing_type": filing_type,
                "priority": priority,
                "date_key": _bs_sort_key(bs),
                "date_rank": _bs_date_rank(bs),
                "period_key": _bs_period_key(bs),
            }
        )

    if not snapshots:
        return {}

    best_priority = min(int(item["priority"]) for item in snapshots)
    best_priority_snaps = [item for item in snapshots if int(item["priority"]) == best_priority]
    base_info = max(best_priority_snaps, key=lambda item: int(item["date_rank"]))
    base_period_key = base_info.get("period_key")
    base = _seed_field_sources(dict(base_info["bs"]), str(base_info["filing_type"]))
    provenance = dict(base.get("_field_sources", {}))

    candidates = sorted(
        [item for item in snapshots if item is not base_info],
        key=lambda item: (int(item["priority"]), -int(item["date_rank"])),
    )
    blocked_periods: set[tuple[str, str, str]] = set()
    for field in _CRITICAL_BS_FIELDS:
        if base.get(field) is not None:
            continue
        for candidate in candidates:
            candidate_period_key = candidate.get("period_key")
            if (not base_period_key) or (not candidate_period_key) or candidate_period_key != base_period_key:
                warn_key = (
                    str(candidate.get("filing_type", "UNKNOWN")),
                    str(base_period_key or "UNKNOWN"),
                    str(candidate_period_key or "UNKNOWN"),
                )
                if warn_key not in blocked_periods:
                    blocked_periods.add(warn_key)
                    warnings.append(
                        "balance_sheet_ultimo cross_period_blocked "
                        f"base={base_period_key or 'UNKNOWN'} "
                        f"candidate={candidate_period_key or 'UNKNOWN'} "
                        f"source={candidate.get('filing_type', 'UNKNOWN')}"
                    )
                continue
            val = candidate["bs"].get(field)
            if not _is_valid_critical_bs_value(val):
                continue
            base[field] = val
            source_ft = str(candidate["filing_type"])
            provenance[field] = f"{source_ft}:fallback_critical"
            warnings.append(
                f"balance_sheet_ultimo.{field} completado desde {source_ft} via fallback_critical"
            )
            break

    # ── Imputation pass (V5.1) ──
    _impute_balance_identity(base, provenance, warnings)
    _impute_deuda_total(base, provenance, warnings)

    base["_field_sources"] = provenance
    return base


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


# ── Imputation helpers (A1/A2 — V5.1 plan) ──────────────────────────

_IDENTITY_FIELDS = ("activos_totales_usd", "pasivos_totales_usd", "patrimonio_usd")


def _impute_balance_identity(
    base: dict, provenance: dict, warnings: list[str]
) -> None:
    """Impute missing balance sheet component from accounting identity.

    Rule: Assets = Liabilities + Equity.  If exactly 2 of 3 are non-null,
    compute the third.  Guards: result must be finite and >= 0.
    Never overwrites an existing non-null value.
    """
    vals = {f: _coerce_finite_number(base.get(f)) for f in _IDENTITY_FIELDS}
    present = {f for f, v in vals.items() if v is not None}
    missing = set(_IDENTITY_FIELDS) - present

    if len(missing) != 1:
        return  # need exactly 2-of-3

    field = missing.pop()
    a = vals["activos_totales_usd"]
    p = vals["pasivos_totales_usd"]
    e = vals["patrimonio_usd"]

    if field == "pasivos_totales_usd":
        computed = a - e  # type: ignore[operator]
        formula = f"activos({a}) - patrimonio({e})"
    elif field == "patrimonio_usd":
        computed = a - p  # type: ignore[operator]
        formula = f"activos({a}) - pasivos({p})"
    else:  # activos_totales_usd
        computed = p + e  # type: ignore[operator]
        formula = f"pasivos({p}) + patrimonio({e})"

    if not math.isfinite(computed) or computed < 0:
        warnings.append(
            f"balance_sheet_ultimo._impute_balance_identity: "
            f"skipped {field} — computed {computed} via {formula} (negative/non-finite)"
        )
        return

    base[field] = computed
    provenance[field] = "IMPUTED:balance_identity"
    warnings.append(
        f"balance_sheet_ultimo.{field} imputed via identity: {formula} = {computed}"
    )


def _impute_deuda_total(
    base: dict, provenance: dict, warnings: list[str]
) -> None:
    """Impute deuda_total_usd from long-term + short-term debt components.

    Strategy:
      - Both LT and ST present → sum  (IMPUTED:debt_components)
      - Only LT present → conservative estimate (IMPUTED:long_term_only)
    """
    if _is_valid_critical_bs_value(base.get("deuda_total_usd")):
        return  # already populated

    lt = _coerce_finite_number(base.get("deuda_largo_plazo_usd"))
    st = _coerce_finite_number(base.get("deuda_corto_plazo_usd"))

    if lt is not None and st is not None:
        computed = lt + st
        tag = "IMPUTED:debt_components"
        formula = f"LT({lt}) + ST({st})"
    elif lt is not None:
        computed = lt
        tag = "IMPUTED:long_term_only"
        formula = f"LT({lt}) only"
    else:
        return  # nothing to impute from

    if not math.isfinite(computed) or computed < 0:
        warnings.append(
            f"balance_sheet_ultimo._impute_deuda_total: "
            f"skipped — computed {computed} via {formula} (negative/non-finite)"
        )
        return

    base["deuda_total_usd"] = computed
    provenance["deuda_total_usd"] = tag
    warnings.append(
        f"balance_sheet_ultimo.deuda_total_usd imputed: {formula} = {computed}"
    )


def _warn_lease_only_debt_missing(tp_like: dict, warnings: list[str]) -> None:
    """Warn when only lease liabilities exist but debt components are missing.

    This is intentional: lease liabilities are not included in deuda_total_usd.
    """
    bs = tp_like.get("balance_sheet_ultimo", {})
    if not isinstance(bs, dict):
        return
    if _is_valid_critical_bs_value(bs.get("deuda_total_usd")):
        return

    lt = _coerce_finite_number(bs.get("deuda_largo_plazo_usd"))
    st = _coerce_finite_number(bs.get("deuda_corto_plazo_usd"))
    if lt is not None or st is not None:
        return

    lease = tp_like.get("lease_data", {})
    if not isinstance(lease, dict):
        return
    lease_total = _coerce_finite_number(lease.get("lease_liabilities_total_usd"))
    lease_current = _coerce_finite_number(lease.get("lease_liabilities_current_usd"))
    lease_non_current = _coerce_finite_number(lease.get("lease_liabilities_non_current_usd"))
    if lease_total is None and lease_current is None and lease_non_current is None:
        return

    msg = (
        "balance_sheet_ultimo lease_only_not_used_for_total_debt: "
        "lease liabilities detected but financial debt components are missing"
    )
    if msg not in warnings:
        warnings.append(msg)


def _normalize_merge_key(entry: dict) -> str:
    """V6.2 1B.1: Normalized merge key for period deduplication.

    Key = (periodo_norm, fecha_fin_norm, tipo_periodo_norm, moneda_original_norm)
    Falls back to just periodo if new fields not present.
    """
    periodo = str(entry.get("periodo", "")).strip().upper()
    fecha_fin = str(entry.get("fecha_fin", "")).strip()
    tipo_periodo = str(entry.get("tipo_periodo", "")).strip().lower()
    moneda = str(entry.get("moneda_original", "")).strip().upper()

    # Normalize periodo: remove spaces, standardize FY/Q format
    periodo = re.sub(r"\s+", "", periodo)

    # For backward compat: if only periodo exists, use it alone
    if not fecha_fin and not tipo_periodo:
        return periodo

    return f"{periodo}|{fecha_fin}|{tipo_periodo}|{moneda}"


def _merge_period_entries(existing: dict, new_entry: dict,
                         existing_priority: int, new_priority: int,
                         new_source: str = "UNKNOWN",
                         new_recency: int = 0,
                         existing_recency: int = 0) -> dict:
    """Merge two period entries, resolving conflicts by priority.

    Rules (V6.2):
      - Tier superior gana siempre (lower priority number wins).
      - En empate de tier: filing más reciente gana (lower index = more recent).
      - All conflicts recorded in _merge_conflicts for reconciliation.
      - Null-fill is ONLY allowed when new source has equal or better
        (lower) priority.
      - Provenance tracked in _field_sources.
    """
    merged = dict(existing)
    provenance = dict(merged.get("_field_sources", {}))
    conflicts: list[dict] = []

    for key, new_val in new_entry.items():
        if key in ("periodo", "fecha_fin", "fuente_refs", "_field_sources",
                    "_merge_conflicts", "tipo_periodo", "moneda_original"):
            continue

        existing_val = merged.get(key)

        if existing_val is None and new_val is not None:
            # Null-fill: only if new source is same or better priority
            if new_priority <= existing_priority:
                merged[key] = new_val
                provenance[key] = new_source
        elif existing_val is not None and new_val is not None and existing_val != new_val:
            # Capture the previous source BEFORE modifying provenance
            prev_source = provenance.get(key, "UNKNOWN")

            # Scale guard: prevent tiny scale-corrupted values from overriding
            # a plausible absolute amount (e.g. 15 vs 9_000_000_000).
            scale_pref = _scale_guard_preference(key, existing_val, new_val)
            if scale_pref == "new":
                merged[key] = new_val
                provenance[key] = f"{new_source}:scale_guard"
                conflicts.append({
                    "campo": key,
                    "valor_kept": new_val, "valor_dropped": existing_val,
                    "source_kept": new_source, "source_dropped": prev_source,
                    "reason": "scale_guard",
                })
                continue
            if scale_pref == "existing":
                conflicts.append({
                    "campo": key,
                    "valor_kept": existing_val, "valor_dropped": new_val,
                    "source_kept": prev_source, "source_dropped": new_source,
                    "reason": "scale_guard",
                })
                continue

            # Conflict — use higher priority (lower number wins)
            if new_priority < existing_priority:
                merged[key] = new_val
                provenance[key] = new_source
                conflicts.append({
                    "campo": key,
                    "valor_kept": new_val, "valor_dropped": existing_val,
                    "source_kept": new_source, "source_dropped": prev_source,
                    "reason": "priority",
                })
            elif new_priority == existing_priority and new_recency < existing_recency:
                # V6.2: Same tier tie-break by recency (lower index = more recent filing wins)
                merged[key] = new_val
                provenance[key] = f"{new_source}:recency"
                conflicts.append({
                    "campo": key,
                    "valor_kept": new_val, "valor_dropped": existing_val,
                    "source_kept": new_source, "source_dropped": prev_source,
                    "reason": "recency",
                })
            else:
                # Existing wins — new is dropped
                conflicts.append({
                    "campo": key,
                    "valor_kept": existing_val, "valor_dropped": new_val,
                    "source_kept": prev_source, "source_dropped": new_source,
                    "reason": "priority" if new_priority > existing_priority else "recency",
                })

    merged["_field_sources"] = provenance
    merged["_merge_conflicts"] = existing.get("_merge_conflicts", []) + conflicts
    return merged


def _scale_guard_preference(field: str, existing_val, new_val):
    """Return preferred side when one value is clearly scale-corrupted.

    Guard criteria:
    - monetary field (`*_usd`)
    - both values numeric
    - one value >= 1M and the other < 1M
    - magnitude gap >= 1000x
    """
    if not isinstance(field, str) or not field.endswith("_usd"):
        return None

    existing_num = _coerce_finite_number(existing_val)
    new_num = _coerce_finite_number(new_val)
    if existing_num is None or new_num is None:
        return None

    existing_abs = abs(existing_num)
    new_abs = abs(new_num)
    high = max(existing_abs, new_abs)
    low = min(existing_abs, new_abs)
    if low <= 0:
        return None
    if high < 1_000_000 or low >= 1_000_000:
        return None
    if (high / low) < 1000.0:
        return None

    return "new" if new_abs > existing_abs else "existing"


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
