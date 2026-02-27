"""SEC EDGAR filing fetcher for the deterministic extraction module.

Refactored from scripts/runners/sec_fetcher_v2_runner.py.
Stripped of all pipeline dependencies (engine/, scripts/, _estado.json, git).
Provides: SecClient, CIK resolution, filing selection, download to local dir.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore[assignment]

from deterministic.src.acquire.pdf_to_text import extract_pdf_text
from deterministic.src.acquire.html_to_markdown import convert as html_to_markdown
from deterministic.src.schemas import AcquisitionResult, FilingInfo

# ── Constants ────────────────────────────────────────────────────────

USER_AGENT = "ELSIAN-INVEST-Bot/1.0 (research; bot@elsian-invest.local)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
TIMEOUT = 40
RATE_LIMIT_SECONDS = 0.12

ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
PERIODIC_FORMS = {"10-Q", "6-K"}

ANNUAL_TARGET = 6
QUARTERLY_TARGET = 12
EARNINGS_TARGET = 10


# ── HTTP Client ──────────────────────────────────────────────────────

class SecClient:
    """Rate-limited HTTP client for SEC EDGAR."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._last_req = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_req
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)
        self._last_req = time.time()

    def get(
        self,
        url: str,
        *,
        binary: bool = False,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> requests.Response:
        self._throttle()
        try:
            resp = self._session.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=timeout or TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.ConnectionError,
        ) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", 0)
            if status in (429, 500, 502, 503, 504) or isinstance(
                exc, requests.exceptions.ConnectionError
            ):
                time.sleep(3)
                self._throttle()
                resp = self._session.get(
                    url,
                    headers=HEADERS,
                    params=params,
                    timeout=timeout or TIMEOUT,
                    allow_redirects=True,
                )
                resp.raise_for_status()
            else:
                raise
        if not binary:
            resp.encoding = resp.encoding or "utf-8"
        return resp

    def get_json(self, url: str) -> Dict[str, Any]:
        return self.get(url).json()


# ── Helpers ──────────────────────────────────────────────────────────

def quarter_for_month(month: int) -> str:
    if month <= 3:
        return "Q1"
    if month <= 6:
        return "Q2"
    if month <= 9:
        return "Q3"
    return "Q4"


def period_from_doc_or_date(
    primary_doc: str, filing_date: str, form: str
) -> str:
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", primary_doc)
    if match:
        y = int(match.group(1))
        m = int(match.group(2))
    else:
        d = dt.date.fromisoformat(filing_date)
        y = d.year
        m = d.month
    if form in ANNUAL_FORMS:
        return f"FY{y}"
    if form in PERIODIC_FORMS:
        return f"{quarter_for_month(m)}-{y}"
    return filing_date


def safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def build_doc_url(cik_int: int, rec: FilingInfo, document: Optional[str] = None) -> str:
    doc = document or rec.primary_doc
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{rec.accession_nodash}/{doc}"


def build_index_json_url(cik_int: int, rec: FilingInfo) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{rec.accession_nodash}/index.json"


def strip_html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


# ── CIK Resolution ──────────────────────────────────────────────────

def resolve_cik(client: SecClient, ticker: str) -> Optional[Tuple[int, str]]:
    """Resolve ticker -> (cik_int, cik10). Returns None if not found."""
    ticker_map = client.get_json(
        "https://www.sec.gov/files/company_tickers.json"
    )
    for val in ticker_map.values():
        if str(val.get("ticker", "")).upper() == ticker.upper():
            cik_int = int(val["cik_str"])
            return cik_int, str(cik_int).zfill(10)
    return None


# ── Filing Collection ────────────────────────────────────────────────

def collect_all_filings(
    client: SecClient, cik10: str
) -> Tuple[Dict[str, Any], List[FilingInfo]]:
    """Fetch all filings for a CIK from EDGAR submissions API."""
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

    records: List[FilingInfo] = []
    for form, date_s, acc, pdoc in zip(
        all_forms, all_dates, all_acc, all_docs
    ):
        if not (form and date_s and acc and pdoc):
            continue
        records.append(
            FilingInfo(
                form=form.strip(),
                filing_date=date_s,
                accession=acc,
                primary_doc=pdoc,
            )
        )

    # Dedup by accession + form
    seen: set[Tuple[str, str]] = set()
    deduped: List[FilingInfo] = []
    for r in records:
        k = (r.form, r.accession)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)
    return sub, deduped


def find_exhibit_99(
    client: SecClient, cik_int: int, rec: FilingInfo
) -> Optional[str]:
    """Find Exhibit 99 document in an 8-K filing index."""
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
        if re.search(r"(exhibit[-_ ]?99|ex[-_ ]?99|99[-_ ]?1)", low):
            return name
    return None


# ── Download Logic ───────────────────────────────────────────────────

def _download_and_save(
    client: SecClient,
    url: str,
    output_dir: Path,
    prefix: str,
    form_label: str,
    period: str,
) -> Tuple[bool, str]:
    """Download a filing, save as .htm + .txt (+ .clean.md if HTML).

    Returns (success, error_message).
    """
    try:
        resp = client.get(url, binary=True)
    except Exception as exc:
        return False, str(exc)

    content = resp.content
    ctype = resp.headers.get("Content-Type", "").lower()
    is_pdf = "application/pdf" in ctype or url.lower().endswith(".pdf")

    # Determine filenames
    base_name = f"{prefix}_{form_label}_{period}"

    if is_pdf:
        pdf_path = output_dir / f"{base_name}.pdf"
        pdf_path.write_bytes(content)
        text = extract_pdf_text(content)
        txt_path = output_dir / f"{base_name}.txt"
        txt_path.write_text(text, encoding="utf-8")
    else:
        # HTML filing
        try:
            decoded = content.decode(
                resp.encoding or "utf-8", errors="replace"
            )
        except Exception:
            decoded = content.decode("utf-8", errors="replace")

        htm_path = output_dir / f"{base_name}.htm"
        htm_path.write_text(decoded, encoding="utf-8")

        # Plain text
        text = strip_html_to_text(decoded)
        txt_path = output_dir / f"{base_name}.txt"
        txt_path.write_text(text, encoding="utf-8")

        # Clean markdown (financial tables)
        clean_md = html_to_markdown(htm_path)
        if clean_md:
            md_path = output_dir / f"{base_name}.clean.md"
            md_path.write_text(clean_md, encoding="utf-8")

    return True, ""


# ── Main Fetch Function ─────────────────────────────────────────────

def fetch(ticker: str, output_dir: str) -> AcquisitionResult:
    """Fetch SEC EDGAR filings for a ticker into output_dir.

    If output_dir already has files, skips download (cache).
    Returns AcquisitionResult with manifest data.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Cache: if filings already exist, skip
    existing = list(out_path.glob("SRC_*"))
    if existing:
        result = AcquisitionResult(
            ticker=ticker,
            source="sec_edgar",
            filings_downloaded=len(existing),
            filings_coverage_pct=100.0,
            notes="Using cached filings (directory not empty).",
        )
        return result

    client = SecClient()

    # Resolve CIK
    cik_result = resolve_cik(client, ticker)
    if cik_result is None:
        return AcquisitionResult(
            ticker=ticker,
            source="sec_edgar",
            notes=f"Ticker {ticker} not found in SEC EDGAR.",
            gaps=[f"CIK not found for {ticker}"],
        )

    cik_int, cik10 = cik_result

    # Collect all filings
    sub, records = collect_all_filings(client, cik10)

    # Select filings by type
    annual = [r for r in records if r.form in ANNUAL_FORMS][:ANNUAL_TARGET]
    quarterly = [r for r in records if r.form in PERIODIC_FORMS][
        :QUARTERLY_TARGET
    ]

    # Earnings 8-K: look for Exhibit 99
    earnings_8k: List[Tuple[FilingInfo, Optional[str]]] = []
    for rec in [r for r in records if r.form in {"8-K", "8-K/A"}][:160]:
        exhibit = find_exhibit_99(client, cik_int, rec)
        if exhibit:
            earnings_8k.append((rec, exhibit))
            if len(earnings_8k) >= EARNINGS_TARGET:
                break
        else:
            # Check if main doc has Item 2.02 signal
            try:
                doc_url = build_doc_url(cik_int, rec)
                resp = client.get(doc_url)
                low = resp.text.lower()
                if (
                    "item 2.02" in low
                    or "results of operations and financial condition" in low
                ):
                    earnings_8k.append((rec, None))
                    if len(earnings_8k) >= EARNINGS_TARGET:
                        break
            except Exception:
                pass

    # Count available
    avail_annual = min(
        len([r for r in records if r.form in ANNUAL_FORMS]), ANNUAL_TARGET
    )
    avail_quarterly = min(
        len([r for r in records if r.form in PERIODIC_FORMS]),
        QUARTERLY_TARGET,
    )
    avail_earnings = min(len(earnings_8k), EARNINGS_TARGET)

    # Download
    source_counter = 1
    downloaded = 0
    failed = 0

    def _download_record(
        rec: FilingInfo,
        form_label: str,
        period: str,
        doc_override: Optional[str] = None,
    ) -> None:
        nonlocal source_counter, downloaded, failed
        prefix = f"SRC_{source_counter:03d}"
        source_counter += 1
        doc_url = build_doc_url(cik_int, rec, doc_override)
        ok, err = _download_and_save(
            client, doc_url, out_path, prefix, form_label, period
        )
        if ok:
            downloaded += 1
        else:
            failed += 1

    for rec in annual:
        period = period_from_doc_or_date(
            rec.primary_doc, rec.filing_date, rec.form
        )
        _download_record(rec, rec.form.replace("/", "-"), period)

    for rec in quarterly:
        period = period_from_doc_or_date(
            rec.primary_doc, rec.filing_date, rec.form
        )
        _download_record(rec, rec.form.replace("/", "-"), period)

    for rec, exhibit in earnings_8k:
        period = rec.filing_date
        _download_record(rec, "8-K", period, exhibit)

    # Coverage
    total_expected = avail_annual + avail_quarterly + avail_earnings
    coverage_pct = (
        (downloaded / total_expected * 100.0) if total_expected > 0 else 0.0
    )

    annual_years = []
    for r in annual:
        m = re.search(r"20\d{2}", r.filing_date)
        if m:
            annual_years.append(int(m.group(0)))

    return AcquisitionResult(
        ticker=ticker,
        source="sec_edgar",
        cik=cik10,
        filings_downloaded=downloaded,
        filings_failed=failed,
        filings_coverage_pct=round(coverage_pct, 1),
        coverage={
            "annual": {
                "available_in_index": len(
                    [r for r in records if r.form in ANNUAL_FORMS]
                ),
                "target": ANNUAL_TARGET,
                "expected": avail_annual,
                "downloaded": len(annual),
                "years": sorted(set(annual_years)),
            },
            "quarterly": {
                "available_in_index": len(
                    [r for r in records if r.form in PERIODIC_FORMS]
                ),
                "target": QUARTERLY_TARGET,
                "expected": avail_quarterly,
                "downloaded": len(quarterly),
            },
            "earnings": {
                "available_in_index": avail_earnings,
                "target": EARNINGS_TARGET,
                "expected": avail_earnings,
                "downloaded": len(earnings_8k),
            },
        },
        notes=f"expected = min(available_in_index, target). All available filings processed.",
        download_date=dt.date.today().isoformat(),
    )
