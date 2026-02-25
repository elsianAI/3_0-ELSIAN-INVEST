"""
TP_VALIDATOR: Ejecuta gates de calidad sobre TruthPack.
100% determinista, 0 tokens LLM.

Gates:
  N1) BALANCE_IDENTITY: Assets ≈ Liabilities + Equity (±2%)
  N2) CASHFLOW_IDENTITY: CFO + CFI + CFF ≈ ΔCash (±5%)
  N3) UNIDADES_SANITY: No saltos 1000x entre periodos consecutivos
  N4) EV_SANITY: EV >= 0 o justificado
  N5) MARGIN_SANITY: Márgenes dentro de rangos sectoriales
  N6) TTM_SANITY: TTM consistente con anuales y trimestrales
  N7) DATA_COMPLETENESS: % campos null por sección

Confidence score: 100 - 15×FAIL - 5×WARN - 10×SKIP
"""

import json
import re
from typing import Optional


def _num(val) -> Optional[float]:
    """Return val only if it's a real number (not bool, not dict, etc.)."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return val
    return None
import sys
from pathlib import Path
from datetime import datetime, timezone


# V6.2 1B.3: Expected fields by filing doc type for adjusted completeness
EXPECTED_FIELDS_BY_DOC_TYPE = {
    "10-K": {
        "historico_anual": [
            "ingresos_usd", "cogs_usd", "gross_profit_usd", "ebit_usd",
            "net_income_usd", "cfo_usd", "cfi_usd", "cff_usd", "capex_usd",
            "delta_cash_usd", "depreciation_usd", "income_tax_usd",
        ],
        "balance_sheet_ultimo": [
            "activos_totales_usd", "pasivos_totales_usd", "patrimonio_usd",
            "caja_usd", "deuda_total_usd",
        ],
    },
    "20-F": {
        "historico_anual": [
            "ingresos_usd", "ebit_usd", "net_income_usd",
            "cfo_usd", "cfi_usd", "cff_usd", "capex_usd",
        ],
        "balance_sheet_ultimo": [
            "activos_totales_usd", "pasivos_totales_usd", "patrimonio_usd",
            "caja_usd",
        ],
    },
    "ANNUAL_REPORT": {
        "historico_anual": [
            "ingresos_usd", "ebit_usd", "net_income_usd",
            "cfo_usd", "cfi_usd", "cff_usd",
        ],
        "balance_sheet_ultimo": [
            "activos_totales_usd", "pasivos_totales_usd", "patrimonio_usd",
            "caja_usd",
        ],
    },
    "10-Q": {
        "historico_trimestral": [
            "ingresos_usd", "net_income_usd", "cfo_usd",
        ],
    },
    "TRANSCRIPT": {
        "historico_anual": ["ingresos_usd"],
    },
    "_default": {
        "historico_anual": ["ingresos_usd", "net_income_usd"],
    },
}


GATES = [
    {"name": "BALANCE_IDENTITY",   "tolerance": 0.02, "critical": True},
    {"name": "CASHFLOW_IDENTITY",  "tolerance": 0.05, "critical": True},
    {"name": "UNIDADES_SANITY",    "tolerance": None,  "critical": False},
    {"name": "EV_SANITY",          "tolerance": None,  "critical": False},
    {"name": "MARGIN_SANITY",      "tolerance": None,  "critical": False},
    {"name": "TTM_SANITY",         "tolerance": 0.20, "critical": False},
    {"name": "TTM_CONSECUTIVE",    "tolerance": None,  "critical": True},
    {"name": "RECENCY_SANITY",     "tolerance": None,  "critical": False},
    {"name": "CORE_FILING_COVERAGE", "tolerance": None, "critical": False},
    {"name": "DATA_COMPLETENESS",  "tolerance": None,  "critical": False},
]

# Sector-typical margin ranges for sanity checking.
# Ranges are (min%, max%) for gross, operating, and net margins.
SECTOR_MARGINS = {
    "default":              {"gross": (-10, 90), "operating": (-50, 60), "net": (-100, 50)},
    # Technology / Software
    "Software":             {"gross": (50, 95),  "operating": (-30, 55), "net": (-50, 45)},
    "SaaS":                 {"gross": (55, 95),  "operating": (-40, 50), "net": (-60, 40)},
    "Semiconductors":       {"gross": (30, 80),  "operating": (-20, 55), "net": (-30, 50)},
    "Technology Hardware":  {"gross": (15, 65),  "operating": (-15, 35), "net": (-25, 30)},
    # Healthcare / Biotech
    "Biotechnology":        {"gross": (40, 95),  "operating": (-200, 50), "net": (-250, 45)},
    "Pharmaceuticals":      {"gross": (50, 90),  "operating": (-30, 50), "net": (-40, 40)},
    "Medical Devices":      {"gross": (40, 80),  "operating": (-20, 40), "net": (-30, 35)},
    "Healthcare Services":  {"gross": (10, 60),  "operating": (-15, 25), "net": (-20, 20)},
    # Consumer / Retail
    "Retail":               {"gross": (15, 55),  "operating": (-10, 20), "net": (-15, 15)},
    "Consumer Staples":     {"gross": (20, 60),  "operating": (0, 25),   "net": (-5, 20)},
    "Restaurants":          {"gross": (20, 70),  "operating": (-10, 25), "net": (-15, 18)},
    # Industrial / Energy
    "Industrials":          {"gross": (15, 55),  "operating": (-10, 25), "net": (-15, 20)},
    "Energy":               {"gross": (10, 70),  "operating": (-30, 40), "net": (-40, 30)},
    "Mining":               {"gross": (10, 65),  "operating": (-25, 45), "net": (-35, 35)},
    # Financial
    "Financial Services":   {"gross": (20, 95),  "operating": (-20, 55), "net": (-25, 45)},
    "Insurance":            {"gross": (10, 60),  "operating": (-10, 30), "net": (-15, 25)},
    "REITs":                {"gross": (20, 80),  "operating": (-10, 50), "net": (-15, 40)},
    # Other
    "Telecom":              {"gross": (30, 70),  "operating": (-10, 35), "net": (-20, 25)},
    "Media & Entertainment": {"gross": (25, 75), "operating": (-20, 35), "net": (-30, 30)},
}


def validate(tp_with_metrics: dict) -> dict:
    """
    Ejecuta todos los gates sobre el TruthPack con métricas.
    Retorna TruthPack completo con sección `data_quality` añadida.
    """
    result = dict(tp_with_metrics)
    gates_results = []
    warnings = []

    # Execute each gate
    gate_funcs = {
        "BALANCE_IDENTITY": _gate_balance_identity,
        "CASHFLOW_IDENTITY": _gate_cashflow_identity,
        "UNIDADES_SANITY": _gate_unidades_sanity,
        "EV_SANITY": _gate_ev_sanity,
        "MARGIN_SANITY": _gate_margin_sanity,
        "TTM_SANITY": _gate_ttm_sanity,
        "TTM_CONSECUTIVE": _gate_ttm_consecutive,
        "RECENCY_SANITY": _gate_recency_sanity,
        "CORE_FILING_COVERAGE": _gate_core_filing_coverage,
        "DATA_COMPLETENESS": _gate_data_completeness,
    }

    for gate_def in GATES:
        gate_name = gate_def["name"]
        func = gate_funcs.get(gate_name)
        if func:
            gate_result = func(result)
            gate_result["critical"] = gate_def["critical"]
            gates_results.append(gate_result)

            if gate_result["status"] == "WARNING":
                warnings.append(f"{gate_name}: {gate_result.get('note', '')}")
            elif gate_result["status"] == "FAIL":
                warnings.append(f"CRITICAL — {gate_name}: {gate_result.get('note', '')}")

    # Calculate overall
    overall = _overall_status(gates_results)
    confidence = _calc_confidence(gates_results)

    # V6.2 1B.3: Compute adjusted completeness by doc type
    completitud_ajustada = _compute_completitud_ajustada(result)

    # V6.2 1B.4: Cross-filing reconciliation
    reconciliation_log = _reconcile_cross_filing(result)

    # Build data_quality section
    result["data_quality"] = {
        "status": overall,
        "validaciones": {g["name"]: {"status": g["status"], "detalle": g.get("note", "")} for g in gates_results},
        "gates": gates_results,
        "overall_status": overall,
        "warnings": warnings,
        "confidence_score": confidence,
        "completitud_ajustada_por_tipo": completitud_ajustada,
        "reconciliation_log": reconciliation_log,
        "faltantes_criticos": _find_critical_missing(result),
        "limitaciones": _find_limitations(result),
        "nota": (
            f"Validation by tp_validator.py. "
            f"Overall: {overall}. Confidence: {confidence}%. "
            f"{len(warnings)} warnings."
            f" Adjusted completeness: {completitud_ajustada.get('pct', 0):.0f}%."
        ),
    }

    result["recomendacion_siguiente_paso"] = {
        "puede_pasar_a_implied_expectations": overall != "FAIL",
        "condiciones": warnings[:3] if overall == "FAIL" else [],
    }

    # Inject _meta
    result["_meta"] = {
        "timestamp_validacion": datetime.now(timezone.utc).isoformat(),
        "version_schema": "TruthPack_v1",
        "tp_validator_version": "1.0.0",
        "notas_auditoria": f"{len(gates_results)} gates executed, {confidence}% confidence",
    }

    return result


def _gate_balance_identity(tp: dict) -> dict:
    """Assets = Liabilities + Equity. Tolerance 2%."""
    bs = tp.get("balance_sheet_ultimo", {})
    assets = _num(bs.get("activos_totales_usd")) or _num(bs.get("total_assets_usd"))
    liabilities = _num(bs.get("pasivos_totales_usd")) or _num(bs.get("total_liabilities_usd"))
    equity = _num(bs.get("patrimonio_usd")) or _num(bs.get("equity_usd"))

    if assets is None or liabilities is None or equity is None:
        # Fallback: try to find BS data embedded in the latest annual entry
        for entry in reversed(tp.get("historico_anual", [])):
            a = _num(entry.get("activos_totales_usd"))
            l = _num(entry.get("pasivos_totales_usd"))
            e = _num(entry.get("patrimonio_usd"))
            if a is not None and l is not None and e is not None:
                assets, liabilities, equity = a, l, e
                break

    # ── Belt-and-suspenders imputation (V5.1 — A3, Codex Adj #4) ──
    # Use temporary variables to avoid corrupting values from historico_anual fallback.
    imputed_field = None
    a_imp, l_imp, e_imp = assets, liabilities, equity
    count_present = sum(1 for x in (a_imp, l_imp, e_imp) if x is not None)
    if count_present == 2:
        if a_imp is not None and e_imp is not None and l_imp is None:
            l_imp = a_imp - e_imp
            imputed_field = "pasivos_totales_usd"
        elif a_imp is not None and l_imp is not None and e_imp is None:
            e_imp = a_imp - l_imp
            imputed_field = "patrimonio_usd"
        elif l_imp is not None and e_imp is not None and a_imp is None:
            a_imp = l_imp + e_imp
            imputed_field = "activos_totales_usd"
        if imputed_field and any(v is not None and v < 0 for v in (a_imp, l_imp, e_imp)):
            imputed_field = None  # negative → invalid, discard imputation
        else:
            assets, liabilities, equity = a_imp, l_imp, e_imp

    if assets is None or liabilities is None or equity is None:
        return {"name": "BALANCE_IDENTITY", "status": "FAIL",
                "note": "Missing balance sheet data — critical gate cannot be skipped"}

    expected = liabilities + equity
    if expected == 0:
        return {"name": "BALANCE_IDENTITY", "status": "SKIP", "note": "L+E = 0"}

    diff_pct = abs(assets - expected) / abs(expected)
    imp_note = f" (imputed {imputed_field})" if imputed_field else ""
    if diff_pct <= 0.02:
        return {"name": "BALANCE_IDENTITY", "status": "PASS", "note": f"Diff: {diff_pct:.2%}{imp_note}", "actual_value": diff_pct}
    else:
        return {"name": "BALANCE_IDENTITY", "status": "FAIL", "note": f"Diff: {diff_pct:.2%} > 2%{imp_note}", "actual_value": diff_pct}


def _find_best_cf_entry(annual: list[dict]) -> tuple[Optional[dict], str]:
    """Find the best annual entry with complete CF data (CFO+CFI+CFF).

    Tries annual[-1] first (latest FY), then falls back to earlier FYs.
    Returns (entry, source_note) or (None, reason).
    """
    if not annual:
        return None, "No annual data"

    # Try from most recent to oldest, skipping partial periods (H1, 9M, etc.)
    for i in range(len(annual) - 1, -1, -1):
        entry = annual[i]
        # Skip partial periods — they don't represent a full FY
        if entry.get("_periodo_parcial"):
            continue
        cfo = _num(entry.get("cfo_usd"))
        cfi = _num(entry.get("cfi_usd"))
        cff = _num(entry.get("cff_usd"))
        if cfo is not None and cfi is not None and cff is not None:
            periodo = entry.get("periodo", f"index_{i}")
            if i == len(annual) - 1:
                return entry, f"Using latest FY ({periodo})"
            else:
                return entry, f"Fallback to {periodo} (latest FY missing CF components)"
    return None, "No FY has complete CF data (CFO+CFI+CFF)"


def _gate_cashflow_identity(tp: dict) -> dict:
    """Cash bridge: CFO + CFI + CFF + FX + Other ≈ ΔCash. Tolerance 5%."""
    annual = tp.get("historico_anual", [])
    if not annual:
        return {"name": "CASHFLOW_IDENTITY", "status": "SKIP", "note": "No annual data"}

    fy0, source_note = _find_best_cf_entry(annual)
    if fy0 is None:
        return {"name": "CASHFLOW_IDENTITY", "status": "FAIL",
                "note": f"Missing CF components (CFO/CFI/CFF) — {source_note}"}

    cfo = _num(fy0.get("cfo_usd"))
    cfi = _num(fy0.get("cfi_usd"))
    cff = _num(fy0.get("cff_usd"))

    if cfo is None or cfi is None or cff is None:
        return {"name": "CASHFLOW_IDENTITY", "status": "FAIL",
                "note": "Missing CF components (CFO/CFI/CFF) — critical gate cannot be skipped"}

    # FX and other adjustments: treat None as 0 for the bridge calculation
    fx = _num(fy0.get("fx_effect_cash_usd")) or 0
    other = _num(fy0.get("otros_ajustes_caja_usd")) or 0
    fx_present = _num(fy0.get("fx_effect_cash_usd")) is not None
    other_present = _num(fy0.get("otros_ajustes_caja_usd")) is not None

    bridge_with_fx = cfo + cfi + cff + fx + other
    bridge_without_fx = cfo + cfi + cff + other
    delta_cash = _num(fy0.get("delta_cash_usd")) or _num(fy0.get("cambio_caja_usd"))

    if delta_cash is None:
        return {"name": "CASHFLOW_IDENTITY", "status": "SKIP",
                "note": (f"CF components present (bridge={bridge_with_fx:,.0f}, "
                         f"fx={fx:,.0f}, other={other:,.0f}), "
                         f"but no delta_cash to cross-check. {source_note}")}

    abs_diff_with_fx = abs(bridge_with_fx - delta_cash)
    denominator_with_fx = max(abs(delta_cash), abs(bridge_with_fx), 1)
    rel_diff_with_fx = abs_diff_with_fx / denominator_with_fx

    # Proportional absolute tolerance: larger of $50K or 0.5% of the bigger CF figure
    absolute_tolerance = max(50_000, 0.005 * denominator_with_fx)

    # Build audit note
    audit = (f"bridge={bridge_with_fx:,.0f} (CFO={cfo:,.0f}+CFI={cfi:,.0f}"
             f"+CFF={cff:,.0f}+FX={fx:,.0f}+Other={other:,.0f}), "
             f"delta_cash={delta_cash:,.0f}, "
             f"abs_diff={abs_diff_with_fx:,.0f}, rel_diff={rel_diff_with_fx:.2%}. {source_note}")

    if rel_diff_with_fx <= 0.05 or abs_diff_with_fx <= absolute_tolerance:
        return {"name": "CASHFLOW_IDENTITY", "status": "PASS", "note": audit}

    # Fallback check for filing presentation ambiguity:
    # some statements present delta_cash pre-FX. If with-FX fails but without-FX
    # passes, downgrade to WARNING (do not hard-fail).
    if abs(fx) > 0:
        abs_diff_without_fx = abs(bridge_without_fx - delta_cash)
        denominator_without_fx = max(abs(delta_cash), abs(bridge_without_fx), 1)
        rel_diff_without_fx = abs_diff_without_fx / denominator_without_fx
        if rel_diff_without_fx <= 0.05 or abs_diff_without_fx <= absolute_tolerance:
            return {
                "name": "CASHFLOW_IDENTITY",
                "status": "WARNING",
                "note": (
                    f"{audit} bridge_without_fx={bridge_without_fx:,.0f}, "
                    f"abs_diff_without_fx={abs_diff_without_fx:,.0f}, "
                    f"rel_diff_without_fx={rel_diff_without_fx:.2%}. "
                    "Possible filing presentation ambiguity: delta_cash appears pre-FX"
                ),
            }

    # WARNING: moderate deviation AND both FX/other adjustments are missing
    if rel_diff_with_fx <= 0.10 and not fx_present and not other_present:
        return {"name": "CASHFLOW_IDENTITY", "status": "WARNING",
                "note": f"Moderate deviation, FX/other adjustments not extracted. {audit}"}

    return {"name": "CASHFLOW_IDENTITY", "status": "FAIL", "note": audit}


def _gate_unidades_sanity(tp: dict) -> dict:
    """No saltos 1000x entre períodos consecutivos."""
    annual = tp.get("historico_anual", [])
    anomalies = []

    for i in range(1, len(annual)):
        prev = annual[i - 1]
        curr = annual[i]
        for field in ["ingresos_usd", "ebit_usd", "net_income_usd", "cfo_usd"]:
            p_val = prev.get(field)
            c_val = curr.get(field)
            if isinstance(p_val, (int, float)) and isinstance(c_val, (int, float)) and p_val != 0:
                ratio = abs(c_val / p_val)
                if ratio > 1000 or ratio < 0.001:
                    anomalies.append(f"{field}: {prev.get('periodo')}→{curr.get('periodo')} ratio={ratio:.0f}x")

    if not anomalies:
        return {"name": "UNIDADES_SANITY", "status": "PASS", "note": "No 1000x jumps detected"}
    else:
        return {"name": "UNIDADES_SANITY", "status": "FAIL", "note": f"Anomalies: {'; '.join(anomalies[:3])}"}


def _gate_ev_sanity(tp: dict) -> dict:
    """EV >= 0."""
    metricas = tp.get("metricas_derivadas", {})
    ev = _num(metricas.get("ev_usd")) or _num(tp.get("mercado", {}).get("enterprise_value_usd"))

    if ev is None:
        return {"name": "EV_SANITY", "status": "SKIP", "note": "EV not calculated"}
    if ev >= 0:
        return {"name": "EV_SANITY", "status": "PASS", "note": f"EV = {ev:,.0f}"}
    else:
        return {"name": "EV_SANITY", "status": "WARNING", "note": f"Negative EV = {ev:,.0f} (cash > market_cap + debt)"}


def _resolve_sector_margins(tp: dict) -> tuple[dict, str]:
    """Resolve the best margin ranges for this company's sector/industry."""
    empresa = tp.get("empresa", {})
    # Try industry first (more specific), then sector, then default
    for field in ("industria", "industry", "sector"):
        value = empresa.get(field, "")
        if value and value in SECTOR_MARGINS:
            return SECTOR_MARGINS[value], value
    return SECTOR_MARGINS["default"], "default"


def _gate_margin_sanity(tp: dict) -> dict:
    """Márgenes dentro de rangos sectoriales."""
    metricas = tp.get("metricas_derivadas", {})
    ranges, sector_used = _resolve_sector_margins(tp)
    issues = []

    for metric, key in [("gross", "margen_bruto_pct"), ("operating", "margen_operativo_pct"), ("net", "margen_neto_pct")]:
        val = metricas.get(key)
        if val is not None:
            lo, hi = ranges[metric]
            if val < lo or val > hi:
                issues.append(f"{key}={val:.1f}% outside [{lo},{hi}] (sector={sector_used})")

    if not issues:
        return {"name": "MARGIN_SANITY", "status": "PASS", "note": f"Margins within expected ranges (sector={sector_used})"}
    else:
        return {"name": "MARGIN_SANITY", "status": "WARNING", "note": "; ".join(issues)}


def _gate_ttm_sanity(tp: dict) -> dict:
    """TTM consistente con anuales y trimestrales."""
    ttm = tp.get("ttm", {})
    annual = tp.get("historico_anual", [])

    if not ttm or ttm.get("metodo") == "no_disponible":
        return {"name": "TTM_SANITY", "status": "SKIP", "note": "TTM not calculated"}

    if not annual:
        return {"name": "TTM_SANITY", "status": "SKIP", "note": "No annual data to compare"}

    fy0 = annual[-1]
    ttm_rev = ttm.get("ingresos_usd")
    fy0_rev = fy0.get("ingresos_usd")

    if ttm_rev is None or fy0_rev is None or fy0_rev == 0:
        return {"name": "TTM_SANITY", "status": "SKIP", "note": "Cannot compare TTM vs FY0 revenue"}

    ratio = ttm_rev / fy0_rev
    if 0.5 <= ratio <= 2.0:
        return {"name": "TTM_SANITY", "status": "PASS", "note": f"TTM/FY0 revenue ratio: {ratio:.2f}"}
    else:
        return {"name": "TTM_SANITY", "status": "WARNING", "note": f"TTM/FY0 revenue ratio: {ratio:.2f} — unusually large deviation"}


def _gate_ttm_consecutive(tp: dict) -> dict:
    """Validate that the TTM quarters are actually consecutive (no cross-era)."""
    ttm = tp.get("ttm", {})
    if not ttm or ttm.get("metodo") != "suma_4_trimestres":
        if ttm and ttm.get("metodo") == "no_disponible":
            return {"name": "TTM_CONSECUTIVE", "status": "SKIP", "note": "TTM not calculated"}
        # FY0_fallback triggered by non-consecutive quarters → WARNING
        if ttm and ttm.get("metodo") == "FY0_fallback":
            nota = ttm.get("nota", "")
            if "NO consecutivos" in nota:
                return {"name": "TTM_CONSECUTIVE", "status": "WARNING",
                        "note": f"FY0_fallback triggered by non-consecutive quarters: {nota}"}
        return {"name": "TTM_CONSECUTIVE", "status": "PASS",
                "note": f"TTM method: {ttm.get('metodo', 'none')} — not based on quarterly sum"}

    nota = ttm.get("nota", "")
    if "NO consecutivos" in nota or "rechazado" in nota:
        return {"name": "TTM_CONSECUTIVE", "status": "FAIL",
                "note": f"TTM quarters not consecutive: {nota}"}

    return {"name": "TTM_CONSECUTIVE", "status": "PASS",
            "note": f"TTM passed consecutiveness check. {nota}"}


def _extract_year_from_entry(entry: dict) -> Optional[int]:
    fecha_fin = str(entry.get("fecha_fin", "")).strip()
    if fecha_fin:
        m = re.search(r"(19|20)\d{2}", fecha_fin)
        if m:
            return int(m.group(0))
    periodo = str(entry.get("periodo", "")).strip()
    if periodo:
        m = re.search(r"(19|20)\d{2}", periodo)
        if m:
            return int(m.group(0))
    return None


def _gate_recency_sanity(tp: dict) -> dict:
    """Warn when the FY base used by TP is too old (>2 years)."""
    annual = tp.get("historico_anual", [])
    years = [y for y in (_extract_year_from_entry(a) for a in annual) if y is not None]
    if not years:
        return {"name": "RECENCY_SANITY", "status": "SKIP", "note": "No annual period year available"}

    base_year = max(years)
    current_year = datetime.now(timezone.utc).year
    age = current_year - base_year
    if age > 2:
        return {
            "name": "RECENCY_SANITY",
            "status": "WARNING",
            "note": f"FY base is {age} years old (base={base_year}, current={current_year})",
            "base_year": base_year,
        }
    return {
        "name": "RECENCY_SANITY",
        "status": "PASS",
        "note": f"FY base recency OK (base={base_year}, current={current_year})",
        "base_year": base_year,
    }


def _gate_core_filing_coverage(tp: dict) -> dict:
    """Warn when no annual core filing (10-K/20-F) appears in field provenance."""
    source_types = set()
    for entry in tp.get("historico_anual", []):
        for value in entry.get("_field_sources", {}).values():
            if value:
                source_types.add(str(value).upper())
    for entry in tp.get("historico_trimestral", []):
        for value in entry.get("_field_sources", {}).values():
            if value:
                source_types.add(str(value).upper())
    for value in tp.get("balance_sheet_ultimo", {}).get("_field_sources", {}).values():
        if value:
            source_types.add(str(value).upper())

    has_core_annual = any(
        ("10-K" in s) or ("20-F" in s) or ("ANNUAL_REPORT" in s) or ("ANNUAL REPORT" in s)
        for s in source_types
    )
    if has_core_annual:
        return {
            "name": "CORE_FILING_COVERAGE",
            "status": "PASS",
            "note": f"Annual core filing present in provenance: {sorted(source_types)[:5]}",
        }
    return {
        "name": "CORE_FILING_COVERAGE",
        "status": "WARNING",
        "note": f"No 10-K/20-F/ANNUAL_REPORT found in field provenance (found={sorted(source_types)[:5]})",
    }


def _gate_data_completeness(tp: dict) -> dict:
    """Cuenta campos null por sección."""
    sections = {
        "historico_anual": tp.get("historico_anual", []),
        "historico_trimestral": tp.get("historico_trimestral", []),
        "balance_sheet_ultimo": [tp.get("balance_sheet_ultimo", {})],
        "metricas_derivadas": [tp.get("metricas_derivadas", {})],
    }

    total_fields = 0
    null_fields = 0
    details = {}

    for section_name, items in sections.items():
        if not items:
            continue
        s_total = 0
        s_null = 0
        for item in (items if isinstance(items, list) else [items]):
            if isinstance(item, dict):
                for k, v in item.items():
                    if k.startswith("_") or k in ("periodo", "fecha_fin", "fuente_refs"):
                        continue
                    s_total += 1
                    if v is None:
                        s_null += 1
        total_fields += s_total
        null_fields += s_null
        if s_total > 0:
            details[section_name] = f"{s_null}/{s_total} null ({s_null/s_total*100:.0f}%)"

    completeness_pct = ((total_fields - null_fields) / total_fields * 100) if total_fields > 0 else 0
    status = "PASS" if completeness_pct >= 50 else "WARNING"

    return {
        "name": "DATA_COMPLETENESS",
        "status": status,
        "note": f"Overall: {completeness_pct:.0f}% complete. {details}",
        "completeness_pct": completeness_pct,
    }


def _compute_completitud_ajustada(tp: dict) -> dict:
    """V6.2 1B.3: Compute completeness adjusted by document type.

    Instead of counting ALL fields globally, only count fields that are
    expected for the primary filing type.  This gives TEP (20-F) a
    realistic score instead of penalizing for missing 10-K-specific fields.
    """
    # Determine primary doc type from field provenance
    source_types: dict[str, int] = {}
    for entry in tp.get("historico_anual", []):
        for val in entry.get("_field_sources", {}).values():
            if val:
                ft = str(val).split(":")[0].upper()
                source_types[ft] = source_types.get(ft, 0) + 1
    for val in tp.get("balance_sheet_ultimo", {}).get("_field_sources", {}).values():
        if val:
            ft = str(val).split(":")[0].upper()
            source_types[ft] = source_types.get(ft, 0) + 1

    primary_type = max(source_types, key=source_types.get) if source_types else "_default"  # type: ignore
    expected = EXPECTED_FIELDS_BY_DOC_TYPE.get(
        primary_type,
        EXPECTED_FIELDS_BY_DOC_TYPE.get("_default", {}),
    )

    total_expected = 0
    total_present = 0
    details: dict[str, str] = {}

    # Check annual fields
    annual_fields = expected.get("historico_anual", [])
    if annual_fields and tp.get("historico_anual"):
        latest = tp["historico_anual"][-1] if tp["historico_anual"] else {}
        present = sum(1 for f in annual_fields if latest.get(f) is not None)
        total_expected += len(annual_fields)
        total_present += present
        details["historico_anual"] = f"{present}/{len(annual_fields)}"

    # Check quarterly fields
    quarterly_fields = expected.get("historico_trimestral", [])
    if quarterly_fields and tp.get("historico_trimestral"):
        latest_q = tp["historico_trimestral"][-1] if tp["historico_trimestral"] else {}
        present_q = sum(1 for f in quarterly_fields if latest_q.get(f) is not None)
        total_expected += len(quarterly_fields)
        total_present += present_q
        details["historico_trimestral"] = f"{present_q}/{len(quarterly_fields)}"

    # Check balance sheet fields
    bs_fields = expected.get("balance_sheet_ultimo", [])
    if bs_fields:
        bs = tp.get("balance_sheet_ultimo", {})
        present_bs = sum(1 for f in bs_fields if bs.get(f) is not None)
        total_expected += len(bs_fields)
        total_present += present_bs
        details["balance_sheet_ultimo"] = f"{present_bs}/{len(bs_fields)}"

    pct = (total_present / total_expected * 100) if total_expected > 0 else 0

    return {
        "primary_doc_type": primary_type,
        "pct": round(pct, 1),
        "present": total_present,
        "expected": total_expected,
        "details": details,
    }


def _reconcile_cross_filing(tp: dict) -> list[dict]:
    """V6.2 1B.4: Cross-filing reconciliation.

    Uses _merge_conflicts stored by the merger to detect material discrepancies.
    Classification (V6.1 rule):
      - concordancia: diff_pct < 1%
      - potential_restatement: diff_pct > 5% AND diff_abs > threshold
      - extraction_discrepancy: everything else (one condition but not both)
    """
    reconciliation_log: list[dict] = []

    # Materiality threshold based on total_assets (V6.1 rule)
    # Fallback: assume conservative proxy of 1B when total_assets unavailable
    _FALLBACK_TOTAL_ASSETS = 1_000_000_000
    bs = tp.get("balance_sheet_ultimo", {})
    total_assets = _num(bs.get("activos_totales_usd"))
    base_assets = total_assets if (total_assets is not None and total_assets > 0) else _FALLBACK_TOTAL_ASSETS
    threshold_abs = max(5_000_000, 0.005 * base_assets)

    # Collect conflicts from all period entries
    for section_key in ("historico_anual", "historico_trimestral"):
        for entry in tp.get(section_key, []):
            periodo = entry.get("periodo", "?")
            conflicts = entry.get("_merge_conflicts", [])
            for conflict in conflicts:
                campo = conflict.get("campo", "?")
                kept = _num(conflict.get("valor_kept"))
                dropped = _num(conflict.get("valor_dropped"))

                if kept is None or dropped is None:
                    # Non-numeric conflict (string fields etc.) — skip
                    continue

                # Compute discrepancy metrics
                avg = (abs(kept) + abs(dropped)) / 2
                diff_abs = abs(kept - dropped)
                diff_pct = (diff_abs / avg * 100) if avg > 0 else 0.0

                # Classify (V6.1 rule: both conditions required for restatement)
                if diff_pct < 1.0:
                    clasificacion = "concordancia"
                elif diff_pct > 5.0 and diff_abs > threshold_abs:
                    clasificacion = "potential_restatement"
                else:
                    clasificacion = "extraction_discrepancy"

                reconciliation_log.append({
                    "periodo": periodo,
                    "campo": campo,
                    "valor_kept": kept,
                    "valor_dropped": dropped,
                    "source_kept": conflict.get("source_kept"),
                    "source_dropped": conflict.get("source_dropped"),
                    "reason": conflict.get("reason"),
                    "diff_abs": round(diff_abs, 2),
                    "diff_pct": round(diff_pct, 2),
                    "clasificacion": clasificacion,
                })

    return reconciliation_log


def _calc_confidence(gates: list[dict]) -> float:
    """100 - 15*FAIL - 5*WARN - 10*SKIP."""
    score = 100.0
    for g in gates:
        if g["status"] == "FAIL":
            score -= 15
        elif g["status"] == "WARNING":
            score -= 5
        elif g["status"] == "SKIP":
            score -= 10
    return max(0, min(100, round(score, 1)))


def _overall_status(gates: list[dict]) -> str:
    """PASS / PARTIAL / FAIL."""
    has_critical_fail = any(g["status"] == "FAIL" and g.get("critical") for g in gates)
    has_critical_skip = any(g["status"] == "SKIP" and g.get("critical") for g in gates)
    has_any_fail = any(g["status"] == "FAIL" for g in gates)
    has_warning = any(g["status"] == "WARNING" for g in gates)

    if has_critical_fail or has_critical_skip:
        return "FAIL"
    if has_any_fail or has_warning:
        return "PARTIAL"
    return "PASS"


def _find_critical_missing(tp: dict) -> list[dict]:
    """Find critically missing data fields."""
    missing = []
    metricas = tp.get("metricas_derivadas", {})

    if metricas.get("ev_usd") is None:
        missing.append({"item": "enterprise_value", "impacto": "Cannot calculate EV multiples", "como_conseguirlo": "Need market_cap + debt - cash"})
    if metricas.get("fcf_usd") is None:
        missing.append({"item": "free_cash_flow", "impacto": "Cannot calculate FCF metrics", "como_conseguirlo": "Need CFO and capex"})

    return missing


def _find_limitations(tp: dict) -> list[str]:
    """Find limitations in the data."""
    limitations = []
    ttm = tp.get("ttm", {})
    if ttm.get("metodo") == "FY0_fallback":
        limitations.append("TTM calculated from FY0 only (no quarterly data)")
    if ttm.get("metodo") == "no_disponible":
        limitations.append("TTM not available")

    annual = tp.get("historico_anual", [])
    if len(annual) < 3:
        limitations.append(f"Only {len(annual)} years of annual data (recommended: 5)")

    return limitations


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <tp_with_metrics.json> <output.json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    tp = json.loads(input_path.read_text())
    result = validate(tp)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[tp_validator] Output written to {output_path}")
    print(f"[tp_validator] Overall: {result['data_quality']['overall_status']} — Confidence: {result['data_quality']['confidence_score']}%")
