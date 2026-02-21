#!/usr/bin/env python3
"""SEC EDGAR filing fetcher for ELSIAN INVEST pipeline.

Downloads 10-K/20-F, 10-Q/6-K, 8-K, DEF14A, and credit-agreement exhibits
from SEC EDGAR.  Produces SourcesPack_v1 JSON + raw filing files.

Usage:
    python3 scripts/runners/sec_fetcher_v2_runner.py --ticker CRTO --case-dir casos/CRTO/2026-02-14

Política de faltantes: ver _operativa/POLITICA_FALTANTES.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


USER_AGENT = "ELSIAN-INVEST-Bot/1.0 (research; bot@elsian-invest.local)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
ALT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": HEADERS["Accept"],
}
TIMEOUT = 40
RATE_LIMIT_SECONDS = 0.12

NON_US_EXCHANGES = {"LSE", "AIM", "SEHK", "HKEX", "ASX", "EPA", "TSX", "OTRA"}
NON_US_COUNTRIES = {"HK", "GB", "UK", "AU", "FR", "CA", "IL", "ISRAEL", "CN", "JP", "SG", "EU"}
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
PERIODIC_FORMS = {"10-Q", "6-K"}
EXTRA_SEC_FALLBACK_FORMS = {
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
}
LOCAL_FILING_KEYWORDS_COMMON = (
    "announcement",
    "results",
    "financial report",
    "interim report",
    "annual report",
    "regulatory",
    "filing",
    "press release",
    "news release",
    "trading update",
    "statement",
)
LOCAL_FILING_KEYWORDS_BY_EXCHANGE: Dict[str, Tuple[str, ...]] = {
    "SEHK": ("hkex", "announcement", "interim report", "annual report"),
    "HKEX": ("hkex", "announcement", "interim report", "annual report"),
    "LSE": ("rns", "regulatory news service", "annual report", "half year"),
    "AIM": ("rns", "regulatory news service", "annual report", "half year"),
    "ASX": ("asx", "appendix 4e", "appendix 4d", "quarterly activities report"),
    "EPA": ("document d'enregistrement universel", "communiqué", "résultats"),
}
LOCAL_FILING_NEGATIVE = (
    "privacy",
    "cookie",
    "terms",
    "careers",
    "job",
    "linkedin",
    "twitter.com",
    "facebook.com",
)


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SecClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._last_req = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_req
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)
        self._last_req = time.time()

    def get(self, url: str, *, binary: bool = False) -> requests.Response:
        self._throttle()
        try:
            resp = self._session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
        except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", 0)
            host = urlparse(url).netloc.lower()
            if status in (429, 500, 502, 503, 504) or isinstance(exc, requests.exceptions.ConnectionError):
                time.sleep(3)
                self._throttle()
                resp = self._session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                resp.raise_for_status()
            elif status == 403 and "sec.gov" not in host:
                # Some IR portals block bot-like User-Agents; use a browser UA
                # only for non-SEC domains to keep SEC requests policy-compliant.
                time.sleep(1)
                self._throttle()
                resp = self._session.get(url, headers=ALT_HEADERS, timeout=TIMEOUT, allow_redirects=True)
                resp.raise_for_status()
            else:
                raise
        if not binary:
            resp.encoding = resp.encoding or "utf-8"
        return resp

    def get_json(self, url: str) -> Dict[str, Any]:
        return self.get(url).json()


@dataclass
class FilingRecord:
    form: str
    filing_date: str
    accession: str
    primary_doc: str

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")


def parse_date(date_s: str) -> dt.date:
    return dt.date.fromisoformat(date_s)


def quarter_for_month(month: int) -> str:
    if month <= 3:
        return "Q1"
    if month <= 6:
        return "Q2"
    if month <= 9:
        return "Q3"
    return "Q4"


def period_from_doc_or_date(primary_doc: str, filing_date: str, form: str) -> str:
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", primary_doc)
    if match:
        y = int(match.group(1))
        m = int(match.group(2))
    else:
        d = parse_date(filing_date)
        y = d.year
        m = d.month
    if form in {"10-K", "20-F"}:
        return f"FY{y}"
    if form in {"10-Q", "6-K"}:
        return f"{quarter_for_month(m)}-{y}"
    return filing_date


def safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def parse_bool(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


def normalize_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in {"USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "US"
    if upper == "AUSTRALIA":
        return "AU"
    if upper == "ISRAEL":
        return "IL"
    return upper


def normalize_exchange(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = value.strip().upper()
    if not raw:
        return None
    if "OTC" in raw:
        return "OTC"
    return raw


def normalize_web_ir(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    candidate = url.strip()
    if not candidate:
        return None
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    return candidate.rstrip("/")


def is_non_us(exchange: Optional[str], country: Optional[str], cik10: Optional[str]) -> bool:
    if country and country not in {"US", "USA"}:
        return True
    if exchange and exchange in NON_US_EXCHANGES:
        return True
    if cik10 is None and country not in {"US", "USA"}:
        return True
    return False


def infer_regulator_code(exchange: Optional[str], country: Optional[str]) -> str:
    ex = (exchange or "").upper()
    c = (country or "").upper()
    if ex in {"SEHK", "HKEX"} or c == "HK":
        return "HKEX"
    if ex in {"LSE", "AIM"} or c in {"GB", "UK"}:
        return "RNS"
    if ex == "ASX" or c == "AU":
        return "ASX"
    if ex == "EPA" or c == "FR":
        return "EURONEXT"
    if ex == "TSX" or c == "CA":
        return "SEDAR+"
    return "LOCAL_IR"


def parse_date_loose(text: str) -> Optional[str]:
    m_iso = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if m_iso:
        return m_iso.group(1)
    for pattern in (r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", r"(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})"):
        m = re.search(pattern, text)
        if not m:
            continue
        raw = m.group(1)
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
            try:
                return dt.datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def read_sources_context(case_dir: Path) -> Dict[str, Any]:
    candidates = sorted(case_dir.glob("SourcesPack_v*.json"))
    if not candidates:
        return {}
    preferred = [
        p
        for p in candidates
        if not re.search(r"_(?:codex53|opus46|gemini3pro)\.json$", p.name, re.IGNORECASE)
    ]
    ordered = preferred + [p for p in candidates if p not in preferred]
    for path in ordered:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        empresa = data.get("empresa")
        if isinstance(empresa, dict):
            return empresa
    return {}


def build_local_ir_pages(web_ir: Optional[str]) -> List[str]:
    base = normalize_web_ir(web_ir)
    if not base:
        return []
    suffixes = (
        "",
        "/investor-relations",
        "/investors",
        "/news",
        "/news-events",
        "/announcements",
        "/financial-results",
        "/reports-results-and-presentations",
        "/publications",
        "/results",
    )
    pages: List[str] = []
    for suffix in suffixes:
        if not suffix:
            pages.append(base)
            continue
        pages.append(urljoin(base + "/", suffix.lstrip("/")))
    return list(dict.fromkeys(pages))


def extract_local_filing_candidates(
    html: str,
    base_url: str,
    exchange: Optional[str],
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    ex = (exchange or "").upper()
    kws = set(LOCAL_FILING_KEYWORDS_COMMON)
    kws.update(LOCAL_FILING_KEYWORDS_BY_EXCHANGE.get(ex, ()))

    by_url: Dict[str, Dict[str, Any]] = {}
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if not full_url.startswith(("http://", "https://")):
            continue

        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        parent = a.find_parent(["li", "tr", "div", "section", "article"])
        row_text = re.sub(r"\s+", " ", parent.get_text(" ", strip=True)).strip() if parent else text
        context = f"{text} {row_text} {full_url}".lower()
        # Normalize common URL/slug separators so keyword matching catches
        # forms like "annual-report" / "interim_report".
        context_norm = re.sub(r"[-_/]+", " ", context)

        if any(neg in context for neg in LOCAL_FILING_NEGATIVE):
            continue
        if "presentation" in context_norm or "deck" in context_norm or "slides" in context_norm:
            continue
        if not any(kw in context_norm for kw in kws):
            continue

        score = 0
        for kw in kws:
            if kw in context_norm:
                score += 1
        if full_url.lower().endswith(".pdf"):
            score += 1
        if "annual" in context or "interim" in context:
            score += 2
        if "rns" in context or "hkex" in context or "asx" in context:
            score += 2

        title = text or Path(urlparse(full_url).path).name or "Local filing"
        date_guess = parse_date_loose(context)

        prev = by_url.get(full_url)
        if prev is None or score > int(prev["score"]):
            by_url[full_url] = {
                "url": full_url,
                "titulo": title[:240],
                "score": score,
                "fecha_publicacion": date_guess,
                "snippet": row_text[:280] if row_text else title[:280],
            }

    candidates = sorted(
        by_url.values(),
        key=lambda x: (int(x["score"]), x.get("fecha_publicacion") or "0000-00-00"),
        reverse=True,
    )
    return candidates[:6]


def strip_html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def first_25_words(text: str) -> str:
    words = re.findall(r"\S+", text)
    return " ".join(words[:25])


def url_ext(url: str, fallback: str = "htm") -> str:
    path = urlparse(url).path
    m = re.search(r"\.([A-Za-z0-9]{2,5})$", path)
    if not m:
        return fallback
    ext = m.group(1).lower()
    if ext == "html":
        return "html"
    if ext in {"htm", "txt", "xml", "pdf"}:
        return ext
    return fallback


def build_doc_url(cik_int: int, record: FilingRecord, document: Optional[str] = None) -> str:
    doc = document or record.primary_doc
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{record.accession_nodash}/{doc}"


def build_index_json_url(cik_int: int, record: FilingRecord) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{record.accession_nodash}/index.json"


def collect_all_filings(client: SecClient, cik10: str) -> Dict[str, Any]:
    sub = client.get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
    recent = sub.get("filings", {}).get("recent", {})
    all_forms: List[str] = list(recent.get("form", []))
    all_dates: List[str] = list(recent.get("filingDate", []))
    all_acc: List[str] = list(recent.get("accessionNumber", []))
    all_docs: List[str] = list(recent.get("primaryDocument", []))

    for extra in sub.get("filings", {}).get("files", []):
        name = extra.get("name")
        if not name:
            continue
        payload = client.get_json(f"https://data.sec.gov/submissions/{name}")
        all_forms.extend(payload.get("form", []))
        all_dates.extend(payload.get("filingDate", []))
        all_acc.extend(payload.get("accessionNumber", []))
        all_docs.extend(payload.get("primaryDocument", []))

    records: List[FilingRecord] = []
    for form, date_s, acc, pdoc in zip(all_forms, all_dates, all_acc, all_docs):
        if not (form and date_s and acc and pdoc):
            continue
        records.append(FilingRecord(form=form.strip(), filing_date=date_s, accession=acc, primary_doc=pdoc))

    # Dedup by accession + form, keep earliest in list (newest first overall)
    seen = set()
    deduped: List[FilingRecord] = []
    for r in records:
        k = (r.form, r.accession)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)
    return {"submissions": sub, "records": deduped}


def find_exhibit_99_file(client: SecClient, cik_int: int, rec: FilingRecord) -> Optional[str]:
    try:
        idx = client.get_json(build_index_json_url(cik_int, rec))
    except Exception:
        return None
    items = idx.get("directory", {}).get("item", [])
    for entry in items:
        name = str(entry.get("name", ""))
        low = name.lower()
        if "index" in low or "header" in low:
            continue
        if not low.endswith((".htm", ".html", ".txt", ".xml")):
            continue
        # Avoid accession-number false positives (e.g. index files containing "...019981...")
        if re.search(r"(exhibit[-_ ]?99|ex[-_ ]?99|99[-_ ]?1)", low):
            return name
    return None


def get_doc_text(client: SecClient, url: str) -> Tuple[bytes, str]:
    resp = client.get(url, binary=True)
    content = resp.content
    ctype = resp.headers.get("Content-Type", "").lower()
    if "application/pdf" in ctype or url.lower().endswith(".pdf"):
        # Keep text extraction simple and deterministic for SEC fetcher use.
        text = "[PDF original descargado; extracción de texto no disponible en este runner]"
        return content, text
    try:
        decoded = content.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        decoded = content.decode("utf-8", errors="replace")
    text = strip_html_to_text(decoded)
    return content, text


def detect_credit_exhibits(
    client: SecClient,
    cik_int: int,
    candidate_records: Iterable[FilingRecord],
    limit: int = 3,
) -> List[Tuple[FilingRecord, str]]:
    out: List[Tuple[FilingRecord, str]] = []
    for rec in candidate_records:
        if len(out) >= limit:
            break
        try:
            idx = client.get_json(build_index_json_url(cik_int, rec))
        except Exception:
            continue
        for entry in idx.get("directory", {}).get("item", []):
            name = str(entry.get("name", ""))
            low = name.lower()
            if not low.endswith((".htm", ".html", ".txt", ".xml", ".pdf")):
                continue
            # Heuristic for exhibit 10 + credit agreement keywords.
            if ("ex10" in low or "exhibit10" in low or "10-" in low) and any(
                kw in low for kw in ("credit", "loan", "facility", "revolver", "agreement")
            ):
                out.append((rec, name))
                break
    return out


def list_supporting_docs(
    client: SecClient,
    cik_int: int,
    rec: FilingRecord,
    limit: int = 6,
) -> List[str]:
    try:
        idx = client.get_json(build_index_json_url(cik_int, rec))
    except Exception:
        return []
    items = idx.get("directory", {}).get("item", [])
    out: List[str] = []
    primary = rec.primary_doc.lower()
    for entry in items:
        name = str(entry.get("name", ""))
        low = name.lower()
        if not low or low == primary:
            continue
        if "index" in low or "header" in low:
            continue
        if not low.endswith((".htm", ".html", ".txt", ".xml", ".pdf")):
            continue
        out.append(name)
        if len(out) >= limit:
            break
    return out


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def raw_dir_local_path(raw_dir: Path, filename: str) -> str:
    """Return repo-root-relative path for a file in raw_dir."""
    full = raw_dir / filename
    try:
        return str(full.relative_to(REPO_ROOT))
    except ValueError:
        return f"_raw_filings/{filename}"


def write_raw_files(
    client: SecClient,
    raw_dir: Path,
    source_id: str,
    tipo: str,
    period: str,
    url: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        binary, text = get_doc_text(client, url)
    except Exception as e:
        return None, None, f"descarga fallida: {e}"

    ext = url_ext(url, fallback="htm")
    base = f"{source_id}_{safe_slug(tipo.upper())}_{safe_slug(period)}"
    original_name = f"{base}.{ext}"
    txt_name = f"{base}.txt"

    (raw_dir / original_name).write_bytes(binary)
    (raw_dir / txt_name).write_text(text, encoding="utf-8")

    # Generate .ixbrl.json and .clean.md for financial filings
    htm_path = raw_dir / original_name
    tipo_upper = tipo.upper().replace(" ", "")
    is_financial = any(ft in tipo_upper for ft in ("10-K", "10K", "20-F", "20F", "10-Q", "10Q", "6-K", "6K"))
    if is_financial and ext in ("htm", "html"):
        try:
            from scripts.runners.ixbrl_extractor import extract_ixbrl_facts
            ixbrl_data = extract_ixbrl_facts(htm_path)
            ixbrl_name = f"{base}.ixbrl.json"
            import json as _json
            (raw_dir / ixbrl_name).write_text(
                _json.dumps(ixbrl_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"WARNING: iXBRL extraction failed for {original_name}: {e}", file=sys.stderr)

        try:
            from scripts.runners.clean_md_extractor import extract_financial_tables
            clean_md = extract_financial_tables(htm_path)
            if clean_md:  # empty string = quality gate rejected
                clean_name = f"{base}.clean.md"
                (raw_dir / clean_name).write_text(clean_md, encoding="utf-8")
        except Exception as e:
            print(f"WARNING: clean.md extraction failed for {original_name}: {e}", file=sys.stderr)

    return raw_dir_local_path(raw_dir, txt_name), first_25_words(text), None


def main() -> int:
    parser = argparse.ArgumentParser(description="SEC_FETCHER_V2 runner")
    parser.add_argument("--ticker", required=True, help="Ticker, e.g., OSPN")
    parser.add_argument("--case-dir", required=True, help="Case directory, e.g., casos/OSPN/2026-02-13")
    parser.add_argument("--raw-dir", default="", help="Raw filings directory (default: casos/{T}/_raw_filings)")
    parser.add_argument("--exchange", default="", help="Exchange hint (NYSE, NASDAQ, LSE, SEHK, ...)")
    parser.add_argument("--country", default="", help="Country hint (US, GB, HK, ...)")
    parser.add_argument("--web-ir", default="", help="Investor relations base URL")
    parser.add_argument(
        "--enable-local-fallback",
        default="true",
        help="If true, attempts local regulatory/IR filings for non-US coverage.",
    )
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    case_dir = Path(args.case_dir).resolve()
    if args.raw_dir:
        raw_dir = Path(args.raw_dir).resolve()
    else:
        raw_dir = case_dir.parent / "_raw_filings"  # ticker-level
    raw_dir.mkdir(parents=True, exist_ok=True)
    enable_local_fallback = parse_bool(args.enable_local_fallback)
    src_empresa = read_sources_context(case_dir)

    exchange = normalize_exchange(args.exchange) or normalize_exchange(src_empresa.get("bolsa"))
    country = normalize_country(args.country) or normalize_country(src_empresa.get("pais"))
    web_ir = normalize_web_ir(args.web_ir) or normalize_web_ir(src_empresa.get("web_ir"))

    client = SecClient()
    ticker_map = client.get_json("https://www.sec.gov/files/company_tickers.json")
    row = None
    for val in ticker_map.values():
        if str(val.get("ticker", "")).upper() == ticker:
            row = val
            break
    if row:
        cik_int = int(row["cik_str"])
        cik10: Optional[str] = str(cik_int).zfill(10)
        payload = collect_all_filings(client, cik10)
        sub = payload["submissions"]
        records: List[FilingRecord] = payload["records"]
    else:
        cik_int = -1
        cik10 = None
        sub = {}
        records = []

    annual: List[FilingRecord] = []
    quarterly: List[FilingRecord] = []
    proxy: List[FilingRecord] = []
    earnings_8k: List[Tuple[FilingRecord, Optional[str]]] = []
    general_8k: List[FilingRecord] = []
    credit_matches: List[Tuple[FilingRecord, str]] = []
    extra_sec_fallback: List[FilingRecord] = []

    if records:
        has_fpi_forms = any(r.form in {"20-F", "6-K", "40-F"} for r in records)
        annual_limit = 6
        periodic_limit = 12

        annual = [r for r in records if r.form in ANNUAL_FORMS][:annual_limit]
        quarterly = [r for r in records if r.form in PERIODIC_FORMS][:periodic_limit]
        proxy = [r for r in records if r.form in {"DEF 14A", "DEF14A", "DEFC14A"}][:3]
        if not proxy:
            proxy = [r for r in records if r.form == "DEFA14A"][:3]

        # Earnings 8-K: require Item 2.02 signals in main doc or an EX-99 style exhibit.
        for rec in [r for r in records if r.form in {"8-K", "8-K/A"}][:160]:
            exhibit = find_exhibit_99_file(client, cik_int, rec)
            use_doc: Optional[str] = None
            is_earnings = False
            if exhibit:
                use_doc = exhibit
                is_earnings = True
            else:
                try:
                    _, text = get_doc_text(client, build_doc_url(cik_int, rec))
                    low = text.lower()
                    if "item 2.02" in low or "results of operations and financial condition" in low:
                        is_earnings = True
                except Exception:
                    is_earnings = False
            if is_earnings:
                if len(earnings_8k) < 10:
                    earnings_8k.append((rec, use_doc))
            elif len(general_8k) < 16:
                general_8k.append(rec)

        credit_matches = detect_credit_exhibits(
            client,
            cik_int,
            [*annual, *quarterly, *(r for r, _ in earnings_8k)],
            limit=2,
        )

        sec_canonical_count = (
            len(annual)
            + len(quarterly)
            + len(earnings_8k)
            + len(general_8k)
            + len(proxy)
            + len(credit_matches)
        )
        non_us_hint = is_non_us(exchange, country, cik10)
        if not non_us_hint and sec_canonical_count < 20:
            need = 20 - sec_canonical_count
            extra_pool = [r for r in records if r.form in EXTRA_SEC_FALLBACK_FORMS]
            extra_sec_fallback = extra_pool[: max(0, need) + 8]

    empresa = {
        "ticker": ticker,
        "nombre": sub.get("name") or (row.get("title") if row else None) or src_empresa.get("nombre"),
        "cik": cik10,
        "bolsa": exchange,
        "pais": country,
        "web_ir": web_ir,
    }

    out: Dict[str, Any] = {
        "version_esquema": "SourcesPack_v1",
        "empresa": empresa,
        "fuentes": [],
        "faltantes": [],
        "cache_stats": {
            "archivos_descargados": 0,
            "archivos_fallidos": 0,
            "directorio": str(raw_dir.relative_to(REPO_ROOT)) if raw_dir.is_relative_to(REPO_ROOT) else "_raw_filings/",
        },
        "sub_agent": "SEC_FETCHER",
        "timestamp": now_utc_iso(),
    }

    def add_missing(tipo: str, prioridad: str, razon: str, como: str) -> None:
        out["faltantes"].append(
            {
                "tipo": tipo,
                "prioridad": prioridad,
                "razon": razon,
                "como_conseguirlo": como,
            }
        )

    source_counter = 1
    used_source_keys: set[Tuple[str, str, str]] = set()

    def push_source(
        *,
        tipo: str,
        title: str,
        rec: FilingRecord,
        doc_url: str,
        period: str,
        ubicacion_relevante: Optional[str] = None,
    ) -> None:
        nonlocal source_counter
        key = (rec.accession, tipo.upper(), doc_url)
        if key in used_source_keys:
            return
        used_source_keys.add(key)
        source_id = f"SRC_SEC_{source_counter:03d}"
        source_counter += 1

        local_path, quote, err = write_raw_files(client, raw_dir, source_id, tipo, period, doc_url)
        if err:
            out["cache_stats"]["archivos_fallidos"] += 1
        else:
            out["cache_stats"]["archivos_descargados"] += 1

        source: Dict[str, Any] = {
            "source_id": source_id,
            "categoria": "REGULATORIO",
            "tipo": tipo,
            "titulo": title,
            "url": doc_url,
            "accession_number": rec.accession,
            "fecha_publicacion": rec.filing_date,
            "fecha_recuperacion": dt.date.today().isoformat(),
            "publicador": "SEC",
            "cita_rapida": quote or "",
        }
        if ubicacion_relevante:
            source["ubicacion_relevante"] = ubicacion_relevante
        if local_path:
            source["local_path"] = local_path
        out["fuentes"].append(source)

        if err:
            out.setdefault("log", {}).setdefault("limitaciones", []).append(
                f"{source_id} ({tipo}) sin local_path: {err}"
            )

    for rec in annual:
        period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
        push_source(
            tipo=rec.form,
            title=f"Form {rec.form} - {period}",
            rec=rec,
            doc_url=build_doc_url(cik_int, rec),
            period=period,
            ubicacion_relevante="Item 7 - Management's Discussion and Analysis",
        )

    for rec in quarterly:
        period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
        push_source(
            tipo=rec.form,
            title=f"Form {rec.form} - {period}",
            rec=rec,
            doc_url=build_doc_url(cik_int, rec),
            period=period,
            ubicacion_relevante="Financial Statements / MD&A",
        )

    for rec, exhibit in earnings_8k:
        period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
        url = build_doc_url(cik_int, rec, exhibit) if exhibit else build_doc_url(cik_int, rec)
        push_source(
            tipo="8-K",
            title=f"Form 8-K Earnings - {period}",
            rec=rec,
            doc_url=url,
            period=period,
            ubicacion_relevante="Item 2.02 / Exhibit 99",
        )

    for rec in general_8k:
        period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
        push_source(
            tipo="8-K",
            title=f"Form 8-K - {period}",
            rec=rec,
            doc_url=build_doc_url(cik_int, rec),
            period=period,
            ubicacion_relevante="Current Report",
        )

    for rec in proxy:
        period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
        push_source(
            tipo="DEF14A",
            title=f"Form {rec.form} - {period}",
            rec=rec,
            doc_url=build_doc_url(cik_int, rec),
            period=period,
            ubicacion_relevante="Executive compensation / Governance",
        )

    for rec, exhibit_doc in credit_matches:
        period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
        push_source(
            tipo="CREDIT_AGREEMENT",
            title=f"Credit Agreement Exhibit - {period}",
            rec=rec,
            doc_url=build_doc_url(cik_int, rec, exhibit_doc),
            period=period,
            ubicacion_relevante="Exhibit 10.x",
        )

    for rec in extra_sec_fallback:
        period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
        push_source(
            tipo=rec.form,
            title=f"Form {rec.form} - {period}",
            rec=rec,
            doc_url=build_doc_url(cik_int, rec),
            period=period,
            ubicacion_relevante="Ownership / Registration",
        )

    # If domestic SEC coverage is still short, add supporting exhibits/docs from
    # EDGAR filing indexes (same accessions, additional supporting documents).
    non_us_hint = is_non_us(exchange, country, cik10)
    if cik10 and not non_us_hint and len(out["fuentes"]) < 20:
        needed = 20 - len(out["fuentes"])
        candidate_records = [*annual, *quarterly, *(r for r, _ in earnings_8k), *general_8k, *proxy, *extra_sec_fallback]
        seen_acc: set[str] = set()
        unique_records: List[FilingRecord] = []
        for rec in candidate_records:
            if rec.accession in seen_acc:
                continue
            seen_acc.add(rec.accession)
            unique_records.append(rec)

        for rec in unique_records:
            if needed <= 0:
                break
            period = period_from_doc_or_date(rec.primary_doc, rec.filing_date, rec.form)
            for doc_name in list_supporting_docs(client, cik_int, rec, limit=8):
                if needed <= 0:
                    break
                push_source(
                    tipo="SEC_EXHIBIT",
                    title=f"SEC Exhibit - {period}",
                    rec=rec,
                    doc_url=build_doc_url(cik_int, rec, doc_name),
                    period=period,
                    ubicacion_relevante="Exhibit / Supporting document",
                )
                needed = 20 - len(out["fuentes"])

    # Local non-US fallback (hybrid by availability): add local regulatory/IR filings
    # when SEC is non-applicable or clearly insufficient for non-US coverage.
    local_fallback_attempted = False
    local_fallback_added = 0
    local_fallback_errors: List[str] = []

    sec_forms_present = {
        str(src.get("tipo", "")).upper()
        for src in out["fuentes"]
        if str(src.get("tipo", "")).upper() in {"10-K", "20-F", "40-F", "10-Q", "6-K", "8-K", "DEF14A"}
    }
    fpi_like = "20-F" in sec_forms_present or "40-F" in sec_forms_present or "6-K" in sec_forms_present
    sec_threshold = 10 if fpi_like else 20
    non_us_hint = is_non_us(exchange, country, cik10)

    need_local_fallback = enable_local_fallback and non_us_hint and (
        cik10 is None or len(out["fuentes"]) < sec_threshold
    )

    if need_local_fallback:
        local_fallback_attempted = True
        # Try to resolve/validate web_ir before building pages
        if web_ir:
            try:
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location(
                    "ir_url_resolver",
                    str(Path(__file__).resolve().parent / "ir_url_resolver.py"),
                )
                _mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                resolved = _mod.resolve_ir_base_url(web_ir, client._session, timeout=10)
                if resolved and resolved != web_ir:
                    print(f"[sec_fetcher] Resolved IR: {web_ir} -> {resolved}", file=sys.stderr)
                    web_ir = resolved
                    out["empresa"]["web_ir"] = resolved
            except Exception as exc:
                print(f"[sec_fetcher] IR resolver failed: {exc}", file=sys.stderr)
        pages = build_local_ir_pages(web_ir)
        regulator_code = infer_regulator_code(exchange, country)

        if not pages:
            local_fallback_errors.append("web_ir no disponible para intentar fallback local.")
        else:
            collected: Dict[str, Dict[str, Any]] = {}
            for page in pages:
                try:
                    html = client.get(page).text
                except Exception as exc:
                    local_fallback_errors.append(f"No se pudo cargar {page}: {exc}")
                    continue

                for candidate in extract_local_filing_candidates(html, page, exchange):
                    url = str(candidate.get("url") or "")
                    if not url:
                        continue
                    prev = collected.get(url)
                    if prev is None or int(candidate.get("score", 0)) > int(prev.get("score", 0)):
                        collected[url] = candidate

            selected = sorted(
                collected.values(),
                key=lambda x: (int(x.get("score", 0)), x.get("fecha_publicacion") or "0000-00-00"),
                reverse=True,
            )[:4]

            for cand in selected:
                source_id = f"SRC_SEC_{source_counter:03d}"
                source_counter += 1
                doc_url = str(cand.get("url", ""))
                title = str(cand.get("titulo") or "Local regulatory filing")
                fecha_pub = str(cand.get("fecha_publicacion") or dt.date.today().isoformat())
                period = fecha_pub

                local_path_val, quote, err = write_raw_files(client, raw_dir, source_id, "IR_NEWS", period, doc_url)
                if err:
                    out["cache_stats"]["archivos_fallidos"] += 1
                    local_fallback_errors.append(f"{source_id} fallback local sin descarga: {err}")
                else:
                    out["cache_stats"]["archivos_descargados"] += 1

                # Classify filing type from context (title + URL + snippet)
                # Works for both PDF and HTML documents
                _ctx = f"{title.lower()} {doc_url.lower()} {str(cand.get('snippet') or '').lower()}"
                _url_low = doc_url.lower()
                _is_media_url = (
                    "youtube.com" in _url_low
                    or "youtu.be" in _url_low
                    or "vimeo.com" in _url_low
                    or "watch?v=" in _url_low
                    or _url_low.endswith((".mp4", ".mov", ".avi", ".m3u8"))
                )
                if _is_media_url:
                    _tipo = "OTHER"
                elif any(w in _ctx for w in ("annual", "full year", "year-end", "year end")):
                    _tipo = "ANNUAL_REPORT"
                elif any(w in _ctx for w in ("interim", "half year", "h1 ", "h2 ", "half-year")):
                    _tipo = "INTERIM_REPORT"
                elif "rns" in _ctx or "regulatory news" in _ctx or "announcement" in _ctx:
                    _tipo = "IR_NEWS"
                elif any(w in _ctx for w in ("results", "financial")):
                    _tipo = "REGULATORY_FILING"
                else:
                    _tipo = "OTHER"

                source: Dict[str, Any] = {
                    "source_id": source_id,
                    "categoria": "REGULATORIO",
                    "tipo": _tipo,
                    "titulo": title,
                    "url": doc_url,
                    "publicador": "Company IR / Local regulator",
                    "fecha_publicacion": fecha_pub,
                    "fecha_recuperacion": dt.date.today().isoformat(),
                    "idioma": "en",
                    "fiabilidad": "B",
                    "relevancia": "ALTA",
                    "notas": f"Fallback local no-US ({regulator_code}).",
                    "cita_rapida": quote or str(cand.get("snippet") or "")[:180],
                    "origen_regulatorio_local": True,
                    "regulator_code": regulator_code,
                }
                if local_path_val:
                    source["local_path"] = local_path_val
                out["fuentes"].append(source)
                local_fallback_added += 1

        if local_fallback_added == 0:
            add_missing(
                "Local regulatory filings",
                "CRITICO",
                "No se localizaron filings regulatorios locales tras fallback en IR/regulador.",
                "Revisar manualmente el regulador local (HKEX/RNS/ASX/Euronext) y la sección Investor Relations.",
            )

    if cik10 is None:
        # Not SEC-registered — single INFO faltante, no per-filing noise.
        add_missing(
            "SEC Filings",
            "INFO",
            f"Ticker {ticker} no encontrado en SEC company_tickers.json. "
            "Empresa probablemente no registrada en SEC (non-US o pre-IPO). "
            "Filings regulatorios deben buscarse en el regulador local.",
            "Para SEHK: HKEX news.  Para LSE: Regulatory News Service (RNS).  "
            "Para TSX: SEDAR+.  Para ADRs: verificar si existe un CIK alternativo.",
        )
    else:
        # SEC-registered — report individual missing filings.
        if not annual:
            add_missing(
                "10-K/20-F/40-F",
                "CRITICO",
                "No se encontraron informes anuales en submissions SEC.",
                f"Buscar en SEC EDGAR por CIK {cik10} > Filings > 10-K/20-F/40-F",
            )
        if not quarterly:
            add_missing(
                "10-Q/6-K",
                "ALTO",
                "No se encontraron informes trimestrales recientes en submissions SEC.",
                f"Buscar en SEC EDGAR por CIK {cik10} > Filings > 10-Q/6-K",
            )
        if not earnings_8k:
            add_missing(
                "8-K Earnings (Item 2.02 / Ex-99)",
                "ALTO",
                "No se localizaron 8-K de resultados con señales de Item 2.02/Exhibit 99.",
                f"Buscar en SEC EDGAR por CIK {cik10} > Filings > 8-K",
            )
        if not proxy:
            add_missing(
                "DEF14A",
                "MEDIO",
                "No se localizaron proxies recientes.",
                f"Buscar en SEC EDGAR por CIK {cik10} > Filings > DEF 14A",
            )
        if not credit_matches:
            add_missing(
                "Credit Agreement",
                "MEDIO",
                "No se localizaron exhibits 10.x con patrones de crédito/facilidad.",
                f"Revisar 8-K y 10-Q/10-K por CIK {cik10} y buscar Exhibit 10.x",
            )

    out["local_fallback"] = {
        "enabled": enable_local_fallback,
        "attempted": local_fallback_attempted,
        "sources_added": local_fallback_added,
        "exchange": exchange,
        "country": country,
        "web_ir": web_ir,
    }
    if local_fallback_errors:
        out.setdefault("log", {}).setdefault("limitaciones", []).extend(local_fallback_errors)

    out_path = case_dir / "_sec_fetcher_output.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(
        {
            "ticker": ticker,
            "case_dir": str(case_dir),
            "output": str(out_path),
            "sources": len(out["fuentes"]),
            "downloaded": out["cache_stats"]["archivos_descargados"],
            "failed": out["cache_stats"]["archivos_fallidos"],
            "missing": len(out["faltantes"]),
            "local_fallback_added": local_fallback_added,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
