"""
TP_NORMALIZER: Normaliza campos heterogéneos de LLM extractors a formato canónico.
100% determinista, 0 tokens LLM.

Problema: Los LLM extractors producen 15+ variantes de nombre de campo,
11 formatos de wrapper de valor, y 6 patrones de anidación.
tp_calculator espera nombres canónicos con valores numéricos raw.

Solución:
  1. Mapas de alias: N variantes → 1 nombre canónico
  2. Unwrap de valores: {"value": X} / {"valor": X} → X
  3. Flatten de nesting: metricas.X / estado_resultados.X → top-level
  4. Clasificación de períodos: FY/Q → primarios, 9M/H1 → parciales, rest → log
  5. Single-metric entries → log auxiliar (trazabilidad)
  6. Sanity checks: signo CAPEX, revenue > 0, gross_profit ≤ revenue, YoY >10x
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

# ── Mapas de alias (variante → canónico) ────────────────────

# Cada clave canónica mapea a un set de alias conocidos (lowercase).
# tp_calculator espera estos campos canónicos en historico_anual/trimestral.
FIELD_ALIASES: dict[str, set[str]] = {
    "ingresos_usd": {
        "revenues", "revenue", "revenue_usd", "revenue_total",
        "ingresos_totales", "consolidated_revenue", "ingresos",
        "total_revenue", "net_revenue", "net_revenues",
    },
    "cogs_usd": {
        "cost_of_revenues", "cost_of_revenue", "cogs",
        "costo_ventas_usd", "cost_of_goods_sold",
    },
    "gross_profit_usd": {
        "gross_profit", "gross_profit_usd", "beneficio_bruto",
        "beneficio_bruto_usd", "utilidad_bruta",
    },
    "ebit_usd": {
        "operating_income", "operating_income_usd", "operating_profit",
        "resultado_operativo", "ingreso_operativo", "beneficio_operativo",
        "income_from_operations",
    },
    "net_income_usd": {
        "net_income", "net_income_usd", "ingreso_neto",
        "ingreso_neto_consolidado", "ingreso_neto_atribuible_a_travelzoo",
        "net_income_attributable_to_travelzoo",
        "net_income_attributable_to_controlling_interest",
        "net_income_attributable_to_company",
        "utilidad_neta",
    },
    "cfo_usd": {
        "cfo_usd", "net_cash_from_operating_activities",
        "cash_from_operations", "operating_cash_flow",
        "flujo_caja_operativo", "cfo",
    },
    "cfi_usd": {
        "cfi_usd", "cfi", "cash_from_investing",
        "net_cash_from_investing_activities",
        "net_cash_used_in_investing_activities",
        "investing_activities", "flujo_caja_inversion",
        "cash_used_in_investing_activities",
    },
    "cff_usd": {
        "cff_usd", "cff", "cash_from_financing",
        "net_cash_from_financing_activities",
        "net_cash_used_in_financing_activities",
        "financing_activities", "flujo_caja_financiacion",
        "cash_used_in_financing_activities",
    },
    "delta_cash_usd": {
        "delta_cash_usd", "delta_cash", "cambio_caja_usd",
        "net_change_in_cash", "net_increase_in_cash",
        "net_increase_decrease_in_cash",
        "net_change_in_cash_and_cash_equivalents",
        "variacion_neta_efectivo", "variacion_neta_caja",
        "cambio_neto_caja", "cambio_neto_efectivo",
        "net_increase_decrease_in_cash_and_cash_equivalents",
    },
    "fx_effect_cash_usd": {
        "fx_effect_cash_usd", "fx_effect_cash",
        "effect_of_exchange_rates_on_cash",
        "effect_of_exchange_rate_changes_on_cash",
        "exchange_rate_effect_on_cash",
        "forex_effect_on_cash",
        "efecto_tipo_cambio_caja_usd", "efecto_tipo_cambio_caja",
        "efecto_cambiario_caja",
        "variacion_por_tipo_de_cambio_en_caja",
    },
    "otros_ajustes_caja_usd": {
        "otros_ajustes_caja_usd", "otros_ajustes_en_caja",
        "other_cash_adjustments_usd", "other_cash_adjustments",
        "other_reconciling_cash_items_usd",
        "ajustes_otros_cambios_efectivo",
    },
    "capex_usd": {
        "capex_usd", "capex", "capital_expenditures",
        "purchases_of_property_and_equipment",
        "gastos_capital",
    },
    "rd_usd": {
        "research_and_development", "r_and_d", "rd_usd",
        "product_development", "investigacion_y_desarrollo",
    },
    "sga_usd": {
        "sales_and_marketing", "sga_usd", "selling_general_administrative",
        "gastos_venta_admin",
    },
    "ga_usd": {
        "general_and_administrative", "g_and_a", "ga_usd",
        "gastos_generales_admin",
    },
    "interest_expense_usd": {
        "interest_expense", "interest_expense_usd",
        "gasto_intereses", "gastos_financieros",
    },
    "depreciation_usd": {
        "depreciation_and_amortization", "depreciation_usd",
        "depreciacion_amortizacion", "d_and_a", "da_usd",
    },
    "income_tax_usd": {
        "income_tax", "income_tax_expense", "income_tax_usd",
        "impuesto_renta", "tax_expense",
    },
}

# Índice invertido: alias (lowercase) → campo canónico
_ALIAS_INDEX: dict[str, str] = {}
for canonical, aliases in FIELD_ALIASES.items():
    for alias in aliases:
        _ALIAS_INDEX[alias.lower()] = canonical
    # También el propio canónico
    _ALIAS_INDEX[canonical.lower()] = canonical

# Campos canónicos para balance sheet (tp_calculator los busca con _bs_val)
BS_FIELD_ALIASES: dict[str, set[str]] = {
    "activos_totales_usd": {
        "total_assets", "total_assets_usd", "activos_totales",
    },
    "pasivos_totales_usd": {
        "total_liabilities", "total_liabilities_usd", "pasivos_totales",
    },
    "patrimonio_usd": {
        "total_stockholders_equity", "total_shareholders_equity",
        "equity_usd", "equity", "patrimonio", "patrimonio_neto",
    },
    "deuda_total_usd": {
        "total_debt", "deuda_total", "long_term_debt",
        "deuda_largo_plazo",
    },
    "caja_usd": {
        "cash_and_cash_equivalents", "cash_usd", "cash",
        "efectivo_equivalentes", "caja_y_equivalentes",
    },
    "cuentas_por_cobrar_usd": {
        "accounts_receivable_usd", "accounts_receivable",
        "cuentas_por_cobrar", "trade_receivables",
    },
    "inventarios_usd": {
        "inventories_usd", "inventories", "inventarios",
    },
    "cuentas_por_pagar_usd": {
        "accounts_payable_usd", "accounts_payable",
        "cuentas_por_pagar",
    },
}

_BS_ALIAS_INDEX: dict[str, str] = {}
for canonical, aliases in BS_FIELD_ALIASES.items():
    for alias in aliases:
        _BS_ALIAS_INDEX[alias.lower()] = canonical
    _BS_ALIAS_INDEX[canonical.lower()] = canonical


# ── Claves "ruido" que no son datos financieros ────────────
# Se ignoran durante el mapeo de alias (no son métricas del P&L/CF/BS)
_NOISE_KEYS = {
    "periodo", "fecha", "fecha_fin", "fecha_inicio", "fecha_corte",
    "fuente_refs", "source_filing", "filing_type", "tipo_periodo",
    "is_preliminary", "duracion", "concepto", "metrica", "metric",
    "valor", "moneda", "unidad", "escala", "scale", "currency", "unit",
    "entidad", "valores", "periodo_inicio", "periodo_fin",
    "resultado_integral", "flujo_caja_operativo_parcial",
    "tipo", "value",  # top-level "value" in single-metric entries
}

# ── Sub-claves de nesting que se deben aplanar ────────────
_NESTING_KEYS = {"metricas", "datos", "estado_resultados", "metrics",
                 "income_statement", "line_items"}


# ── Clasificación de períodos ──────────────────────────────

_RE_FY = re.compile(r"^FY\d{4}$")
_RE_Q = re.compile(r"^Q[1-4]-\d{4}$")
_RE_PARTIAL = re.compile(r"^(9M|H1|H2|6M|FY\d{4}_YTD_\d+M)-?\d{0,4}$", re.IGNORECASE)
_RE_GUIDANCE = re.compile(r"guidance|estimate|\d{4}E$", re.IGNORECASE)


def _derive_fy_period(date_str: str) -> str:
    """Derive FY period from an ISO date string like '2024-12-31' → 'FY2024'."""
    try:
        parts = date_str.strip().split("-")
        return f"FY{parts[0]}"
    except Exception:
        return ""


def _derive_q_period(date_str: str) -> str:
    """Derive quarter period from an ISO date string like '2024-06-30' → 'Q2-2024'."""
    try:
        parts = date_str.strip().split("-")
        year = parts[0]
        month = int(parts[1])
        q = (month - 1) // 3 + 1
        return f"Q{q}-{year}"
    except Exception:
        return ""


def _classify_period(periodo: str | None) -> str:
    """Clasifica un período en: 'primary', 'partial', 'rejected'."""
    if not periodo or not isinstance(periodo, str):
        return "rejected"
    p = periodo.strip()
    if _RE_FY.match(p) or _RE_Q.match(p):
        return "primary"
    if _RE_PARTIAL.match(p):
        return "partial"
    if p == "UNKNOWN" or _RE_GUIDANCE.search(p):
        return "rejected"
    # Date-based (YYYY-MM-DD), AS_OF_*, etc.
    if re.match(r"^\d{4}-\d{2}-\d{2}$", p) or p.startswith("AS_OF_"):
        return "rejected"
    # Anything with parentheses like "FY2026 (guidance, next year)"
    if "(" in p:
        return "rejected"
    return "primary"  # Default: keep unknown formats as primary


# ── Unwrapping de valores ──────────────────────────────────

def _unwrap_value(val: Any) -> float | None:
    """Extrae número raw de cualquier formato wrapper.

    Formatos soportados:
      - Raw number: 12345 → 12345
      - {"value": X, ...}: → X
      - {"valor": X, ...}: → X
      - {"min": ..., "max": ...}: → None (range/guidance, no es dato puntual)
      - None → None
      - bool → None
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, dict):
        # Range/guidance — no es un valor puntual
        if "min" in val and "max" in val and "value" not in val and "valor" not in val:
            return None
        # Try "value" first, then "valor"
        for key in ("value", "valor"):
            inner = val.get(key)
            if inner is None:
                continue
            if isinstance(inner, bool):
                continue
            if isinstance(inner, (int, float)):
                return inner
            if isinstance(inner, dict):
                # Nested dict — try recursion one level
                return _unwrap_value(inner)
        return None
    return None


# ── Detección de single-metric entries ─────────────────────

def _is_single_metric_entry(entry: dict) -> bool:
    """Detecta entradas tipo single-metric: {"periodo":"FY2021","metric":"X","valor":Y}.

    Heurística: tiene 'concepto'/'metrica'/'metric' a nivel raíz Y
    NO tiene campos que matcheen alias de P&L (revenues, operating_income, etc.)
    como claves separadas (no confundir con el campo plano 'valor' de la single-metric).
    """
    has_single_marker = any(
        entry.get(k) is not None
        for k in ("concepto", "metrica", "metric")
    )
    if not has_single_marker:
        return False

    # Check if entry also has recognized financial fields as separate keys
    for key in entry:
        k_lower = key.lower()
        if k_lower in _ALIAS_INDEX and k_lower not in _NOISE_KEYS:
            return False

    return True


# ── Flatten de nesting ─────────────────────────────────────

def _flatten_entry(entry: dict) -> dict:
    """Promueve campos anidados en metricas/datos/estado_resultados a nivel raíz.

    Ejemplo: {"estado_resultados": {"revenue": {"valor": X}}}
           → {"revenue": {"valor": X}}
    """
    flat = {}
    for key, val in entry.items():
        if key.lower() in _NESTING_KEYS and isinstance(val, dict):
            # Promote nested fields, don't overwrite existing
            for sub_key, sub_val in val.items():
                if sub_key not in flat:
                    flat[sub_key] = sub_val
        else:
            flat[key] = val
    return flat


# ── Normalización de una entrada de período ────────────────

def _normalize_entry(entry: dict, alias_index: dict[str, str]) -> dict:
    """Normaliza una entrada de período:
    1. Flatten nesting
    2. Resolve aliases → canonical names
    3. Unwrap values
    """
    # Step 1: Flatten
    flat = _flatten_entry(entry)

    # Step 2+3: Alias resolution + unwrap
    normalized: dict[str, Any] = {}
    for key, val in flat.items():
        k_lower = key.lower()

        # Preserve metadata keys as-is
        if k_lower in ("periodo", "fecha", "fecha_fin", "fecha_inicio",
                        "fecha_corte", "fuente_refs", "source_filing",
                        "filing_type", "is_preliminary", "tipo_periodo",
                        "duracion", "periodo_inicio", "periodo_fin",
                        "_periodo_parcial"):
            normalized[key] = val
            continue

        # Skip noise keys (single-metric markers already handled separately)
        if k_lower in _NOISE_KEYS:
            continue

        # Try alias resolution
        canonical = alias_index.get(k_lower)
        if canonical:
            unwrapped = _unwrap_value(val)
            # Only set if not already set, or if new value is not None
            if canonical not in normalized or (normalized[canonical] is None and unwrapped is not None):
                normalized[canonical] = unwrapped
        # Else: unrecognized field — skip (don't litter output with noise)

    return normalized


# ── Sanity checks ──────────────────────────────────────────

def _sanity_check_entry(entry: dict, periodo: str) -> list[str]:
    """Ejecuta sanity checks sobre una entrada normalizada.
    Retorna lista de warnings (vacía si OK)."""
    warnings = []

    capex = entry.get("capex_usd")
    if capex is not None and capex > 0:
        warnings.append(f"{periodo}: CAPEX positivo ({capex}), se invierte signo")
        entry["capex_usd"] = -capex

    revenue = entry.get("ingresos_usd")
    if revenue is not None and revenue < 0:
        warnings.append(f"{periodo}: Revenue negativo ({revenue})")

    gp = entry.get("gross_profit_usd")
    if revenue is not None and gp is not None and revenue > 0 and gp > revenue:
        warnings.append(f"{periodo}: gross_profit ({gp}) > revenue ({revenue})")

    return warnings


def _sanity_check_yoy(entries: list[dict]) -> list[str]:
    """Detecta saltos >10x YoY en métricas clave."""
    warnings = []
    for i in range(1, len(entries)):
        prev = entries[i - 1]
        curr = entries[i]
        for field in ("ingresos_usd", "ebit_usd", "net_income_usd"):
            p_val = prev.get(field)
            c_val = curr.get(field)
            if (isinstance(p_val, (int, float)) and isinstance(c_val, (int, float))
                    and p_val != 0):
                ratio = abs(c_val / p_val)
                if ratio > 10:
                    warnings.append(
                        f"{field}: {prev.get('periodo')}→{curr.get('periodo')} "
                        f"ratio={ratio:.1f}x (>10x)"
                    )
    return warnings


# ── Punto de entrada principal ─────────────────────────────

def normalize(tp: dict) -> dict:
    """Normaliza un TruthPack completo (post-merger o single-partial).

    Procesa:
      - historico_anual: alias + unwrap + period classification
      - historico_trimestral: alias + unwrap + period classification
      - balance_sheet_ultimo: alias + unwrap (BS-specific aliases)

    Añade sección `_normalized_log` con trazabilidad.
    """
    result = deepcopy(tp)
    log: dict[str, Any] = {
        "single_metric_entries": [],
        "rejected_periods": [],
        "sanity_warnings": [],
        "fields_mapped": 0,
        "entries_processed": 0,
    }

    # ── Normalizar historico_anual ──
    raw_annual = result.get("historico_anual", [])
    norm_annual = []
    for entry in raw_annual:
        periodo = entry.get("periodo", "")
        # Derive periodo from period_end when missing
        if not periodo and entry.get("period_end"):
            periodo = _derive_fy_period(entry["period_end"])
            entry["periodo"] = periodo
            entry.setdefault("fecha_fin", entry["period_end"])
        classification = _classify_period(periodo)

        if _is_single_metric_entry(entry):
            log["single_metric_entries"].append({
                "periodo": periodo,
                "concepto": entry.get("concepto") or entry.get("metrica") or entry.get("metric"),
                "valor": _unwrap_value(entry.get("valor")) or _unwrap_value(entry.get("value")),
                "source": entry.get("source_filing"),
            })
            continue

        if classification == "rejected":
            log["rejected_periods"].append({
                "periodo": periodo,
                "seccion": "historico_anual",
                "razon": "formato de periodo no válido para datos anuales",
            })
            continue

        normalized = _normalize_entry(entry, _ALIAS_INDEX)
        normalized["periodo"] = periodo

        if classification == "partial":
            normalized["_periodo_parcial"] = True

        # Sanity checks
        sw = _sanity_check_entry(normalized, periodo)
        log["sanity_warnings"].extend(sw)

        # Only keep if has at least one financial field with data
        has_data = any(
            normalized.get(k) is not None
            for k in ("ingresos_usd", "ebit_usd", "net_income_usd", "cfo_usd",
                       "gross_profit_usd", "cogs_usd", "cfi_usd", "cff_usd")
        )
        if has_data:
            norm_annual.append(normalized)
            log["entries_processed"] += 1
        else:
            log["rejected_periods"].append({
                "periodo": periodo,
                "seccion": "historico_anual",
                "razon": "sin datos financieros tras normalización",
            })

    # YoY sanity check
    log["sanity_warnings"].extend(_sanity_check_yoy(norm_annual))
    result["historico_anual"] = norm_annual

    # ── Normalizar historico_trimestral ──
    raw_quarterly = result.get("historico_trimestral", [])
    norm_quarterly = []
    for entry in raw_quarterly:
        periodo = entry.get("periodo", "")
        # Derive periodo from period_end when missing
        if not periodo and entry.get("period_end"):
            periodo = _derive_q_period(entry["period_end"])
            entry["periodo"] = periodo
            entry.setdefault("fecha_fin", entry["period_end"])
        classification = _classify_period(periodo)

        if _is_single_metric_entry(entry):
            log["single_metric_entries"].append({
                "periodo": periodo,
                "concepto": entry.get("concepto") or entry.get("metrica") or entry.get("metric"),
                "valor": _unwrap_value(entry.get("valor")) or _unwrap_value(entry.get("value")),
                "source": entry.get("source_filing"),
            })
            continue

        if classification == "rejected":
            log["rejected_periods"].append({
                "periodo": periodo,
                "seccion": "historico_trimestral",
                "razon": "formato de periodo no válido",
            })
            continue

        normalized = _normalize_entry(entry, _ALIAS_INDEX)
        normalized["periodo"] = periodo

        if classification == "partial":
            normalized["_periodo_parcial"] = True

        # Preserve fecha_fin/fecha_inicio if present
        for meta_key in ("fecha_fin", "fecha_inicio", "tipo_periodo", "duracion"):
            if meta_key in entry and meta_key not in normalized:
                normalized[meta_key] = entry[meta_key]

        sw = _sanity_check_entry(normalized, periodo)
        log["sanity_warnings"].extend(sw)

        has_data = any(
            normalized.get(k) is not None
            for k in ("ingresos_usd", "ebit_usd", "net_income_usd", "cfo_usd",
                       "gross_profit_usd", "cogs_usd", "cfi_usd", "cff_usd")
        )
        if has_data:
            norm_quarterly.append(normalized)
            log["entries_processed"] += 1
        else:
            log["rejected_periods"].append({
                "periodo": periodo,
                "seccion": "historico_trimestral",
                "razon": "sin datos financieros tras normalización",
            })

    log["sanity_warnings"].extend(_sanity_check_yoy(norm_quarterly))
    result["historico_trimestral"] = norm_quarterly

    # ── Normalizar balance_sheet_ultimo ──
    raw_bs = result.get("balance_sheet_ultimo", {})
    if isinstance(raw_bs, list):
        # LLM may return multiple balance sheet snapshots.
        # Prefer latest by ISO date; if no date is available, prefer entry with
        # more non-null canonical BS fields.
        candidates: list[tuple[int, dict]] = []
        for idx, entry in enumerate(raw_bs):
            if isinstance(entry, dict):
                candidates.append((idx, _normalize_entry(entry, _BS_ALIAS_INDEX)))

        if not candidates:
            result["balance_sheet_ultimo"] = {}
        else:
            bs_fields = (
                "activos_totales_usd",
                "pasivos_totales_usd",
                "patrimonio_usd",
                "deuda_total_usd",
                "caja_usd",
                "cuentas_por_cobrar_usd",
                "inventarios_usd",
                "cuentas_por_pagar_usd",
            )

            def _date_key(bs_entry: dict) -> str:
                for key in ("fecha", "fecha_fin", "fecha_corte"):
                    raw_date = bs_entry.get(key)
                    if isinstance(raw_date, str):
                        iso = raw_date.strip()[:10]
                        if re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
                            return iso
                return ""

            def _completeness_key(bs_entry: dict) -> int:
                return sum(1 for key in bs_fields if bs_entry.get(key) is not None)

            dated_candidates: list[tuple[int, dict, str, int]] = []
            undated_candidates: list[tuple[int, dict, int]] = []
            for idx, bs_entry in candidates:
                dkey = _date_key(bs_entry)
                ckey = _completeness_key(bs_entry)
                if dkey:
                    dated_candidates.append((idx, bs_entry, dkey, ckey))
                else:
                    undated_candidates.append((idx, bs_entry, ckey))

            if dated_candidates:
                # date asc + completeness asc + idx asc => max picks latest and deterministic tie-break.
                _, best_entry, _, _ = max(dated_candidates, key=lambda t: (t[2], t[3], t[0]))
            else:
                # No valid date in any snapshot: prefer richer snapshot, then most recent list position.
                _, best_entry, _ = max(undated_candidates, key=lambda t: (t[2], t[0]))
            result["balance_sheet_ultimo"] = best_entry
    elif isinstance(raw_bs, dict) and raw_bs:
        norm_bs = _normalize_entry(raw_bs, _BS_ALIAS_INDEX)
        result["balance_sheet_ultimo"] = norm_bs

    # Count mapped fields
    for section in (norm_annual, norm_quarterly):
        for entry in section:
            log["fields_mapped"] += sum(
                1 for k in entry
                if k in _ALIAS_INDEX.values() or k in _BS_ALIAS_INDEX.values()
            )

    result["_normalized_log"] = log
    return result
