#!/usr/bin/env python3
"""Market data snapshot fetcher for ELSIAN INVEST pipeline.

Retrieves price, market cap, volume, 52-week range and key ratios from
Finviz (US equities) and Stooq (OHLCV history).  Produces SourcesPack_v1 JSON.

Usage:
    python3 scripts/runners/market_data_v1_runner.py --ticker CRTO --case-dir casos/CRTO/2026-02-14

Política de faltantes: ver _operativa/POLITICA_FALTANTES.md
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "ELSIAN-INVEST-Bot/1.0 (research; bot@elsian-invest.local)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
TIMEOUT = 45

# Stooq exchange suffixes (lower-case)
STOOQ_SUFFIX: Dict[str, str] = {
    "NYSE": ".us", "NASDAQ": ".us", "AMEX": ".us", "US": ".us",
    "SEHK": ".hk", "HKEX": ".hk",
    "LSE": ".uk", "AIM": ".uk",
    "EPA": ".fr",
    "XETRA": ".de", "FRA": ".de",
    "TSE": ".jp",
    "ASX": ".au",
    "TSX": ".ca",
}

# Yahoo Finance ticker suffixes
YAHOO_SUFFIX: Dict[str, str] = {
    "NYSE": "", "NASDAQ": "", "AMEX": "", "US": "",
    "SEHK": ".HK", "HKEX": ".HK",
    "LSE": ".L", "AIM": ".L",
    "EPA": ".PA",
    "XETRA": ".DE", "FRA": ".DE",
    "TSE": ".T",
    "ASX": ".AX",
    "TSX": ".TO",
}

US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "US", ""}


def _get_with_retry(url: str) -> requests.Response:
    """GET with 1 retry on 429/5xx or connection errors (3s backoff)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as exc:
        status = getattr(getattr(exc, "response", None), "status_code", 0)
        if status in (429, 500, 502, 503, 504) or isinstance(exc, requests.exceptions.ConnectionError):
            time.sleep(3)
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            return resp
        raise


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return dt.date.today().isoformat()


def to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    s = value.strip()
    if not s or s.upper() in {"N/A", "-"}:
        return None
    s = s.replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    m = re.match(r"^([-+]?[0-9]*\.?[0-9]+)\s*([KMBT])$", s, re.IGNORECASE)
    if m:
        num = float(m.group(1))
        unit = m.group(2).upper()
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[unit]
        return num * mult
    try:
        return float(s)
    except ValueError:
        return None


def parse_snapshot_table(soup: BeautifulSoup) -> Dict[str, str]:
    table = soup.find("table", class_="snapshot-table2")
    if not table:
        return {}
    cells = [td.get_text(" ", strip=True) for td in table.find_all("td")]
    values: Dict[str, str] = {}
    for i in range(0, len(cells) - 1, 2):
        key = cells[i]
        val = cells[i + 1]
        if key:
            values[key] = val
    return values


def parse_quote_links(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    box = soup.select_one(".quote-links")
    if not box:
        return None, None, None, None
    text = box.get_text(" ", strip=True)
    parts = [p.strip() for p in text.split("•")]
    clean = [p for p in parts if p and p.lower() not in {"chart", "stock detail"}]
    if len(clean) >= 4:
        return clean[0], clean[1], clean[2], clean[3]
    return None, None, None, None


def fetch_finviz_context(ticker: str) -> Dict[str, Any]:
    url = f"https://finviz.com/quote.ashx?t={quote_plus(ticker)}&p=d"
    resp = _get_with_retry(url)
    resp.encoding = resp.encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    company_node = soup.select_one(".quote-header_left h2")
    company_name = company_node.get_text(" ", strip=True) if company_node else ticker

    sector, industry, country, exchange = parse_quote_links(soup)
    snap = parse_snapshot_table(soup)

    return {
        "url": url,
        "company_name": company_name,
        "sector": sector,
        "industry": industry,
        "country": country,
        "exchange": exchange,
        "snapshot": snap,
    }


def fetch_stooq_ohlcv(ticker: str, exchange: str = "US") -> List[Dict[str, str]]:
    """Fetch daily OHLCV from Stooq.  Uses exchange-specific suffix."""
    suffix = STOOQ_SUFFIX.get(exchange.upper(), ".us")
    sym = f"{ticker.lower()}{suffix}"
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    try:
        resp = _get_with_retry(url)
    except requests.exceptions.HTTPError:
        return []
    text = resp.text.strip()
    if not text or "No data" in text:
        return []
    rows = list(csv.DictReader(io.StringIO(text)))
    return [r for r in rows if r.get("Date") and r.get("Close")]


def fetch_yahoo_snapshot(ticker: str, exchange: str) -> Dict[str, Any]:
    """Fetch basic quote data from Yahoo Finance (non-US fallback)."""
    suffix = YAHOO_SUFFIX.get(exchange.upper(), "")
    sym = f"{ticker}{suffix}"
    chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(sym)}?range=5d&interval=1d"
    try:
        resp = _get_with_retry(chart_url)
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return {"url": f"https://finance.yahoo.com/quote/{quote_plus(sym)}", "company_name": ticker,
                    "sector": None, "industry": None, "country": None, "exchange": exchange, "snapshot": {}}
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        prev = meta.get("previousClose") or meta.get("chartPreviousClose")
        volume = meta.get("regularMarketVolume")
        snap: Dict[str, str] = {}
        if price is not None:
            snap["Price"] = str(price)
        if prev is not None:
            snap["Prev Close"] = str(prev)
        if volume is not None:
            snap["Volume"] = str(int(volume))
        currency = meta.get("currency", "USD")
        return {
            "url": f"https://finance.yahoo.com/quote/{quote_plus(sym)}",
            "company_name": meta.get("shortName") or meta.get("longName") or ticker,
            "sector": None,
            "industry": None,
            "country": None,
            "exchange": meta.get("exchangeName") or exchange,
            "snapshot": snap,
            "currency": currency,
        }
    except Exception:
        return {"url": f"https://finance.yahoo.com/quote/{quote_plus(sym)}", "company_name": ticker,
                "sector": None, "industry": None, "country": None, "exchange": exchange, "snapshot": {}}


def rolling_avg_volume(rows: List[Dict[str, str]], n: int) -> Optional[float]:
    if not rows:
        return None
    tail = rows[-n:] if len(rows) >= n else rows
    vols: List[float] = []
    for r in tail:
        try:
            vols.append(float(r["Volume"]))
        except Exception:
            continue
    if not vols:
        return None
    return sum(vols) / len(vols)


def max_min_52w(rows: List[Dict[str, str]]) -> Tuple[Optional[float], Optional[float]]:
    if not rows:
        return None, None
    tail = rows[-252:] if len(rows) >= 252 else rows
    closes: List[float] = []
    for r in tail:
        try:
            closes.append(float(r["Close"]))
        except Exception:
            continue
    if not closes:
        return None, None
    return max(closes), min(closes)


def main() -> int:
    parser = argparse.ArgumentParser(description="MARKET_DATA_V1 runner")
    parser.add_argument("--ticker", required=True, help="Ticker, e.g., BBW or 0327")
    parser.add_argument("--case-dir", required=True, help="Case directory, e.g., casos/BBW/2026-02-13")
    parser.add_argument("--exchange", default="", help="Exchange code (NYSE, NASDAQ, SEHK, LSE, …). Empty = auto-detect/US.")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    exchange_arg = args.exchange.upper().strip()
    case_dir = Path(args.case_dir).resolve()
    case_dir.mkdir(parents=True, exist_ok=True)

    now_iso = now_utc_iso()
    date_cut = case_dir.name[:10]  # "2026-02-12" from dir name
    modelo_suffix = case_dir.name[11:] if len(case_dir.name) > 10 else ""
    faltantes: List[Dict[str, Any]] = []

    is_us = exchange_arg in US_EXCHANGES

    # ── Snapshot data ──────────────────────────────────────────────
    if is_us:
        try:
            ctx = fetch_finviz_context(ticker)
        except Exception as exc:
            ctx = {"url": "", "company_name": ticker, "sector": None, "industry": None,
                   "country": None, "exchange": None, "snapshot": {}}
            faltantes.append({
                "tipo": "MARKET_SNAPSHOT", "prioridad": "CRITICO",
                "razon": f"Finviz fetch failed: {exc}",
                "como_conseguirlo": "Reintentar o usar Yahoo Finance manualmente.",
            })
        currency = "USD"
        publicador = "Finviz + Stooq"
    else:
        ctx = fetch_yahoo_snapshot(ticker, exchange_arg)
        currency = ctx.get("currency", "USD")
        publicador = "Yahoo Finance + Stooq"
        if not ctx.get("snapshot"):
            faltantes.append({
                "tipo": "MARKET_SNAPSHOT", "prioridad": "CRITICO",
                "razon": f"Yahoo Finance returned no data for {ticker} on {exchange_arg}.",
                "como_conseguirlo": "Verificar ticker/exchange. Buscar manualmente en Yahoo Finance o Bloomberg.",
            })

    snapshot = ctx.get("snapshot", {})

    # ── OHLCV history ─────────────────────────────────────────────
    stooq_exchange = exchange_arg if exchange_arg else "US"
    stooq_rows = fetch_stooq_ohlcv(ticker, stooq_exchange)
    if not stooq_rows and not is_us:
        # Fallback: try Yahoo chart for OHLCV (1y range)
        suffix = YAHOO_SUFFIX.get(exchange_arg, "")
        sym = f"{ticker}{suffix}"
        try:
            chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(sym)}?range=1y&interval=1d"
            resp = _get_with_retry(chart_url)
            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                ts_list = result[0].get("timestamp", [])
                indicators = result[0].get("indicators", {}).get("quote", [{}])[0]
                closes = indicators.get("close", [])
                volumes = indicators.get("volume", [])
                for i, ts in enumerate(ts_list):
                    if i < len(closes) and closes[i] is not None:
                        d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")
                        row = {"Date": d, "Close": str(closes[i]),
                               "Volume": str(volumes[i]) if i < len(volumes) and volumes[i] is not None else "0"}
                        stooq_rows.append(row)
        except Exception:
            pass

    # ── Extract values ────────────────────────────────────────────
    price = to_float(snapshot.get("Price"))
    prev_close = to_float(snapshot.get("Prev Close"))
    change_pct = to_float(snapshot.get("Change"))

    market_cap = to_float(snapshot.get("Market Cap"))
    market_cap_m = round(market_cap / 1_000_000, 2) if market_cap is not None else None

    shares = to_float(snapshot.get("Shs Outstand"))
    shares_m = round(shares / 1_000_000, 4) if shares is not None else None

    vol_last = to_float(snapshot.get("Volume"))
    vol_avg30 = rolling_avg_volume(stooq_rows, 30)
    if vol_avg30 is not None:
        vol_avg30 = round(vol_avg30)

    high_52w, low_52w = max_min_52w(stooq_rows)
    beta = to_float(snapshot.get("Beta"))
    pe = to_float(snapshot.get("P/E"))
    pb = to_float(snapshot.get("P/B"))
    target = to_float(snapshot.get("Target Price"))
    inst_own = to_float(snapshot.get("Inst Own"))
    insider_own = to_float(snapshot.get("Insider Own"))
    div_yield = to_float(snapshot.get("Dividend %"))

    exchange_out = ctx.get("exchange") or exchange_arg or "UNKNOWN"
    country = ctx.get("country") or "UNKNOWN"
    sector = ctx.get("sector") or "UNKNOWN"
    industry = ctx.get("industry") or "UNKNOWN"

    # If both snapshot and OHLCV are empty → CRÍTICO
    if price is None and not stooq_rows:
        faltantes.append({
            "tipo": "MARKET_DATA_COMPLETO", "prioridad": "CRITICO",
            "razon": f"No market data found for {ticker} ({exchange_out}).",
            "como_conseguirlo": "Verificar que el ticker y bolsa son correctos. Buscar en Bloomberg/Reuters.",
        })

    source = {
        "source_id": "SRC_MKT_001",
        "tipo": "MARKET_DATA",
        "titulo": f"Market Data - {ticker} @ {date_cut}",
        "url": ctx.get("url", ""),
        "publicador": publicador,
        "fecha_publicacion": date_cut,
        "fecha_recuperacion": date_cut,
        "idioma": "en",
        "fiabilidad": "B",
        "relevancia": "ALTA",
        "notas": f"Snapshot {'Finviz' if is_us else 'Yahoo Finance'} + serie Stooq. Exchange: {exchange_out}.",
        "datos": {
            "precio_cierre": price,
            "precio_previo": prev_close,
            "cambio_pct": change_pct,
            "moneda": currency,
            "market_cap_millones": market_cap_m,
            "shares_outstanding_millones": shares_m,
            "volumen_diario_promedio_30d": vol_avg30,
            "volumen_ultimo_dia": int(vol_last) if vol_last is not None else None,
            "rango_52_semanas": {
                "high": round(high_52w, 4) if high_52w is not None else None,
                "low": round(low_52w, 4) if low_52w is not None else None,
                "fecha": date_cut,
            },
            "beta_5y": beta,
            "dividend_yield_pct": div_yield,
            "pb_ratio": pb,
            "pe_ratio_ttm": pe,
            "insider_ownership_pct": insider_own,
            "institutional_ownership_pct": inst_own,
            "precio_objetivo_medio": target,
        },
        "fecha_datos": now_iso,
        "divisa": currency,
        "cita_rapida": f"{ticker}: {currency} {price}, market cap {currency} {market_cap_m}M, 52w {low_52w}-{high_52w}.",
    }

    out: Dict[str, Any] = {
        "version_esquema": "SourcesPack_v1",
        "caso_id": f"CASE_{date_cut.replace('-', '')}_{ticker}" + (f"_{modelo_suffix}" if modelo_suffix else ""),
        "fecha_corte": date_cut,
        "empresa": {
            "ticker": ticker,
            "nombre": ctx.get("company_name", ticker),
            "bolsa": exchange_out,
            "pais": country if len(country) <= 3 else "US" if country.upper() in {"USA", "UNITED STATES"} else country,
            "sector": sector,
            "industria": industry,
            "web_ir": None,
        },
        "fuentes": [source] if price is not None or stooq_rows else [],
        "faltantes": faltantes,
        "sub_agent": "MARKET_DATA",
        "timestamp": now_iso,
    }

    out_path = case_dir / "_market_data_output.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ticker": ticker,
                "exchange": exchange_out,
                "case_dir": str(case_dir),
                "output": str(out_path),
                "price": price,
                "currency": currency,
                "market_cap_m": market_cap_m,
                "shares_m": shares_m,
                "sources": len(out["fuentes"]),
                "faltantes": len(faltantes),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
