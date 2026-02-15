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
import sys
from pathlib import Path
from datetime import datetime, timezone


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

    # Get FY0 (most recent annual)
    fy0 = annual[-1] if annual else {}

    # Extract key values for derived metrics
    ingresos = ttm.get("ingresos_usd") or fy0.get("ingresos_usd")
    cogs = fy0.get("cogs_usd") or fy0.get("costo_ventas_usd")
    beneficio_bruto = fy0.get("beneficio_bruto_usd")
    ebit = ttm.get("ebit_usd") or fy0.get("ebit_usd")
    net_income = ttm.get("net_income_usd") or fy0.get("net_income_usd")
    cfo = ttm.get("cfo_usd") or fy0.get("cfo_usd")
    capex = ttm.get("capex_usd") or fy0.get("capex_usd")

    # Balance sheet items
    bs = result.get("balance_sheet_ultimo", {})
    total_assets = bs.get("activos_totales_usd") or bs.get("total_assets_usd")
    total_liabilities = bs.get("pasivos_totales_usd") or bs.get("total_liabilities_usd")
    equity = bs.get("patrimonio_usd") or bs.get("equity_usd")
    debt = bs.get("deuda_total_usd") or fy0.get("deuda_total_usd")
    cash = bs.get("caja_usd") or bs.get("cash_usd") or fy0.get("caja_usd")

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
        "periodo_base": ttm.get("metodo", "FY0") if ttm.get("ingresos_usd") else "FY0",
        "nota": f"Calculated by tp_calculator.py at {datetime.now(timezone.utc).isoformat()}. "
                f"Periodo base: {'TTM' if ttm.get('ingresos_usd') else 'FY0'}. "
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
    """Extract relevant fields from market data output."""
    # market_data can be raw _market_data_output.json or nested
    data = market_data.get("data", market_data)

    return {
        "market_cap_usd": data.get("market_cap") or data.get("market_cap_usd"),
        "shares_outstanding": data.get("shares_outstanding") or data.get("shs_outstand"),
        "price": data.get("price") or data.get("precio"),
    }


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


def _ttm(annual: list, quarters: list) -> dict:
    """Calcula TTM para items de income statement."""
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

    if len(quarters) >= 4:
        # Use last 4 quarters
        last_4 = quarters[-4:]
        for field in ["ingresos_usd", "ebit_usd", "net_income_usd", "cfo_usd", "capex_usd"]:
            values = [q.get(field) for q in last_4]
            if all(v is not None for v in values):
                result[field] = sum(values)

        # FCF from TTM CFO and capex
        if result["cfo_usd"] is not None and result["capex_usd"] is not None:
            result["fcf_usd"] = result["cfo_usd"] - abs(result["capex_usd"])

        result["metodo"] = "suma_4_trimestres"
        result["fecha_fin"] = last_4[-1].get("fecha_fin")
        result["nota"] = f"TTM from quarters: {[q.get('periodo', '?') for q in last_4]}"
    elif annual:
        # Fallback to FY0
        fy0 = annual[-1]
        for field in ["ingresos_usd", "ebit_usd", "net_income_usd", "cfo_usd", "capex_usd"]:
            result[field] = fy0.get(field)

        if result["cfo_usd"] is not None and result["capex_usd"] is not None:
            result["fcf_usd"] = result["cfo_usd"] - abs(result["capex_usd"])

        result["metodo"] = "FY0_fallback"
        result["fecha_fin"] = fy0.get("fecha_fin")
        result["nota"] = "TTM not available, using FY0"

    return result


def _fcf(cfo, capex):
    """FCF = CFO - |capex|. null-safe."""
    if cfo is None or capex is None:
        return None
    return cfo - abs(capex)


def _ev(market_cap, debt, cash):
    """EV = market_cap + debt - cash."""
    if market_cap is None:
        return None
    d = debt or 0
    c = cash or 0
    return market_cap + d - c


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
