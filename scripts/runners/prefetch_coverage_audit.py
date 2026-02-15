#!/usr/bin/env python3
"""Audit pre-fetch coverage status for latest case per ticker.

Outputs:
  - tmp/prefetch_coverage_report_YYYY-MM-DD.json
  - tmp/prefetch_coverage_report_YYYY-MM-DD.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CASE_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:_\w+)?$")
US_COUNTRIES = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}
NON_US_EXCHANGES = {"LSE", "AIM", "SEHK", "HKEX", "ASX", "EPA", "TSX", "OTRA"}

SEC_TYPES = {
    "10-K",
    "20-F",
    "40-F",
    "10-Q",
    "6-K",
    "8-K",
    "DEF14A",
    "CREDIT_AGREEMENT",
    "3",
    "4",
    "4/A",
    "S-1",
    "S-1/A",
    "S-8",
    "424B4",
    "10-12B",
    "10-12B/A",
    "8-A12B",
    "D",
    "DRS",
    "DRS/A",
    "SEC_EXHIBIT",
}
ANNUAL_TYPES = {"10-K", "20-F", "40-F"}
PERIODIC_TYPES = {"10-Q", "6-K"}


def today_iso() -> str:
    return dt.date.today().isoformat()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def jread(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def normalize_country(value: Optional[str]) -> str:
    if not value:
        return ""
    v = value.strip().upper()
    if v == "AUSTRALIA":
        return "AU"
    if v == "ISRAEL":
        return "IL"
    return v


def normalize_exchange(value: Optional[str]) -> str:
    if not value:
        return ""
    v = value.strip().upper()
    if "OTC" in v:
        return "OTC"
    return v


def latest_case_dirs(casos_root: Path) -> List[Path]:
    """Return the most recent case dir per ticker for prefetch coverage."""
    out: List[Path] = []
    for ticker_dir in sorted(p for p in casos_root.iterdir() if p.is_dir()):
        date_dirs = sorted(
            (d for d in ticker_dir.iterdir() if d.is_dir() and CASE_DIR_RE.match(d.name)),
            key=lambda x: x.name[:10],
        )
        if not date_dirs:
            continue
        latest_date = date_dirs[-1].name[:10]
        candidates = [d for d in date_dirs if d.name[:10] == latest_date]
        # Prefer prefetch-only (no suffix)
        prefetch_only = [d for d in candidates if len(d.name) == 10]
        if prefetch_only:
            out.append(prefetch_only[0])
            continue
        # Prefer dir without _estado.json (not yet executed)
        no_estado = [d for d in candidates if not (d / "_estado.json").exists()]
        if no_estado:
            out.append(no_estado[0])
            continue
        # Fallback: first alphabetically
        out.append(candidates[0])
    return out


def read_empresa_context(case_dir: Path, sec_d: Optional[Dict[str, Any]], tr_d: Optional[Dict[str, Any]], mkt_d: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # Prefer canonical sources pack first.
    sources_packs = sorted(case_dir.glob("SourcesPack_v*.json"))
    preferred = [
        p
        for p in sources_packs
        if not re.search(r"_(?:codex53|opus46|gemini3pro)\.json$", p.name, re.IGNORECASE)
    ]
    ordered = preferred + [p for p in sources_packs if p not in preferred]
    for path in ordered:
        d = jread(path)
        if d and isinstance(d.get("empresa"), dict):
            return d["empresa"]

    for d in (mkt_d, tr_d, sec_d):
        if d and isinstance(d.get("empresa"), dict):
            return d["empresa"]
    return {}


def extract_sec_metrics(sec_d: Optional[Dict[str, Any]]) -> Tuple[int, int, int, int]:
    if not sec_d:
        return 0, 0, 0, 0
    sec_count = 0
    local_count = 0
    annual_count = 0
    periodic_count = 0
    for src in sec_d.get("fuentes", []):
        if not isinstance(src, dict):
            continue
        tipo = str(src.get("tipo", "")).upper()
        is_local = bool(src.get("origen_regulatorio_local")) or (
            str(src.get("categoria", "")).upper() == "REGULATORIO" and tipo in {"IR_NEWS", "OTHER"}
        )
        if is_local:
            local_count += 1
            continue
        if tipo in SEC_TYPES:
            sec_count += 1
        if tipo in ANNUAL_TYPES:
            annual_count += 1
        if tipo in PERIODIC_TYPES:
            periodic_count += 1
    return sec_count, local_count, annual_count, periodic_count


def issuer_class(country: str, exchange: str, cik: Optional[str], has_20f_or_6k: bool) -> str:
    non_us_country = bool(country) and country not in US_COUNTRIES
    non_us_exchange = exchange in NON_US_EXCHANGES

    if cik and (has_20f_or_6k or non_us_country):
        return "FPI_ADR"
    if not cik or non_us_exchange or non_us_country:
        return "NonUS_Local"
    return "Domestic_US"


def load_exception(case_dir: Path) -> Optional[Dict[str, Any]]:
    exc_path = case_dir / "_prefetch_coverage_exception.json"
    if not exc_path.exists():
        return None
    return jread(exc_path)


def evaluate_case(case_dir: Path) -> Dict[str, Any]:
    ticker = case_dir.parent.name.upper()
    sec_d = jread(case_dir / "_sec_fetcher_output.json")
    tr_d = jread(case_dir / "_transcript_finder_output.json")
    mkt_d = jread(case_dir / "_market_data_output.json")
    estado_d = jread(case_dir / "_estado.json")
    empresa = read_empresa_context(case_dir, sec_d, tr_d, mkt_d)

    country = normalize_country(empresa.get("pais"))
    exchange = normalize_exchange(empresa.get("bolsa"))
    web_ir = empresa.get("web_ir")
    cik = (sec_d or {}).get("empresa", {}).get("cik")

    sec_count, local_count, annual_count, periodic_count = extract_sec_metrics(sec_d)
    trans_count = len((tr_d or {}).get("fuentes", [])) if tr_d else 0
    mkt_count = len((mkt_d or {}).get("fuentes", [])) if mkt_d else 0

    has_20f_or_6k = False
    for src in (sec_d or {}).get("fuentes", []):
        if str(src.get("tipo", "")).upper() in {"20-F", "6-K"}:
            has_20f_or_6k = True
            break

    cls = issuer_class(country, exchange, cik, has_20f_or_6k)
    required: List[str] = []
    if cls == "Domestic_US":
        if sec_count < 20:
            required.append("SEC")
        if trans_count < 6:
            required.append("TRANS")
        if mkt_count < 1:
            required.append("MKT")
    elif cls == "FPI_ADR":
        if sec_count < 10 or annual_count < 1 or periodic_count < 1:
            required.append("SEC")
        if trans_count < 4:
            required.append("TRANS")
        if mkt_count < 1:
            required.append("MKT")
    else:  # NonUS_Local
        if local_count < 1:
            required.append("LOCAL_FILINGS")
        if trans_count < 4:
            required.append("TRANS")
        if mkt_count < 1:
            required.append("MKT")

    exception_data = load_exception(case_dir)
    status = "PASS"
    if required:
        status = "EXCEPTION" if exception_data else "NEEDS_ACTION"

    return {
        "ticker": ticker,
        "case_dir": str(case_dir),
        "date": case_dir.name,
        "estado_pipeline": (estado_d or {}).get("estado_pipeline") or (estado_d or {}).get("estado"),
        "next_step": (estado_d or {}).get("next_step") or (estado_d or {}).get("proximo_step"),
        "issuer_class": cls,
        "country": country,
        "exchange": exchange,
        "web_ir": web_ir,
        "cik": cik,
        "sec_count": sec_count,
        "trans_count": trans_count,
        "mkt_count": mkt_count,
        "local_filing_count": local_count,
        "annual_count": annual_count,
        "periodic_count": periodic_count,
        "required_actions": required,
        "status": status,
        "exception": exception_data,
    }


def build_report(casos_root: Path, scope: str, report_date: str) -> Dict[str, Any]:
    if scope != "latest":
        raise ValueError("Solo se soporta --scope latest en esta fase.")

    case_dirs = latest_case_dirs(casos_root)
    cases = [evaluate_case(case_dir) for case_dir in case_dirs]

    summary = {
        "total_tickers": len(cases),
        "pass_count": sum(1 for c in cases if c["status"] == "PASS"),
        "needs_action_count": sum(1 for c in cases if c["status"] == "NEEDS_ACTION"),
        "exception_count": sum(1 for c in cases if c["status"] == "EXCEPTION"),
        "class_counts": {
            "Domestic_US": sum(1 for c in cases if c["issuer_class"] == "Domestic_US"),
            "FPI_ADR": sum(1 for c in cases if c["issuer_class"] == "FPI_ADR"),
            "NonUS_Local": sum(1 for c in cases if c["issuer_class"] == "NonUS_Local"),
        },
    }

    return {
        "version": "1.0",
        "generated_at": now_iso(),
        "date": report_date,
        "scope": scope,
        "summary": summary,
        "cases": sorted(cases, key=lambda x: x["ticker"]),
        "needs_action": [c for c in sorted(cases, key=lambda x: x["ticker"]) if c["status"] == "NEEDS_ACTION"],
        "exceptions": [c for c in sorted(cases, key=lambda x: x["ticker"]) if c["status"] == "EXCEPTION"],
        "pass": [c for c in sorted(cases, key=lambda x: x["ticker"]) if c["status"] == "PASS"],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines: List[str] = []
    lines.append(f"# Prefetch Coverage Report ({report['date']})")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Scope: `{report['scope']}`")
    lines.append(f"- Total tickers: `{s['total_tickers']}`")
    lines.append(f"- PASS: `{s['pass_count']}`")
    lines.append(f"- NEEDS_ACTION: `{s['needs_action_count']}`")
    lines.append(f"- EXCEPTION: `{s['exception_count']}`")
    lines.append("")
    lines.append("## Needs Action")
    lines.append("")
    if not report["needs_action"]:
        lines.append("- None")
    else:
        for c in report["needs_action"]:
            lines.append(
                f"- `{c['ticker']}` ({c['issuer_class']}): "
                f"SEC={c['sec_count']} TRANS={c['trans_count']} MKT={c['mkt_count']} LOCAL={c['local_filing_count']} "
                f"-> `{'+'.join(c['required_actions'])}`"
            )
    lines.append("")
    lines.append("## Exceptions")
    lines.append("")
    if not report["exceptions"]:
        lines.append("- None")
    else:
        for c in report["exceptions"]:
            reason = ""
            exc = c.get("exception")
            if isinstance(exc, dict):
                reason = str(exc.get("reason") or "")
            lines.append(
                f"- `{c['ticker']}` ({c['issuer_class']}): "
                f"pending `{'+'.join(c['required_actions'])}`. {reason}".strip()
            )
    lines.append("")
    lines.append("## PASS")
    lines.append("")
    for c in report["pass"]:
        lines.append(
            f"- `{c['ticker']}` ({c['issuer_class']}): "
            f"SEC={c['sec_count']} TRANS={c['trans_count']} MKT={c['mkt_count']} LOCAL={c['local_filing_count']}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prefetch coverage audit")
    parser.add_argument("--scope", default="latest", help="Coverage scope (latest)")
    parser.add_argument("--date", default=today_iso(), help="Report date YYYY-MM-DD")
    parser.add_argument("--casos-root", default="casos", help="Cases root directory")
    args = parser.parse_args()

    casos_root = Path(args.casos_root).resolve()
    report = build_report(casos_root, args.scope, args.date)

    tmp_dir = Path("tmp").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    json_path = tmp_dir / f"prefetch_coverage_report_{args.date}.json"
    md_path = tmp_dir / f"prefetch_coverage_report_{args.date}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "scope": args.scope,
                "date": args.date,
                "json": str(json_path),
                "markdown": str(md_path),
                "summary": report["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
