"""
TP_CALCULATOR: Calcula métricas derivadas sobre datos crudos del TP_EXTRACTOR.
100% determinista, 0 tokens LLM.

Fórmulas:
  N1) TTM = suma últimos 4 trimestres (o FY0 si no hay trimestrales)
  N2) FCF = CFO - capex. null si inputs null.
  N3) EV = market_cap + deuda_total - cash. null si inputs null.
  N4) WC = (AR + INV) - (AP + accruals). Cambio período a período.
  N5) Márgenes: gross, operating, net, FCF margin.
  N6) Retornos: ROIC, ROE, ROA.
  N7) Múltiplos: EV/EBIT, EV/FCF, P/FCF, FCF_yield. N/A si denom ≤ 0.
  N8) deuda_neta = deuda - cash.
  N9) Per-share: EPS, FCF/share, BV/share.
  N10) Anotación de periodo base por métrica.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone


# ── FY0 eligibility (shared between _ttm and calculate) ─────

_FY0_KEY_FIELDS = ("ingresos_usd", "ebit_usd", "net_income_usd",
                   "cfo_usd", "capex_usd", "cogs_usd")


def _is_real_numeric(v) -> bool:
    """True if v is a real number (including 0), handling dict wrappers."""
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, dict):
        inner = v.get("value", v.get("valor"))
        if isinstance(inner, bool):
            return False
        return isinstance(inner, (int, float))
    return False


def _find_eligible_fy0(annual: list[dict]) -> dict | None:
    """Find the most recent annual entry eligible as FY0.

    Requirements:
    - Not a partial period (_periodo_parcial)
    - ingresos_usd is mandatory (must be a real numeric)
    - At least 3 of 6 key fields with real numeric values
    """
    annual_full = [a for a in annual if not a.get("_periodo_parcial")]
    annual_full = sorted(annual_full, key=_parse_period_sort_key)
    for candidate in reversed(annual_full):  # most recent first
        if not _is_real_numeric(candidate.get("ingresos_usd")):
            continue
        populated = sum(1 for f in _FY0_KEY_FIELDS if _is_real_numeric(candidate.get(f)))
        if populated >= 3:
            return candidate
    return None


def calculate(partial_tp: dict, market_data: dict) -> dict:
    """
    Toma output del TP_EXTRACTOR (datos crudos) + market_data.
    Calcula todas las métricas derivadas.
    Retorna partial_tp enriquecido con sección `metricas_derivadas` y `ttm`.
    Regla: si input es null → output es null (NO imputation).
    """
    result = dict(partial_tp)  # Shallow copy

    # Extract market data
    mkt = _extract_market_data(market_data)
    market_cap = mkt.get("market_cap_usd")
    shares = mkt.get("shares_outstanding")
    price = mkt.get("price")

    # Get annual and quarterly data
    annual = result.get("historico_anual", [])
    quarterly = result.get("historico_trimestral", [])

    # N1) TTM calculation
    ttm = _ttm(annual, quarterly)
    result["ttm"] = ttm

    # Get eligible FY0 (most recent annual passing quality threshold)
    fy0 = _find_eligible_fy0(annual) or {}

    # Extract key values for derived metrics.
    # RULE: use TTM as a coherent block OR eligible FY0 as fallback. Never mix
    # fields across sources (e.g., TTM revenue with FY0 ebit) — that produces
    # fabricated cross-era metrics.  If _ttm() returned no_disponible AND no
    # eligible FY0 exists, all metric inputs stay None (fail-closed).
    ttm_method = ttm.get("metodo", "no_disponible")
    if ttm_method in ("suma_4_trimestres", "FY0_fallback") and ttm.get("ingresos_usd") is not None:
        ingresos = ttm.get("ingresos_usd")
        ebit = ttm.get("ebit_usd")
        net_income = ttm.get("net_income_usd")
        cfo = ttm.get("cfo_usd")
        capex = ttm.get("capex_usd")
    else:
        ingresos = fy0.get("ingresos_usd")
        ebit = fy0.get("ebit_usd")
        net_income = fy0.get("net_income_usd")
        cfo = fy0.get("cfo_usd")
        capex = fy0.get("capex_usd")

    # COGS/gross profit: must come from the SAME era as ingresos to avoid
    # cross-era margin calculation.  TTM doesn't carry these fields, so only
    # populate when the income source is FY0 (either direct or fallback).
    if ttm_method == "FY0_fallback" or ttm.get("ingresos_usd") is None:
        cogs = fy0.get("cogs_usd")
        if cogs is None:
            cogs = fy0.get("costo_ventas_usd")
        beneficio_bruto = fy0.get("beneficio_bruto_usd")
        if beneficio_bruto is None:
            beneficio_bruto = fy0.get("gross_profit_usd")
    else:
        # TTM sum of quarters — use TTM values if available, else None
        cogs = ttm.get("cogs_usd")
        beneficio_bruto = ttm.get("beneficio_bruto_usd")
        if beneficio_bruto is None:
            beneficio_bruto = ttm.get("gross_profit_usd")

    # Balance sheet items
    bs = result.get("balance_sheet_ultimo", {})
    total_assets = _bs_val(bs, "total_assets", "activos_totales_usd", "total_assets_usd")
    total_liabilities = _bs_val(bs, "total_liabilities", "pasivos_totales_usd", "total_liabilities_usd")
    equity = _bs_val(bs, "total_stockholders_equity", "total_shareholders_equity",
                     "patrimonio_usd", "equity_usd")
    debt = _bs_val(bs, "deuda_total_usd", "total_debt")
    if debt is None:
        debt = fy0.get("deuda_total_usd")
    cash = _bs_val(bs, "cash_and_cash_equivalents", "caja_usd", "cash_usd")
    if cash is None:
        cash = fy0.get("caja_usd")

    # N2) FCF
    fcf = _fcf(cfo, capex)

    # N3) EV
    ev = _ev(market_cap, debt, cash)

    # N4) Working capital change
    wc = _working_capital(result)

    # N5) Margins
    margins = _margins(ingresos, cogs, beneficio_bruto, ebit, net_income, fcf)

    # N6) Returns
    invested_capital = _safe_add(debt, equity)
    returns = _returns(ebit, 0.21, invested_capital, net_income, equity, total_assets)

    # N7) Multiples
    multiples = _multiples(ev, ebit, fcf, market_cap)

    # N8) Net debt
    deuda_neta = _safe_sub(debt, cash)

    # N9) Per-share
    per_share = _per_share(net_income, fcf, equity, shares)

    # N10) Assemble metricas_derivadas
    result["metricas_derivadas"] = {
        "margen_bruto_pct": margins.get("gross_margin"),
        "margen_operativo_pct": margins.get("operating_margin"),
        "margen_neto_pct": margins.get("net_margin"),
        "margen_fcf_pct": margins.get("fcf_margin"),
        "fcf_yield_pct": _safe_div(fcf, market_cap, multiply_100=True) if fcf and market_cap else None,
        "ev_ebit": _safe_div(ev, ebit),
        "ev_fcf": _safe_div(ev, fcf),
        "p_fcf": _safe_div(market_cap, fcf),
        "net_debt_ebitda": None,  # EBITDA not always available
        "roic_pct": returns.get("roic"),
        "roe_pct": returns.get("roe"),
        "roa_pct": returns.get("roa"),
        "deuda_neta_usd": deuda_neta,
        "eps_usd": per_share.get("eps"),
        "fcf_per_share_usd": per_share.get("fcf_per_share"),
        "bv_per_share_usd": per_share.get("bv_per_share"),
        "ev_usd": ev,
        "fcf_usd": fcf,
        "wc_change": wc,
        "variacion_acciones_yoy_pct": None,  # Requires multi-year shares data
        "periodo_base": ttm.get("metodo", "no_disponible") if ttm.get("ingresos_usd") is not None else ("FY0" if fy0 else "no_disponible"),
        "nota": f"Calculated by tp_calculator.py at {datetime.now(timezone.utc).isoformat()}. "
                f"Periodo base: {ttm.get('metodo', 'no_disponible') if ttm.get('ingresos_usd') is not None else ('FY0' if fy0 else 'no_disponible')}. "
                f"Null propagation applied.",
    }

    # Inject market data into mercado section
    result.setdefault("mercado", {})
    result["mercado"].update({
        "precio": {"valor": price, "divisa": "USD"},
        "market_cap_usd": market_cap,
        "enterprise_value_usd": ev,
        "deuda_neta_usd": deuda_neta,
        "deuda_total_usd": debt,
        "caja_y_equivalentes_usd": cash,
        "traza_calculo_ev": {
            "formula": "EV = market_cap + deuda_total - caja",
            "inputs": {
                "market_cap_usd": market_cap,
                "deuda_total_usd": debt,
                "caja_y_equivalentes_usd": cash,
            },
            "nota": "Calculated by tp_calculator.py",
        },
    })

    return result


def _extract_market_data(market_data: dict) -> dict:
    """Extract relevant fields from market data output.

    Handles multiple formats:
    - Flat: {market_cap, price, shares_outstanding}
    - Nested data key: {data: {market_cap, ...}}
    - SourcesPack format: {fuentes: [{datos: {market_cap_millones, precio_cierre, ...}}]}
    """
    result: dict = {
        "market_cap_usd": None,
        "shares_outstanding": None,
        "price": None,
    }

    # Try SourcesPack format first (fuentes[].datos)
    fuentes = market_data.get("fuentes", [])
    for fuente in fuentes:
        datos = fuente.get("datos", {})
        if not datos:
            continue
        mcap_m = datos.get("market_cap_millones")
        if mcap_m is not None and result["market_cap_usd"] is None:
            result["market_cap_usd"] = mcap_m * 1_000_000
        precio = datos.get("precio_cierre") or datos.get("precio")
        if precio is not None and result["price"] is None:
            result["price"] = precio
        shares_m = datos.get("shares_outstanding_millones")
        if shares_m is not None and result["shares_outstanding"] is None:
            result["shares_outstanding"] = shares_m * 1_000_000
        if all(v is not None for v in result.values()):
            return result

    # Fallback: flat or nested data key
    data = market_data.get("data", market_data)
    if result["market_cap_usd"] is None:
        result["market_cap_usd"] = data.get("market_cap") or data.get("market_cap_usd")
    if result["shares_outstanding"] is None:
        result["shares_outstanding"] = data.get("shares_outstanding") or data.get("shs_outstand")
    if result["price"] is None:
        result["price"] = data.get("price") or data.get("precio")

    return result


def _safe_div(numerator, denominator, multiply_100=False):
    """División segura: retorna None si alguno es None o denom <= 0."""
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    result = numerator / denominator
    if multiply_100:
        result *= 100
    return round(result, 4)


def _bs_val(bs: dict, *keys) -> float | None:
    """Extract a numeric value from balance sheet, trying multiple key names.

    Handles both raw numbers and {"valor": X} dicts from LLM extractors.
    """
    for key in keys:
        val = bs.get(key)
        if val is None:
            continue
        if isinstance(val, dict):
            val = val.get("valor")
        if isinstance(val, (int, float)):
            return val
    return None


def _safe_add(*args):
    """Sum that returns None if any arg is None."""
    if any(a is None for a in args):
        return None
    return sum(args)


def _safe_sub(a, b):
    """Subtraction that returns None if any arg is None."""
    if a is None or b is None:
        return None
    return a - b


def _parse_period_sort_key(entry: dict) -> str:
    """Return an ISO-date sort key from fecha_fin or periodo string.

    Handles:
      - fecha_fin: '2024-12-31' → '2024-12-31'
      - periodo:   'FY2024'    → '2024-12-31'
      - periodo:   'Q3-2024'   → '2024-09-30'
      - periodo:   '2024'      → '2024-12-31'
    Falls back to original periodo string for unknown formats.
    """
    fecha_fin = entry.get("fecha_fin")
    if fecha_fin and re.match(r"\d{4}-\d{2}-\d{2}", str(fecha_fin)):
        return str(fecha_fin)

    periodo = str(entry.get("periodo", ""))
    # FY2024 or just 2024
    m = re.search(r"(?:FY)?(\d{4})", periodo)
    if m:
        year = m.group(1)
        # Check for quarter prefix
        qm = re.match(r"Q([1-4])", periodo)
        if qm:
            q = int(qm.group(1))
            month = q * 3
            import calendar
            day = calendar.monthrange(int(year), month)[1]
            return f"{year}-{month:02d}-{day:02d}"
        return f"{year}-12-31"
    return periodo


def _to_number(v) -> float | None:
    """Normalize raw numbers and {'valor'/'value': n} wrappers to float."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        inner = v.get("value", v.get("valor"))
        if isinstance(inner, bool):
            return None
        if isinstance(inner, (int, float)):
            return float(inner)
    return None


def _extract_year_from_annual(entry: dict) -> int | None:
    """Extract fiscal year from annual entry."""
    fecha_fin = entry.get("fecha_fin")
    if isinstance(fecha_fin, str) and re.match(r"\d{4}-\d{2}-\d{2}", fecha_fin):
        return int(fecha_fin[:4])
    periodo = str(entry.get("periodo", ""))
    m = re.search(r"(?:FY)?(\d{4})", periodo)
    if m:
        return int(m.group(1))
    return None


def _extract_quarter_year(entry: dict) -> tuple[int | None, int | None]:
    """Extract (year, quarter_number) from quarter entry."""
    periodo = str(entry.get("periodo", "")).upper()

    # Q1-2024, Q1 2024, Q1_2024
    m = re.search(r"\bQ([1-4])[-_/ ]?(\d{4})\b", periodo)
    if m:
        return int(m.group(2)), int(m.group(1))

    # 2024-Q1, 2024Q1
    m = re.search(r"\b(\d{4})[-_/ ]?Q([1-4])\b", periodo)
    if m:
        return int(m.group(1)), int(m.group(2))

    fecha_fin = entry.get("fecha_fin")
    if isinstance(fecha_fin, str) and re.match(r"\d{4}-\d{2}-\d{2}", fecha_fin):
        year = int(fecha_fin[:4])
        month = int(fecha_fin[5:7])
        month_to_q = {3: 1, 6: 2, 9: 3, 12: 4}
        q = month_to_q.get(month)
        if q:
            return year, q
    return None, None


def _build_synthetic_q4_quarters(annual: list[dict], quarters: list[dict]) -> list[dict]:
    """Create synthetic Q4 entries as FY - (Q1+Q2+Q3) when Q4 is missing."""
    annual_by_year: dict[int, dict] = {}
    for a in annual:
        if a.get("_periodo_parcial"):
            continue
        year = _extract_year_from_annual(a)
        if year is not None:
            annual_by_year[year] = a

    quarters_by_year: dict[int, dict[int, dict]] = {}
    for q in quarters:
        if q.get("_periodo_parcial"):
            continue
        year, q_num = _extract_quarter_year(q)
        if year is None or q_num is None:
            continue
        quarters_by_year.setdefault(year, {})
        existing = quarters_by_year[year].get(q_num)
        if existing is None or _parse_period_sort_key(q) >= _parse_period_sort_key(existing):
            quarters_by_year[year][q_num] = q

    synthetic: list[dict] = []
    synth_fields = [
        "ingresos_usd",
        "ebit_usd",
        "net_income_usd",
        "cfo_usd",
        "capex_usd",
        "cogs_usd",
        "beneficio_bruto_usd",
        "gross_profit_usd",
    ]

    for year, a in annual_by_year.items():
        q_map = quarters_by_year.get(year, {})
        if 4 in q_map:
            continue
        if not all(qn in q_map for qn in (1, 2, 3)):
            continue

        q1, q2, q3 = q_map[1], q_map[2], q_map[3]
        synth_q4 = {
            "periodo": f"Q4-{year}",
            "fecha_fin": f"{year}-12-31",
            "_periodo_parcial": False,
            "_sintetico_q4": True,
            "_sintesis_fuente": f"FY{year} - (Q1+Q2+Q3)",
        }

        for field in synth_fields:
            annual_val = _to_number(a.get(field))
            q_values = [_to_number(q.get(field)) for q in (q1, q2, q3)]
            if annual_val is not None and all(v is not None for v in q_values):
                synth_q4[field] = annual_val - sum(q_values)
            else:
                synth_q4[field] = None

        # Require at least revenue so the quarter is financially meaningful.
        if synth_q4.get("ingresos_usd") is None:
            continue
        synthetic.append(synth_q4)

    if not synthetic:
        return quarters

    return sorted([*quarters, *synthetic], key=_parse_period_sort_key)


def _quarters_are_consecutive(quarters: list[dict], max_gap_days: int = 120) -> bool:
    """Validate that quarters span roughly 12 months with no large gaps."""
    if len(quarters) < 2:
        return False
    dates = []
    for q in quarters:
        key = _parse_period_sort_key(q)
        try:
            dates.append(datetime.strptime(key, "%Y-%m-%d"))
        except (ValueError, TypeError):
            return False
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        if gap > max_gap_days or gap < 30:
            return False
    # Total span should be roughly 9-15 months (4 quarters end-to-end)
    total_span = (dates[-1] - dates[0]).days
    if total_span < 240 or total_span > 460:
        return False
    return True


def _ttm(annual: list, quarters: list) -> dict:
    """Calcula TTM para items de income statement.

    Sorts chronologically by fecha_fin/periodo and validates that
    the 4 quarters used are actually consecutive.
    """
    result = {
        "periodo": "TTM",
        "fecha_fin": None,
        "ingresos_usd": None,
        "ebit_usd": None,
        "net_income_usd": None,
        "cfo_usd": None,
        "capex_usd": None,
        "fcf_usd": None,
        "metodo": "no_disponible",
        "nota": None,
    }

    # Filtrar períodos parciales (9M, H1, etc.) que contaminarían la suma TTM
    quarters_full = [q for q in quarters if not q.get("_periodo_parcial")]

    # CRITICAL FIX: sort chronologically, not alphabetically
    quarters_full = sorted(quarters_full, key=_parse_period_sort_key)
    # If Q4 is missing but FY + Q1..Q3 exist, synthesize Q4 deterministically.
    quarters_full = _build_synthetic_q4_quarters(annual, quarters_full)

    if len(quarters_full) >= 4:
        last_4 = quarters_full[-4:]

        # Validate consecutiveness — reject cross-era TTMs
        if not _quarters_are_consecutive(last_4):
            periods_str = [q.get('periodo', '?') for q in last_4]
            result["nota"] = (f"4 trimestres disponibles pero NO consecutivos: {periods_str}. "
                              f"TTM rechazado para evitar datos fabricados.")
        else:
            for field in ["ingresos_usd", "ebit_usd", "net_income_usd", "cfo_usd", "capex_usd",
                         "cogs_usd", "beneficio_bruto_usd", "gross_profit_usd"]:
                values = [_to_number(q.get(field)) for q in last_4]
                if all(v is not None for v in values):
                    result[field] = sum(values)

            # FCF from TTM CFO and capex
            if result["cfo_usd"] is not None and result["capex_usd"] is not None:
                result["fcf_usd"] = result["cfo_usd"] - abs(result["capex_usd"])

            result["metodo"] = "suma_4_trimestres"
            result["fecha_fin"] = last_4[-1].get("fecha_fin")
            labels = []
            for q in last_4:
                label = q.get("periodo", "?")
                if q.get("_sintetico_q4"):
                    label = f"{label}*"
                labels.append(label)
            if any(q.get("_sintetico_q4") for q in last_4):
                result["nota"] = f"TTM from quarters: {labels} (*Q4 sintético=FY-(Q1+Q2+Q3))"
            else:
                result["nota"] = f"TTM from quarters: {labels}"

    elif len(quarters_full) > 0:
        result["nota"] = f"Solo {len(quarters_full)} trimestres completos (necesarios 4)"

    if result["metodo"] == "no_disponible" and annual:
        fy0 = _find_eligible_fy0(annual)

        if fy0 is None:
            prev_nota = result.get("nota") or ""
            result["nota"] = (prev_nota + " Fallback a FY0 descartado: ningún año con ≥3 campos clave o sin ingresos.").strip()
            return result
        for field in ["ingresos_usd", "ebit_usd", "net_income_usd", "cfo_usd", "capex_usd",
                     "cogs_usd", "beneficio_bruto_usd", "gross_profit_usd"]:
            result[field] = fy0.get(field)

        if result["cfo_usd"] is not None and result["capex_usd"] is not None:
            result["fcf_usd"] = result["cfo_usd"] - abs(result["capex_usd"])

        result["metodo"] = "FY0_fallback"
        result["fecha_fin"] = fy0.get("fecha_fin")
        prev_nota = result.get("nota") or ""
        if "NO consecutivos" in prev_nota:
            result["nota"] = prev_nota + " Fallback a FY0."
        else:
            result["nota"] = "TTM not available, using FY0"

    return result


def _fcf(cfo, capex):
    """FCF = CFO - |capex|. null-safe."""
    if cfo is None or capex is None:
        return None
    return cfo - abs(capex)


def _ev(market_cap, debt, cash):
    """EV = market_cap + debt - cash.  Fail-closed: null if any input null."""
    if market_cap is None or debt is None or cash is None:
        return None
    return market_cap + debt - cash


def _working_capital(tp: dict) -> dict | None:
    """Calculate working capital from balance sheet."""
    bs = tp.get("balance_sheet_ultimo", {})
    ar = bs.get("cuentas_por_cobrar_usd") or bs.get("accounts_receivable_usd")
    inv = bs.get("inventarios_usd") or bs.get("inventories_usd")
    ap = bs.get("cuentas_por_pagar_usd") or bs.get("accounts_payable_usd")

    if ar is None and inv is None and ap is None:
        return None

    current_assets = (ar or 0) + (inv or 0)
    current_liabilities = ap or 0
    wc = current_assets - current_liabilities

    return {
        "accounts_receivable": ar,
        "inventories": inv,
        "accounts_payable": ap,
        "working_capital_usd": wc,
    }


def _margins(ingresos, cogs, beneficio_bruto, ebit, net_income, fcf) -> dict:
    """gross_margin, operating_margin, net_margin, fcf_margin."""
    result = {}

    if ingresos and ingresos > 0:
        if beneficio_bruto is not None:
            result["gross_margin"] = round(beneficio_bruto / ingresos * 100, 2)
        elif cogs is not None:
            result["gross_margin"] = round((ingresos - cogs) / ingresos * 100, 2)
        else:
            result["gross_margin"] = None

        result["operating_margin"] = round(ebit / ingresos * 100, 2) if ebit is not None else None
        result["net_margin"] = round(net_income / ingresos * 100, 2) if net_income is not None else None
        result["fcf_margin"] = round(fcf / ingresos * 100, 2) if fcf is not None else None
    else:
        result = {"gross_margin": None, "operating_margin": None, "net_margin": None, "fcf_margin": None}

    return result


def _returns(ebit, tax_rate, invested_capital, net_income, equity, total_assets) -> dict:
    """ROIC, ROE, ROA."""
    result = {}

    # ROIC = EBIT*(1-tax) / invested_capital
    if ebit is not None and invested_capital is not None and invested_capital > 0:
        nopat = ebit * (1 - tax_rate)
        result["roic"] = round(nopat / invested_capital * 100, 2)
    else:
        result["roic"] = None

    # ROE
    if net_income is not None and equity is not None and equity > 0:
        result["roe"] = round(net_income / equity * 100, 2)
    else:
        result["roe"] = None

    # ROA
    if net_income is not None and total_assets is not None and total_assets > 0:
        result["roa"] = round(net_income / total_assets * 100, 2)
    else:
        result["roa"] = None

    return result


def _multiples(ev, ebit, fcf, market_cap) -> dict:
    """EV/EBIT, EV/FCF, P/FCF, FCF_yield."""
    return {
        "ev_ebit": _safe_div(ev, ebit) if ebit and ebit > 0 else None,
        "ev_fcf": _safe_div(ev, fcf) if fcf and fcf > 0 else None,
        "p_fcf": _safe_div(market_cap, fcf) if fcf and fcf > 0 else None,
        "fcf_yield": _safe_div(fcf, market_cap, multiply_100=True) if fcf and market_cap and market_cap > 0 else None,
    }


def _per_share(net_income, fcf, equity, shares) -> dict:
    """EPS, FCF/share, BV/share."""
    result = {}

    if shares and shares > 0:
        result["eps"] = round(net_income / shares, 4) if net_income is not None else None
        result["fcf_per_share"] = round(fcf / shares, 4) if fcf is not None else None
        result["bv_per_share"] = round(equity / shares, 4) if equity is not None else None
    else:
        result = {"eps": None, "fcf_per_share": None, "bv_per_share": None}

    return result


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <partial_tp.json> <market_data.json> <output.json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    market_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3])

    partial = json.loads(input_path.read_text())
    market = json.loads(market_path.read_text())
    result = calculate(partial, market)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[tp_calculator] Output written to {output_path}")
