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
import hashlib
import html as html_lib
import importlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore[assignment]


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
    "policy",
    "careers",
    "job",
    "linkedin",
    "twitter.com",
    "facebook.com",
)
LOCAL_IR_DISCOVERY_HINTS = (
    "investor",
    "financial",
    "results",
    "reports",
    "report",
    "announcement",
    "news",
    "regulatory",
    "finance kit",
    "financials",
)
LOCAL_FALLBACK_MAX_PAGES = 12
LOCAL_FALLBACK_MAX_LINKS_PER_PAGE = 80
LOCAL_FALLBACK_MAX_TOTAL = 12
LOCAL_FALLBACK_PER_TYPE = {
    "ANNUAL_REPORT": 4,
    "INTERIM_REPORT": 4,
    "REGULATORY_FILING": 4,
    "IR_NEWS": 3,
    "_default": 2,
}
DATE_DEBUG = os.getenv("SEC_FETCHER_DATE_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
_NAV_HINTS = (
    "search home",
    "cookie",
    "privacy policy",
    "investor relations",
    "latest news",
    "products",
    "smartpos",
    "newsletter",
)
_FIN_HINTS = (
    "revenue",
    "profit",
    "income",
    "cash flow",
    "assets",
    "liabilities",
    "equity",
    "ebit",
    "ebitda",
    "dividend",
    "capex",
    "hk$",
    "usd",
    "rmb",
    "cny",
    "%",
)
TEXT_SAMPLE_MAX_CHARS = 12_000
LOCAL_ANNUAL_MIN_TEXT_CHARS = 1_500
LOCAL_ANNUAL_MIN_SIGNAL_HITS = 2
LOCAL_ANNUAL_LONG_SAMPLE_CHARS = 8_000
LOCAL_EVENT_REGISTRATION_HINTS_STRONG = (
    "engagestream",
    "register",
    "registration",
    "signup",
    "webcast",
)
LOCAL_UMBRACO_MAX_PAGES = 6
LOCAL_UMBRACO_PAGE_SIZE = 50
LOCAL_UMBRACO_TIMEOUT_SECONDS = 5


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

    def get(
        self,
        url: str,
        *,
        binary: bool = False,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> requests.Response:
        request_headers = headers or HEADERS
        request_timeout = timeout or TIMEOUT
        self._throttle()
        try:
            resp = self._session.get(
                url,
                headers=request_headers,
                params=params,
                timeout=request_timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
        except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", 0)
            host = urlparse(url).netloc.lower()
            if status in (429, 500, 502, 503, 504) or isinstance(exc, requests.exceptions.ConnectionError):
                time.sleep(3)
                self._throttle()
                resp = self._session.get(
                    url,
                    headers=request_headers,
                    params=params,
                    timeout=request_timeout,
                    allow_redirects=True,
                )
                resp.raise_for_status()
            elif status == 403 and "sec.gov" not in host:
                # Some IR portals block bot-like User-Agents; use a browser UA
                # only for non-SEC domains to keep SEC requests policy-compliant.
                time.sleep(1)
                self._throttle()
                fallback_headers = ALT_HEADERS if headers is None else headers
                resp = self._session.get(
                    url,
                    headers=fallback_headers,
                    params=params,
                    timeout=request_timeout,
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
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return None

    for m in re.finditer(r"\b((?:19|20)\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", value):
        try:
            y, mo, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return dt.date(y, mo, day).isoformat()
        except ValueError:
            continue

    for m in re.finditer(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)", value):
        try:
            y, mo, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return dt.date(y, mo, day).isoformat()
        except ValueError:
            continue

    for pattern in (r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", r"(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})"):
        m = re.search(pattern, value, flags=re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1).strip()
        normalized = raw.title()
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
            try:
                return dt.datetime.strptime(normalized, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _date_debug(msg: str) -> None:
    if DATE_DEBUG:
        print(f"[sec_fetcher][date-debug] {msg}", file=sys.stderr)


def parse_year_hint(text: str) -> Optional[int]:
    low = re.sub(r"\s+", " ", str(text or "")).lower()
    if not low:
        return None
    if not any(k in low for k in ("annual", "interim", "year", "fy", "report", "results")):
        return None
    years = [int(m.group(0)) for m in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", low)]
    if not years:
        return None
    return max(years)


def _normalize_text_for_hash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _content_hash(text: str) -> str:
    normalized = _normalize_text_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _extract_largest_text_block(soup: BeautifulSoup) -> str:
    candidates = soup.find_all(["main", "article", "section", "div"])
    best = ""
    for node in candidates:
        txt = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if len(txt) > len(best):
            best = txt
    return best


def strip_html_boilerplate(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "link", "nav", "header", "footer", "aside"]):
        tag.decompose()

    regex = re.compile(r"(menu|navbar|sidebar|cookie|breadcrumb)", re.IGNORECASE)
    for node in soup.find_all(attrs={"class": regex}):
        node.decompose()
    for node in soup.find_all(attrs={"id": regex}):
        node.decompose()

    text = strip_html_to_text(str(soup)).strip()
    if len(text) >= 600:
        return str(soup)

    # fallback: keep only the largest textual block when global text is too noisy/thin
    block = _extract_largest_text_block(soup)
    if block and len(block) > len(text):
        shell = BeautifulSoup("<html><body></body></html>", "html.parser")
        shell.body.string = block  # type: ignore[union-attr]
        return str(shell)
    return str(soup)


def _extract_pattern_date_from_pdf_text(text: str) -> Optional[str]:
    probe = re.sub(r"\s+", " ", str(text or "")).strip()
    if not probe:
        return None
    patterns = (
        r"(?:for the|for)\s+year\s+ended\s+([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
        r"year\s+ended\s+([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
        r"for the period ended\s+([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
        r"(?:for the|for)\s+year\s+ended\s+((?:19|20)\d{2}-\d{2}-\d{2})",
    )
    for pat in patterns:
        m = re.search(pat, probe, flags=re.IGNORECASE)
        if not m:
            continue
        parsed = parse_date_loose(m.group(1))
        if parsed:
            return parsed
    return None


def _is_low_financial_density(text: str, window: int = 2000) -> bool:
    sample = _normalize_text_for_hash(text)[:window]
    if not sample:
        return True
    fin_hits = sum(1 for k in _FIN_HINTS if k in sample)
    num_hits = len(re.findall(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?%\b", sample))
    return fin_hits < 2 and num_hits < 2


def is_navigation_like_source(title: str, cleaned_text: str, url: str) -> bool:
    low_url = (url or "").lower()
    is_pdf = low_url.endswith(".pdf")
    if is_pdf:
        return False
    sample = _normalize_text_for_hash(cleaned_text)[:2500]
    title_low = _normalize_text_for_hash(title)
    nav_hits = sum(1 for k in _NAV_HINTS if k in sample or k in title_low or k in low_url)
    index_like_url = any(p in low_url for p in (
        "/investor-relations",
        "/latest-news",
        "/announcements",
        "/news",
        "/finance-kit",
        "/publications",
    ))
    if "search home android smartpos" in sample:
        return True
    if index_like_url and _is_low_financial_density(sample):
        return True
    return nav_hits >= 4 and _is_low_financial_density(sample)


def _prefer_new_candidate(prev: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    prev_score = int(prev.get("score", 0))
    new_score = int(candidate.get("score", 0))
    if new_score > prev_score:
        # protect a date-carrying candidate from a date-less overwrite unless score delta is meaningful
        if prev.get("fecha_publicacion") and not candidate.get("fecha_publicacion"):
            return (new_score - prev_score) >= 2
        return True
    if new_score < prev_score:
        return False
    prev_has_date = bool(prev.get("fecha_publicacion"))
    new_has_date = bool(candidate.get("fecha_publicacion"))
    if new_has_date and not prev_has_date:
        return True
    if prev_has_date and not new_has_date:
        return False
    return float(candidate.get("selection_score", 0.0)) > float(prev.get("selection_score", 0.0))


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


def _derive_local_ir_roots(base_url: str) -> List[str]:
    parsed = urlparse(base_url)
    host_root = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    path = parsed.path.strip("/")
    segments = [seg for seg in path.split("/") if seg]
    original_segments = list(segments)

    # Trim homepage tails that produce 404 when appending financial suffixes.
    while segments and segments[-1].lower() in {
        "investors-homepage",
        "investor-homepage",
        "homepage",
        "home",
    }:
        segments.pop()

    locale = segments[0].lower() if segments and re.fullmatch(r"[a-z]{2}-[a-z]{2}", segments[0].lower()) else None
    investor_idx = next(
        (idx for idx, seg in enumerate(segments) if seg.lower() in {"investors", "investor-relations"}),
        None,
    )

    has_homepage_tail = bool(original_segments) and original_segments[-1].lower() in {
        "investors-homepage",
        "investor-homepage",
        "homepage",
        "home",
    }

    roots: List[str] = []
    if locale and investor_idx is not None:
        roots.append(f"{host_root}/{locale}/{segments[investor_idx]}")
    elif investor_idx is not None:
        roots.append(f"{host_root}/{segments[investor_idx]}")
    if segments:
        roots.append(f"{host_root}/{'/'.join(segments)}")
    if locale:
        roots.append(f"{host_root}/{locale}")
    if locale:
        roots.append(f"{host_root}/{locale}/investors")
    if not has_homepage_tail:
        roots.append(base_url.rstrip("/"))
    roots.append(host_root)

    deduped: List[str] = []
    seen = set()
    for root in roots:
        cleaned = normalize_web_ir(root)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def build_local_ir_pages(web_ir: Optional[str]) -> List[str]:
    base = normalize_web_ir(web_ir)
    if not base:
        return []
    suffixes = (
        "/publications-and-events/financial-publications",
        "/publications-and-events/regulated-information",
        "/publications-and-events/press-releases",
        "/reports-results-and-presentations",
        "/financial-results",
        "/results",
        "/finance-kit",
        "/financial-reports",
        "/annual-reports",
        "/investor-relations",
        "/investors",
        "/company-announcements",
        "/announcements",
        "/news-events",
        "/news",
        "/publications",
    )
    pages: List[str] = [base]
    homepage_tail_re = re.compile(r"/(?:investors-homepage|investor-homepage|homepage|home)$")
    for ir_root in _derive_local_ir_roots(base):
        pages.append(ir_root)
        low_path = (urlparse(ir_root).path or "").rstrip("/").lower()
        if homepage_tail_re.search(low_path):
            continue
        for suffix in suffixes:
            pages.append(urljoin(ir_root + "/", suffix.lstrip("/")))
    return list(dict.fromkeys(pages))


def _is_same_domain(base_url: str, candidate_url: str) -> bool:
    base_host = urlparse(base_url).netloc.lower()
    cand_host = urlparse(candidate_url).netloc.lower()
    return bool(base_host and cand_host and base_host == cand_host)


def discover_ir_subpages(
    html: str,
    base_url: str,
    exchange: Optional[str],
    max_links: int = LOCAL_FALLBACK_MAX_LINKS_PER_PAGE,
) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    ex = (exchange or "").upper()
    hints = set(LOCAL_IR_DISCOVERY_HINTS)
    hints.update(LOCAL_FILING_KEYWORDS_BY_EXCHANGE.get(ex, ()))

    out: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if not full_url.startswith(("http://", "https://")):
            continue
        if not _is_same_domain(base_url, full_url):
            continue

        low_url = full_url.lower()
        if any(neg in low_url for neg in LOCAL_FILING_NEGATIVE):
            continue
        if low_url.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".ppt", ".pptx")):
            continue

        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        context_norm = re.sub(r"[-_/]+", " ", f"{text} {low_url}".lower())
        if not any(h in context_norm for h in hints):
            continue

        if full_url in seen:
            continue
        seen.add(full_url)
        out.append(full_url)
        if len(out) >= max_links:
            break
    return out


def _classify_local_filing_type(title: str, doc_url: str, snippet: str) -> str:
    _ctx = f"{title.lower()} {doc_url.lower()} {snippet.lower()}"
    _url_low = doc_url.lower()
    _is_media_url = (
        "youtube.com" in _url_low
        or "youtu.be" in _url_low
        or "vimeo.com" in _url_low
        or "watch?v=" in _url_low
        or _url_low.endswith((".mp4", ".mov", ".avi", ".m3u8"))
    )
    if _is_media_url:
        return "OTHER"

    has_press_release = any(
        w in _ctx
        for w in (
            "press release",
            "press-release",
            "news release",
            "earnings release",
            "communique",
            "communiqué",
        )
    )
    has_urd_strong = bool(
        re.search(r"\burd\b", _ctx)
        or "universal registration document" in _ctx
        or "document d'enregistrement universel" in _ctx
    )
    has_annual_doc_signal = any(
        w in _ctx
        for w in (
            "annual report",
            "registration document",
            "integrated report",
            "integrated annual report",
            "rapport annuel",
        )
    ) or has_urd_strong

    # Press-releases mentioning "annual results" are not annual reports.
    if has_press_release:
        if "results" in _ctx or "financial" in _ctx or "earnings" in _ctx:
            return "REGULATORY_FILING"
        return "IR_NEWS"

    if has_annual_doc_signal:
        return "ANNUAL_REPORT"
    if any(w in _ctx for w in ("interim", "half year", "h1 ", "h2 ", "half-year")):
        return "INTERIM_REPORT"
    if "rns" in _ctx or "regulatory news" in _ctx or "announcement" in _ctx:
        return "IR_NEWS"
    if any(w in _ctx for w in ("results", "financial")):
        return "REGULATORY_FILING"
    return "OTHER"


def _resolve_local_candidate_date(
    anchor_text: str,
    row_text: str,
    full_url: str,
) -> Tuple[Optional[str], str, bool]:
    anchor_dbg = re.sub(r"\s+", " ", str(anchor_text or "")).strip()
    row_dbg = re.sub(r"\s+", " ", str(row_text or "")).strip()
    _date_debug(
        "_resolve_local_candidate_date "
        f"anchor='{anchor_dbg[:100]}' row='{row_dbg[:120]}' url='{full_url[:180]}'"
    )
    for source_name, chunk in (
        ("context", f"{anchor_text} {row_text}"),
        ("url", full_url),
    ):
        date_guess = parse_date_loose(chunk)
        if date_guess:
            estimated = source_name != "context"
            _date_debug(f"  -> parsed date {date_guess} from {source_name}")
            return date_guess, source_name, estimated
    for source_name, chunk in (
        ("title_year", f"{anchor_text} {row_text}"),
        ("url_year", full_url),
    ):
        year_hint = parse_year_hint(chunk)
        if year_hint:
            inferred = f"{int(year_hint):04d}-12-31"
            _date_debug(f"  -> inferred year-only date {inferred} from {source_name}")
            return inferred, source_name, True
    _date_debug("  -> no date inferred")
    return None, "unknown", True


def _extract_date_from_html_document(html: str, doc_url: str) -> Tuple[Optional[str], str]:
    soup = BeautifulSoup(html, "html.parser")
    meta_selectors = (
        ("html_meta", {"property": "article:published_time"}),
        ("html_meta", {"name": "date"}),
        ("html_meta", {"name": "publishdate"}),
        ("html_meta", {"name": "publication_date"}),
        ("html_meta", {"name": "dc.date"}),
    )
    for source_name, attrs in meta_selectors:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            parsed = parse_date_loose(str(tag.get("content")))
            if parsed:
                return parsed, source_name

    for t in soup.find_all("time"):
        text = str(t.get("datetime") or t.get_text(" ", strip=True) or "")
        parsed = parse_date_loose(text)
        if parsed:
            return parsed, "html_time_tag"

    if soup.title and soup.title.get_text():
        parsed = parse_date_loose(soup.title.get_text(" ", strip=True))
        if parsed:
            return parsed, "html_title"

    parsed = parse_date_loose(doc_url)
    if parsed:
        return parsed, "url"
    return None, "unknown"


def _local_event_registration_penalty(context_norm: str, full_url: str) -> float:
    """Soft-penalize event/registration links so annual reports rank higher."""
    ctx = f"{context_norm} {full_url.lower()}"
    penalty = 0.0
    if any(hint in ctx for hint in LOCAL_EVENT_REGISTRATION_HINTS_STRONG):
        penalty -= 3.0
    if re.search(r"\bevents?\b", ctx):
        penalty -= 1.0
    return penalty


def _clean_embedded_pdf_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    cleaned = str(raw_url).strip().strip("\"'`")
    cleaned = html_lib.unescape(cleaned)
    cleaned = cleaned.replace("\\/", "/")
    cleaned = re.sub(r"\\u0*2f", "/", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\\x2f", "/", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("\\\\", "\\")
    cleaned = cleaned.strip().strip("\"'`")
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    return cleaned


def _extract_embedded_title(context_window: str, full_url: str) -> str:
    patterns = (
        r'data-gtm-elem-text\\?"?\s*[:=]\s*["\']([^"\']{6,220})["\']',
        r'"name"\s*:\s*\{\s*"Value"\s*:\s*"([^"]{6,220})"',
        r'"name"\s*:\s*\{\s*"value"\s*:\s*"([^"]{6,220})"',
        r'"title"\s*:\s*"([^"]{6,220})"',
    )
    for pat in patterns:
        m = re.search(pat, context_window, flags=re.IGNORECASE)
        if not m:
            continue
        candidate = re.sub(r"\s+", " ", html_lib.unescape(m.group(1))).strip()
        if candidate:
            return candidate[:240]
    basename = unquote(Path(urlparse(full_url).path).name).replace("+", " ").strip()
    return basename[:240] or "Local filing"


def _extract_embedded_pdf_candidates(
    html: str,
    base_url: str,
    exchange: Optional[str],
) -> List[Dict[str, Any]]:
    ex = (exchange or "").upper()
    kws = set(LOCAL_FILING_KEYWORDS_COMMON)
    kws.update(LOCAL_FILING_KEYWORDS_BY_EXCHANGE.get(ex, ()))

    positive_plain_hints = (
        "annual",
        "results",
        "registration document",
        "universal registration document",
        "integrated report",
        "interim",
        "financial",
        "urd",
    )
    negative_plain_hints = ("privacy", "cookie", "terms", "policy")
    event_register_re = re.compile(r"(webcast|event)[\w\s:/-]{0,40}register|signup", re.IGNORECASE)
    period_hint_re = re.compile(r"\b(q[1-4]|h[12])\b", re.IGNORECASE)

    pattern = re.compile(
        r"""(?ix)
        (?:
            (?P<absolute>https?://[^\s"'<>\\]+?\.pdf(?:\?[^\s"'<>\\]*)?)
            |
            (?P<relative>(?:\\?/)?media/[^\s"'<>\\]+?\.pdf(?:\?[^\s"'<>\\]*)?)
            |
            (?P<slash_relative>\\?/media/[^\s"'<>\\]+?\.pdf(?:\?[^\s"'<>\\]*)?)
        )
        """
    )

    by_url: Dict[str, Dict[str, Any]] = {}
    for match in pattern.finditer(html):
        raw_url = match.group("absolute") or match.group("relative") or match.group("slash_relative") or ""
        cleaned_url = _clean_embedded_pdf_url(raw_url)
        if not cleaned_url:
            continue

        if not cleaned_url.startswith(("http://", "https://", "/")):
            continue
        if cleaned_url.startswith("media/"):
            cleaned_url = f"/{cleaned_url}"
        full_url = urljoin(base_url, cleaned_url)
        if not full_url.lower().startswith(("http://", "https://")):
            continue
        if not full_url.lower().endswith(".pdf") and ".pdf?" not in full_url.lower():
            continue

        start, end = match.span()
        left = max(0, start - 180)
        right = min(len(html), end + 180)
        context_window = html[left:right]
        context_window = html_lib.unescape(context_window.replace("\\/", "/"))
        context_window = re.sub(r"\s+", " ", context_window).strip()
        context_low = context_window.lower()
        context_norm = re.sub(r"[-_/]+", " ", context_low)
        merged_ctx = f"{full_url.lower()} {context_low}"

        if any(neg in merged_ctx for neg in negative_plain_hints):
            continue
        if event_register_re.search(merged_ctx):
            continue

        title = _extract_embedded_title(context_window, full_url)
        url_title_ctx = f"{full_url.lower()} {title.lower()}"
        has_positive = any(pos in url_title_ctx for pos in positive_plain_hints) or bool(
            period_hint_re.search(url_title_ctx)
        )
        if not has_positive:
            continue

        date_guess, date_source, date_estimated = _resolve_local_candidate_date(
            title,
            context_window,
            full_url,
        )
        basename_hint = unquote(Path(urlparse(full_url).path).name).replace("+", " ")
        filing_type = _classify_local_filing_type(title, full_url, basename_hint)

        score = 1  # Base score for embedded PDF match.
        kw_hits = sum(1 for kw in kws if kw in context_norm or kw in url_title_ctx)
        score += min(3, kw_hits)
        if "annual" in url_title_ctx or "integrated report" in url_title_ctx or "urd" in url_title_ctx:
            score += 2
        if "interim" in url_title_ctx or re.search(r"\b(h1|h2|q[1-4])\b", url_title_ctx):
            score += 2

        selection_score = float(score)
        if filing_type == "ANNUAL_REPORT":
            selection_score += 4.0
        elif filing_type == "INTERIM_REPORT":
            selection_score += 3.0
        elif filing_type == "REGULATORY_FILING":
            selection_score += 2.0
        elif filing_type == "IR_NEWS":
            selection_score += 1.0
        if date_guess:
            selection_score += 0.5
        selection_score += _local_event_registration_penalty(context_norm, full_url)

        snippet = context_window[:280] if context_window else title[:280]
        candidate = {
            "url": full_url,
            "titulo": title[:240],
            "score": score,
            "fecha_publicacion": date_guess,
            "fecha_source": date_source,
            "fecha_publicacion_estimated": date_estimated,
            "snippet": snippet,
            "tipo_guess": filing_type,
            "selection_score": selection_score,
            "discovered_via": "embedded_pdf",
        }
        prev = by_url.get(full_url)
        if prev is None or _prefer_new_candidate(prev, candidate):
            by_url[full_url] = candidate

    return list(by_url.values())


def _extract_umbraco_modules(html: str) -> List[Dict[str, str]]:
    modules: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    patterns = (
        re.compile(
            r"new\s+filesDownloadList\(\s*['\"](?P<hash>[^'\"]+)['\"]\s*,\s*['\"](?P<node>[^'\"]+)['\"]",
            re.IGNORECASE,
        ),
        re.compile(
            r"filesDownloadList\(\s*['\"](?P<hash>[^'\"]+)['\"]\s*,\s*['\"](?P<node>[^'\"]+)['\"]",
            re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        for match in pattern.finditer(html or ""):
            hash_code = str(match.group("hash") or "").strip()
            node_id = str(match.group("node") or "").strip()
            if not hash_code or not node_id:
                continue
            key = (hash_code, node_id)
            if key in seen:
                continue
            seen.add(key)
            modules.append({"hash": hash_code, "node_id": node_id})
    return modules


def _infer_umbraco_cultures(base_url: str, country: Optional[str]) -> List[str]:
    path = (urlparse(base_url).path or "").lower()
    cultures: List[str] = []
    match = re.search(r"/([a-z]{2}-[a-z]{2})(?:/|$)", path)
    if match:
        cultures.append(match.group(1))
    if str(country or "").upper() == "FR":
        cultures.append("fr-fr")
    cultures.append("en-us")

    deduped: List[str] = []
    seen = set()
    for culture in cultures:
        if culture in seen:
            continue
        seen.add(culture)
        deduped.append(culture)
    return deduped


def _is_umbraco_row_financial_candidate(title: str, file_url: str) -> bool:
    merged = f"{title.lower()} {file_url.lower()}"
    if any(neg in merged for neg in ("privacy", "cookie", "terms", "policy")):
        return False
    if any(bad in merged for bad in ("register", "webcast replay", "signup", "event replay", "event register")):
        return False
    if ".pdf" not in file_url.lower():
        return False
    if re.search(r"\b(q[1-4]|h[12])\b", merged):
        return True
    return any(
        pos in merged
        for pos in (
            "annual",
            "results",
            "registration document",
            "universal registration document",
            "urd",
            "integrated report",
            "interim",
            "financial",
            "half-year",
            "half year",
        )
    )


def _rows_to_local_candidates(
    rows: List[Dict[str, Any]],
    page_url: str,
    exchange: Optional[str],
    culture: str,
) -> List[Dict[str, Any]]:
    ex = (exchange or "").upper()
    kws = set(LOCAL_FILING_KEYWORDS_COMMON)
    kws.update(LOCAL_FILING_KEYWORDS_BY_EXCHANGE.get(ex, ()))

    by_url: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        title = re.sub(r"\s+", " ", str(row.get("title") or "Local filing")).strip()
        file_raw = str(row.get("file") or "").strip()
        if not file_raw:
            continue
        full_url = urljoin(page_url, _clean_embedded_pdf_url(file_raw))
        if not full_url.startswith(("http://", "https://")):
            continue
        if not _is_umbraco_row_financial_candidate(title, full_url):
            continue

        snippet = title[:280]
        date_guess, date_source, date_estimated = _resolve_local_candidate_date(title, title, full_url)
        filing_type = _classify_local_filing_type(title, full_url, snippet)
        context_norm = re.sub(r"[-_/]+", " ", f"{title.lower()} {full_url.lower()}")

        score = 1
        score += min(3, sum(1 for kw in kws if kw in context_norm))
        if filing_type == "ANNUAL_REPORT":
            score += 3
        elif filing_type == "INTERIM_REPORT":
            score += 2
        elif filing_type == "REGULATORY_FILING":
            score += 1

        selection_score = float(score)
        if date_guess:
            selection_score += 0.5
        selection_score += _local_event_registration_penalty(context_norm, full_url)

        candidate = {
            "url": full_url,
            "titulo": title[:240],
            "score": score,
            "fecha_publicacion": date_guess,
            "fecha_source": date_source,
            "fecha_publicacion_estimated": date_estimated,
            "snippet": snippet,
            "tipo_guess": filing_type,
            "selection_score": selection_score,
            "discovered_via": "umbraco_api",
            "umbraco_culture": culture,
        }
        prev = by_url.get(full_url)
        if prev is None or _prefer_new_candidate(prev, candidate):
            by_url[full_url] = candidate
    return list(by_url.values())


def _collect_umbraco_candidates(
    *,
    client: SecClient,
    html: str,
    page_url: str,
    exchange: Optional[str],
    country: Optional[str],
) -> tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
    modules = _extract_umbraco_modules(html)
    metrics = {
        "modules_detected": len(modules),
        "rows_collected": 0,
        "candidates_added": 0,
        "api_errors": 0,
    }
    errors: List[str] = []
    if not modules:
        return [], metrics, errors

    parsed = urlparse(page_url)
    host_root = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    endpoint_candidates = (
        f"{host_root}/Umbraco/Api/FileDownloadList/GetFileDownload",
        f"{host_root}/Api/FileDownloadList/GetFileDownload",
    )
    cultures = _infer_umbraco_cultures(page_url, country)
    all_candidates: List[Dict[str, Any]] = []
    seen_url: set[str] = set()
    seen_payload_warnings: set[tuple[str, str, str]] = set()

    for module in modules:
        node_id = module.get("node_id", "")
        hash_code = module.get("hash", "")
        if not node_id:
            continue
        module_rows: List[Dict[str, Any]] = []
        module_ok = False
        for culture in cultures:
            culture_rows: List[Dict[str, Any]] = []
            for endpoint in endpoint_candidates:
                endpoint_ok = False
                for page_num in range(1, LOCAL_UMBRACO_MAX_PAGES + 1):
                    params = {
                        "nodeId": node_id,
                        "hash": hash_code,
                        "type": "",
                        "year": "",
                        "page": page_num,
                        "pageSize": LOCAL_UMBRACO_PAGE_SIZE,
                        "culture": culture,
                    }
                    try:
                        response = client.get(
                            endpoint,
                            params=params,
                            timeout=LOCAL_UMBRACO_TIMEOUT_SECONDS,
                        )
                        payload = response.json()
                    except Exception as exc:
                        metrics["api_errors"] += 1
                        errors.append(
                            f"Umbraco API error node={node_id} culture={culture} endpoint={endpoint}: {exc}"
                        )
                        break

                    rows = None
                    if isinstance(payload, dict):
                        for key in ("resultado", "results", "items", "rows", "data"):
                            val = payload.get(key)
                            if isinstance(val, list):
                                rows = val
                                break
                    if rows is None:
                        warn_key = (node_id, culture, endpoint)
                        if warn_key not in seen_payload_warnings:
                            seen_payload_warnings.add(warn_key)
                            keys = list(payload.keys())[:6] if isinstance(payload, dict) else []
                            errors.append(
                                "Umbraco payload without list rows "
                                f"node={node_id} culture={culture} endpoint={endpoint} keys={keys}"
                            )
                        break
                    if not rows:
                        break

                    endpoint_ok = True
                    culture_rows.extend(rows)
                    if len(rows) < LOCAL_UMBRACO_PAGE_SIZE:
                        break
                if endpoint_ok:
                    module_ok = True
                    break
            if culture_rows:
                for candidate in _rows_to_local_candidates(culture_rows, page_url, exchange, culture):
                    url = str(candidate.get("url") or "")
                    if not url or url in seen_url:
                        continue
                    seen_url.add(url)
                    all_candidates.append(candidate)
                module_rows.extend(culture_rows)
                if len(culture_rows) >= 3:
                    break
        if module_ok:
            metrics["rows_collected"] += len(module_rows)

    metrics["candidates_added"] = len(all_candidates)
    return all_candidates, metrics, errors


def _financial_signal_hits(text: str) -> Tuple[int, List[str]]:
    if not text:
        return 0, []
    normalized = re.sub(r"\s+", " ", text.lower())
    hits = sorted({hint for hint in _FIN_HINTS if hint in normalized})
    return len(hits), hits


def _classify_local_annual_extractability(
    *,
    tipo: str,
    extraction_status: str,
    extraction_reason: str,
    text_chars: int,
    text_sample: str,
) -> Tuple[str, str, Dict[str, Any]]:
    """Downgrade low-quality local annual fallback sources to non-extractable."""
    tipo_up = str(tipo or "").upper().replace(" ", "")
    is_local_annual = tipo_up in {"ANNUAL_REPORT", "10-K", "10K", "20-F", "20F", "40-F", "40F"}
    if not is_local_annual or extraction_status != "OK":
        return extraction_status, extraction_reason, {}

    signal_hits_count, signal_hits = _financial_signal_hits(text_sample)
    sample_len = len(text_sample or "")
    sample_long_enough = sample_len >= LOCAL_ANNUAL_LONG_SAMPLE_CHARS

    if text_chars < LOCAL_ANNUAL_MIN_TEXT_CHARS:
        reason = (
            "Local annual fallback downgraded: extracted text too short "
            f"({text_chars} < {LOCAL_ANNUAL_MIN_TEXT_CHARS})."
        )
        merged_reason = f"{extraction_reason} {reason}".strip()
        return "NON_EXTRACTABLE_LOW_TEXT_ANNUAL", merged_reason, {
            "rejected_low_quality": True,
            "reject_reason": "LOW_TEXT_ANNUAL",
            "signal_hits": signal_hits,
            "signal_hits_count": signal_hits_count,
            "sample_len": sample_len,
            "sample_long_enough": sample_long_enough,
        }

    if signal_hits_count < LOCAL_ANNUAL_MIN_SIGNAL_HITS and not sample_long_enough:
        reason = (
            "Local annual fallback downgraded: insufficient financial signal "
            f"(hits={signal_hits_count} < {LOCAL_ANNUAL_MIN_SIGNAL_HITS}; sample_len={sample_len})."
        )
        if signal_hits:
            reason = f"{reason} matched={','.join(signal_hits[:8])}."
        merged_reason = f"{extraction_reason} {reason}".strip()
        return "NON_EXTRACTABLE_LOW_SIGNAL_ANNUAL", merged_reason, {
            "rejected_low_quality": True,
            "reject_reason": "LOW_SIGNAL_ANNUAL",
            "signal_hits": signal_hits,
            "signal_hits_count": signal_hits_count,
            "sample_len": sample_len,
            "sample_long_enough": sample_long_enough,
        }

    return extraction_status, extraction_reason, {
        "rejected_low_quality": False,
        "signal_hits": signal_hits,
        "signal_hits_count": signal_hits_count,
        "sample_len": sample_len,
        "sample_long_enough": sample_long_enough,
    }


def _select_local_fallback_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda x: (
            float(x.get("selection_score", 0.0)),
            x.get("fecha_publicacion") or "0000-00-00",
        ),
        reverse=True,
    )

    selected: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    for cand in ordered:
        ctype = str(cand.get("tipo_guess") or "OTHER").upper()
        limit = int(LOCAL_FALLBACK_PER_TYPE.get(ctype, LOCAL_FALLBACK_PER_TYPE["_default"]))
        if counts.get(ctype, 0) >= limit:
            continue
        selected.append(cand)
        counts[ctype] = counts.get(ctype, 0) + 1
        if len(selected) >= LOCAL_FALLBACK_MAX_TOTAL:
            break
    return selected


def extract_local_filing_candidates(
    html: str,
    base_url: str,
    exchange: Optional[str],
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    ex = (exchange or "").upper()
    kws = set(LOCAL_FILING_KEYWORDS_COMMON)
    kws.update(LOCAL_FILING_KEYWORDS_BY_EXCHANGE.get(ex, ()))
    event_register_re = re.compile(
        r"(webcast|event)[\w\s:/-]{0,40}register|engagestream|signup|/register(?:$|[/?#])",
        re.IGNORECASE,
    )

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
        context_raw = f"{text} {row_text} {full_url}"
        context = context_raw.lower()
        # Normalize common URL/slug separators so keyword matching catches
        # forms like "annual-report" / "interim_report".
        context_norm = re.sub(r"[-_/]+", " ", context)

        if any(neg in context for neg in LOCAL_FILING_NEGATIVE):
            continue
        if event_register_re.search(f"{context} {full_url.lower()}"):
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
        date_guess, date_source, date_estimated = _resolve_local_candidate_date(text, row_text, full_url)
        filing_type = _classify_local_filing_type(title, full_url, row_text)
        selection_score = float(score)
        if filing_type == "ANNUAL_REPORT":
            selection_score += 4.0
        elif filing_type == "INTERIM_REPORT":
            selection_score += 3.0
        elif filing_type == "REGULATORY_FILING":
            selection_score += 2.0
        elif filing_type == "IR_NEWS":
            selection_score += 1.0
        if date_guess:
            selection_score += 0.5
        selection_score += _local_event_registration_penalty(context_norm, full_url)

        candidate = {
            "url": full_url,
            "titulo": title[:240],
            "score": score,
            "fecha_publicacion": date_guess,
            "fecha_source": date_source,
            "fecha_publicacion_estimated": date_estimated,
            "snippet": row_text[:280] if row_text else title[:280],
            "tipo_guess": filing_type,
            "selection_score": selection_score,
        }
        prev = by_url.get(full_url)
        if prev is None:
            by_url[full_url] = candidate
            continue
        if _prefer_new_candidate(prev, candidate):
            if prev.get("fecha_publicacion") and not candidate.get("fecha_publicacion"):
                _date_debug(
                    f"candidate replacement preserved? prev had date={prev.get('fecha_publicacion')} "
                    f"new had none (url={full_url})"
                )
            by_url[full_url] = candidate

    for candidate in _extract_embedded_pdf_candidates(html, base_url, exchange):
        full_url = str(candidate.get("url") or "")
        if not full_url:
            continue
        prev = by_url.get(full_url)
        if prev is None:
            by_url[full_url] = candidate
            continue
        if _prefer_new_candidate(prev, candidate):
            by_url[full_url] = candidate

    candidates = sorted(
        by_url.values(),
        key=lambda x: (
            float(x.get("selection_score", 0.0)),
            x.get("fecha_publicacion") or "0000-00-00",
        ),
        reverse=True,
    )
    return candidates[:20]


def strip_html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha / max(1, len(text))


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


def get_doc_text(client: SecClient, url: str) -> Tuple[bytes, str, Dict[str, Any]]:
    resp = client.get(url, binary=True)
    content = resp.content
    ctype = resp.headers.get("Content-Type", "").lower()
    if "application/pdf" in ctype or url.lower().endswith(".pdf"):
        if PdfReader is None:
            return content, "", {
                "extraction_status": "NON_EXTRACTABLE_PDF",
                "extraction_reason": "pypdf no disponible para extraer texto embebido de PDF.",
                "extractor": "none",
                "text_chars": 0,
                "inferred_date": None,
                "date_source": "unknown",
                "text_sample": "",
                "content_hash": "",
            }
        try:
            reader = PdfReader(BytesIO(content))
            chunks: List[str] = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
                page_text = re.sub(r"[ \t]+", " ", page_text)
                page_text = re.sub(r"\n{3,}", "\n\n", page_text).strip()
                if page_text:
                    chunks.append(page_text)
            text = "\n\n".join(chunks).strip()
            text_probe = text[:20000]
            inferred_date = None
            date_source = "unknown"
            metadata = getattr(reader, "metadata", None) or {}
            for key in ("/ModDate", "/CreationDate", "ModDate", "CreationDate"):
                raw_date = metadata.get(key) if hasattr(metadata, "get") else None
                parsed = parse_date_loose(str(raw_date or ""))
                if parsed:
                    inferred_date = parsed
                    date_source = "pdf_metadata"
                    break
            if inferred_date is None:
                parsed = _extract_pattern_date_from_pdf_text(text_probe)
                if parsed:
                    inferred_date = parsed
                    date_source = "pdf_text_pattern"
            if inferred_date is None:
                parsed = parse_date_loose(text_probe)
                if parsed:
                    inferred_date = parsed
                    date_source = "pdf_text_general"
        except Exception as exc:
            return content, "", {
                "extraction_status": "NON_EXTRACTABLE_PDF",
                "extraction_reason": f"Error extrayendo PDF con pypdf: {exc}",
                "extractor": "pypdf",
                "text_chars": 0,
                "inferred_date": None,
                "date_source": "unknown",
                "text_sample": "",
                "content_hash": "",
            }
        text_chars = len(text)
        alpha_ratio = _alpha_ratio(text)
        content_hash = _content_hash(text)
        text_sample = text[:TEXT_SAMPLE_MAX_CHARS]
        if text_chars >= 500 and alpha_ratio >= 0.30:
            reason = ""
            if text_chars < 10000:
                reason = (
                    f"Texto PDF extraído pero bajo para filing anual "
                    f"({text_chars} chars, alpha_ratio={alpha_ratio:.2f})."
                )
            return content, text, {
                "extraction_status": "OK",
                "extraction_reason": reason,
                "extractor": "pypdf",
                "text_chars": text_chars,
                "inferred_date": inferred_date,
                "date_source": date_source,
                "text_sample": text_sample,
                "content_hash": content_hash,
            }
        return content, text, {
            "extraction_status": "NON_EXTRACTABLE_PDF",
            "extraction_reason": (
                "PDF sin texto embebido suficiente "
                f"(chars={text_chars}, alpha_ratio={alpha_ratio:.2f})."
            ),
            "extractor": "pypdf",
            "text_chars": text_chars,
            "inferred_date": inferred_date,
            "date_source": date_source,
            "text_sample": text_sample,
            "content_hash": content_hash,
        }
    try:
        decoded = content.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        decoded = content.decode("utf-8", errors="replace")
    clean_html = strip_html_boilerplate(decoded)
    inferred_date, date_source = _extract_date_from_html_document(clean_html, url)
    text = strip_html_to_text(clean_html).strip()
    if len(text) < 200:
        raw_soup = BeautifulSoup(decoded, "html.parser")
        fallback_block = _extract_largest_text_block(raw_soup)
        if fallback_block and len(fallback_block) > len(text):
            text = fallback_block
    text_chars = len(text)
    content_hash = _content_hash(text)
    text_sample = text[:TEXT_SAMPLE_MAX_CHARS]
    return content, text, {
        "extraction_status": "OK" if text_chars > 0 else "FETCH_ERROR",
        "extraction_reason": "" if text_chars > 0 else "Documento sin texto extraible tras limpieza HTML.",
        "extractor": "html_text",
        "text_chars": text_chars,
        "inferred_date": inferred_date,
        "date_source": date_source,
        "text_sample": text_sample,
        "content_hash": content_hash,
    }


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


_EXTRACTORS_CACHE: Optional[Tuple[Any, Any]] = None
_CLEAN_MD_GENERATOR_CACHE: Optional[Any] = None


def _resolve_extractor_or_raise(local_module: str, package_module: str, attr: str) -> Any:
    errors: List[str] = []
    try:
        mod = importlib.import_module(local_module)
        return getattr(mod, attr)
    except Exception as exc:
        errors.append(f"{local_module}.{attr}: {exc!r}")

    try:
        mod = importlib.import_module(package_module)
        return getattr(mod, attr)
    except Exception as exc:
        errors.append(f"{package_module}.{attr}: {exc!r}")

    path0 = sys.path[0] if sys.path else ""
    raise RuntimeError(
        "Extractor import failed (both local+package paths). "
        f"runner={Path(__file__).name} cwd={Path.cwd()} sys.path[0]={path0!r} "
        f"errors={'; '.join(errors)}"
    )


def _load_financial_extractors_or_raise() -> Tuple[Any, Any]:
    global _EXTRACTORS_CACHE
    if _EXTRACTORS_CACHE is not None:
        return _EXTRACTORS_CACHE

    extract_ixbrl_facts = _resolve_extractor_or_raise(
        "ixbrl_extractor",
        "scripts.runners.ixbrl_extractor",
        "extract_ixbrl_facts",
    )
    extract_financial_tables = _resolve_extractor_or_raise(
        "clean_md_extractor",
        "scripts.runners.clean_md_extractor",
        "extract_financial_tables",
    )
    _EXTRACTORS_CACHE = (extract_ixbrl_facts, extract_financial_tables)
    return _EXTRACTORS_CACHE


def _load_clean_md_generator() -> Any:
    global _CLEAN_MD_GENERATOR_CACHE
    if _CLEAN_MD_GENERATOR_CACHE is not None:
        return _CLEAN_MD_GENERATOR_CACHE
    try:
        mod = importlib.import_module("clean_md_pipeline")
        _CLEAN_MD_GENERATOR_CACHE = getattr(mod, "generate_clean_md")
        return _CLEAN_MD_GENERATOR_CACHE
    except Exception:
        pass
    try:
        mod = importlib.import_module("scripts.runners.clean_md_pipeline")
        _CLEAN_MD_GENERATOR_CACHE = getattr(mod, "generate_clean_md")
        return _CLEAN_MD_GENERATOR_CACHE
    except Exception as exc:
        raise RuntimeError(f"clean_md_pipeline.generate_clean_md import failed: {exc}") from exc


def _is_financial_source_type(tipo: str) -> bool:
    normalized = str(tipo or "").upper().replace(" ", "")
    tokens = (
        "10-K",
        "10K",
        "20-F",
        "20F",
        "40-F",
        "40F",
        "10-Q",
        "10Q",
        "6-K",
        "6K",
        "ANNUAL_REPORT",
        "INTERIM_REPORT",
        "REGULATORY_FILING",
    )
    return any(token in normalized for token in tokens)


def write_raw_files(
    client: SecClient,
    raw_dir: Path,
    source_id: str,
    tipo: str,
    period: str,
    url: str,
) -> Tuple[Optional[str], Optional[str], Optional[str], Dict[str, Any]]:
    try:
        binary, text, extraction_meta = get_doc_text(client, url)
    except Exception as e:
        return None, None, f"descarga fallida: {e}", {
            "extraction_status": "FETCH_ERROR",
            "extraction_reason": f"descarga fallida: {e}",
            "extractor": "none",
            "text_chars": 0,
        }

    ext = url_ext(url, fallback="htm")
    base = f"{source_id}_{safe_slug(tipo.upper())}_{safe_slug(period)}"
    original_name = f"{base}.{ext}"
    txt_name = f"{base}.txt"

    (raw_dir / original_name).write_bytes(binary)
    (raw_dir / txt_name).write_text(text, encoding="utf-8")

    # Generate .ixbrl.json (HTML) and .clean.md (HTML/PDF/TXT) for financial filings.
    source_path = raw_dir / original_name
    is_financial = _is_financial_source_type(tipo)
    clean_meta: Dict[str, Any] = {
        "mode": "unknown",
        "status": "SKIPPED_NOT_FINANCIAL" if not is_financial else "SKIPPED",
        "reason": "",
    }
    if is_financial and ext in ("htm", "html"):
        # Structural import failures must be explicit (fail-fast), not silent.
        extract_ixbrl_facts, _ = _load_financial_extractors_or_raise()
        try:
            ixbrl_data = extract_ixbrl_facts(source_path)
            ixbrl_name = f"{base}.ixbrl.json"
            import json as _json

            (raw_dir / ixbrl_name).write_text(
                _json.dumps(ixbrl_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            print(f"WARNING: iXBRL extraction failed for {original_name}: {e}", file=sys.stderr)

    if is_financial:
        try:
            generate_clean_md = _load_clean_md_generator()
            clean_md, clean_meta = generate_clean_md(
                source_path=source_path,
                txt_content=text,
                filing_type=tipo,
                source_id=source_id,
            )
            if clean_md:
                clean_name = f"{base}.clean.md"
                clean_path = raw_dir / clean_name
                clean_path.write_text(clean_md, encoding="utf-8")
                try:
                    clean_meta["clean_path"] = str(clean_path.relative_to(REPO_ROOT))
                except ValueError:
                    clean_meta["clean_path"] = str(clean_path)
        except Exception as e:
            clean_meta = {
                "mode": "unknown",
                "status": "ERROR",
                "reason": f"clean_md pipeline failed: {e}",
            }
            print(f"WARNING: clean.md pipeline failed for {original_name}: {e}", file=sys.stderr)

    extraction_meta["clean_md_mode"] = str(clean_meta.get("mode") or "unknown")
    extraction_meta["clean_md_status"] = str(clean_meta.get("status") or "SKIPPED")
    extraction_meta["clean_md_reason"] = str(clean_meta.get("reason") or "")
    extraction_meta["clean_md_chars"] = int(clean_meta.get("output_chars") or 0)
    if clean_meta.get("clean_path"):
        extraction_meta["clean_md_path"] = str(clean_meta.get("clean_path"))
    if isinstance(clean_meta.get("quality"), dict):
        extraction_meta["clean_md_quality"] = clean_meta.get("quality")

    return raw_dir_local_path(raw_dir, txt_name), first_25_words(text), None, extraction_meta


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
                    _, text, _ = get_doc_text(client, build_doc_url(cik_int, rec))
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
    # Diagnostics collected during push_source() extraction.
    # Must be initialized before the closure uses it.
    clean_md_diag_records: List[Dict[str, Any]] = []

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

        local_path, quote, err, extraction_meta = write_raw_files(
            client, raw_dir, source_id, tipo, period, doc_url
        )
        if err:
            out["cache_stats"]["archivos_fallidos"] += 1
        else:
            out["cache_stats"]["archivos_descargados"] += 1

        extraction_status = str(
            extraction_meta.get("extraction_status") or ("OK" if local_path else "FETCH_ERROR")
        ).upper()
        extraction_reason = str(extraction_meta.get("extraction_reason") or "")
        extractor = str(extraction_meta.get("extractor") or "none")
        clean_md_mode = str(extraction_meta.get("clean_md_mode") or "unknown")
        clean_md_status = str(extraction_meta.get("clean_md_status") or "SKIPPED")
        clean_md_reason = str(extraction_meta.get("clean_md_reason") or "")
        try:
            clean_md_chars = int(extraction_meta.get("clean_md_chars") or 0)
        except Exception:
            clean_md_chars = 0
        try:
            text_chars = int(extraction_meta.get("text_chars") or 0)
        except Exception:
            text_chars = 0
        clean_md_diag_records.append(
            {
                "source_id": source_id,
                "tipo": tipo,
                "url": doc_url,
                "mode": clean_md_mode,
                "status": clean_md_status,
                "reason": clean_md_reason,
                "output_chars": clean_md_chars,
                "text_chars": text_chars,
                "clean_md_path": str(extraction_meta.get("clean_md_path") or ""),
            }
        )

        annual_like = {"10-K", "20-F", "40-F", "ANNUAL_REPORT"}
        if tipo.upper() in annual_like and extraction_status == "OK" and text_chars < 10000:
            low_text_note = (
                f"Annual filing with low extracted text volume ({text_chars} chars)."
            )
            extraction_reason = f"{extraction_reason} {low_text_note}".strip()
            out.setdefault("log", {}).setdefault("limitaciones", []).append(
                f"{source_id} ({tipo}) warning: {low_text_note}"
            )

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
            "extraction_status": extraction_status,
            "extraction_reason": extraction_reason,
            "extractor": extractor,
            "text_chars": text_chars,
            "content_hash": str(extraction_meta.get("content_hash") or ""),
            "contenido_disponible": extraction_status == "OK",
            "clean_md_mode": clean_md_mode,
            "clean_md_status": clean_md_status,
            "clean_md_reason": clean_md_reason,
            "clean_md_chars": clean_md_chars,
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
        elif extraction_status != "OK":
            out.setdefault("log", {}).setdefault("limitaciones", []).append(
                f"{source_id} ({tipo}) extraction_status={extraction_status}: {extraction_reason or 'sin detalle'}"
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
    local_fallback_extractable_added = 0
    local_fallback_rejected_low_quality = 0
    local_fallback_annual_non_extractable = 0
    local_fallback_umbraco_modules_detected = 0
    local_fallback_umbraco_rows_collected = 0
    local_fallback_umbraco_candidates_added = 0
    local_fallback_umbraco_api_errors = 0
    local_fallback_clean_md_generated_html = 0
    local_fallback_clean_md_generated_pdf = 0
    local_fallback_clean_md_rejected_quality = 0
    local_fallback_clean_md_generation_errors = 0
    local_fallback_clean_md_rejection_samples: List[Dict[str, Any]] = []
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
            queue = list(pages)
            visited = set()
            while queue and len(visited) < LOCAL_FALLBACK_MAX_PAGES:
                page = queue.pop(0)
                if page in visited:
                    continue
                visited.add(page)
                try:
                    html = client.get(page).text
                except Exception as exc:
                    local_fallback_errors.append(f"No se pudo cargar {page}: {exc}")
                    continue

                for subpage in discover_ir_subpages(
                    html,
                    page,
                    exchange,
                    max_links=LOCAL_FALLBACK_MAX_LINKS_PER_PAGE,
                ):
                    if subpage in visited or subpage in queue:
                        continue
                    if len(visited) + len(queue) >= LOCAL_FALLBACK_MAX_PAGES:
                        break
                    queue.append(subpage)

                for candidate in extract_local_filing_candidates(html, page, exchange):
                    url = str(candidate.get("url") or "")
                    if not url:
                        continue
                    candidate["discovered_from"] = page
                    prev = collected.get(url)
                    if prev is None:
                        collected[url] = candidate
                        continue
                    if _prefer_new_candidate(prev, candidate):
                        if prev.get("fecha_publicacion") and not candidate.get("fecha_publicacion"):
                            _date_debug(
                                "collected candidate replacement would drop date "
                                f"(url={url}, prev_date={prev.get('fecha_publicacion')})"
                            )
                        collected[url] = candidate

                umbraco_candidates, umbraco_metrics, umbraco_errors = _collect_umbraco_candidates(
                    client=client,
                    html=html,
                    page_url=page,
                    exchange=exchange,
                    country=country,
                )
                local_fallback_umbraco_modules_detected += int(umbraco_metrics.get("modules_detected", 0))
                local_fallback_umbraco_rows_collected += int(umbraco_metrics.get("rows_collected", 0))
                local_fallback_umbraco_candidates_added += int(umbraco_metrics.get("candidates_added", 0))
                local_fallback_umbraco_api_errors += int(umbraco_metrics.get("api_errors", 0))
                if umbraco_errors:
                    local_fallback_errors.extend(umbraco_errors)

                for candidate in umbraco_candidates:
                    url = str(candidate.get("url") or "")
                    if not url:
                        continue
                    candidate["discovered_from"] = page
                    prev = collected.get(url)
                    if prev is None or _prefer_new_candidate(prev, candidate):
                        collected[url] = candidate

            selected = _select_local_fallback_candidates(list(collected.values()))

            for cand in selected:
                source_id = f"SRC_SEC_{source_counter:03d}"
                source_counter += 1
                doc_url = str(cand.get("url", ""))
                title = str(cand.get("titulo") or "Local regulatory filing")
                # Classify filing type from context (title + URL + snippet)
                _tipo = str(cand.get("tipo_guess") or _classify_local_filing_type(
                    title, doc_url, str(cand.get("snippet") or "")
                ))
                if is_navigation_like_source(title, str(cand.get("snippet") or ""), doc_url):
                    local_fallback_errors.append(
                        f"{source_id} descartada por patrón de navegación/índice ({doc_url})"
                    )
                    continue

                fecha_pub = cand.get("fecha_publicacion")
                fecha_source = str(cand.get("fecha_source") or "unknown")
                fecha_estimated = bool(cand.get("fecha_publicacion_estimated", True))
                period = str(fecha_pub or "UNDATED")

                local_path_val, quote, err, extraction_meta = write_raw_files(
                    client, raw_dir, source_id, _tipo, period, doc_url
                )
                if err:
                    out["cache_stats"]["archivos_fallidos"] += 1
                    local_fallback_errors.append(f"{source_id} fallback local sin descarga: {err}")

                extraction_status = str(
                    extraction_meta.get("extraction_status") or ("OK" if local_path_val else "FETCH_ERROR")
                ).upper()
                extraction_reason = str(extraction_meta.get("extraction_reason") or "")
                extractor = str(extraction_meta.get("extractor") or "none")
                clean_md_mode = str(extraction_meta.get("clean_md_mode") or "unknown")
                clean_md_status = str(extraction_meta.get("clean_md_status") or "SKIPPED")
                clean_md_reason = str(extraction_meta.get("clean_md_reason") or "")
                try:
                    clean_md_chars = int(extraction_meta.get("clean_md_chars") or 0)
                except Exception:
                    clean_md_chars = 0
                text_sample = str(extraction_meta.get("text_sample") or "")
                if not err and extraction_status == "OK" and is_navigation_like_source(title, text_sample, doc_url):
                    local_fallback_errors.append(
                        f"{source_id} descartada tras extracción por contenido navegación/índice ({doc_url})"
                    )
                    if local_path_val:
                        try:
                            lp = Path(local_path_val)
                            lp_abs = lp if lp.is_absolute() else (REPO_ROOT / lp)
                            txt_abs = lp_abs if lp_abs.suffix.lower() == ".txt" else lp_abs.with_suffix(".txt")
                            raw_abs = txt_abs.with_suffix(f".{url_ext(doc_url, fallback='htm')}")
                            if txt_abs.exists():
                                txt_abs.unlink()
                            if raw_abs.exists():
                                raw_abs.unlink()
                        except Exception:
                            pass
                    continue
                if not err:
                    out["cache_stats"]["archivos_descargados"] += 1
                try:
                    text_chars = int(extraction_meta.get("text_chars") or 0)
                except Exception:
                    text_chars = 0
                clean_md_diag_records.append(
                    {
                        "source_id": source_id,
                        "tipo": _tipo,
                        "url": doc_url,
                        "mode": clean_md_mode,
                        "status": clean_md_status,
                        "reason": clean_md_reason,
                        "output_chars": clean_md_chars,
                        "text_chars": text_chars,
                        "clean_md_path": str(extraction_meta.get("clean_md_path") or ""),
                    }
                )
                if clean_md_status == "GENERATED":
                    if clean_md_mode == "html_table":
                        local_fallback_clean_md_generated_html += 1
                    elif clean_md_mode == "pdf_text":
                        local_fallback_clean_md_generated_pdf += 1
                elif clean_md_status == "REJECTED_QUALITY":
                    local_fallback_clean_md_rejected_quality += 1
                    if len(local_fallback_clean_md_rejection_samples) < 10:
                        local_fallback_clean_md_rejection_samples.append(
                            {
                                "source_id": source_id,
                                "reason": clean_md_reason or "LOW_QUALITY",
                            }
                        )
                elif clean_md_status.startswith("ERROR"):
                    local_fallback_clean_md_generation_errors += 1
                    if len(local_fallback_clean_md_rejection_samples) < 10:
                        local_fallback_clean_md_rejection_samples.append(
                            {
                                "source_id": source_id,
                                "reason": clean_md_reason or "PIPELINE_ERROR",
                            }
                        )
                extraction_status, extraction_reason, annual_quality_eval = _classify_local_annual_extractability(
                    tipo=_tipo,
                    extraction_status=extraction_status,
                    extraction_reason=extraction_reason,
                    text_chars=text_chars,
                    text_sample=text_sample,
                )
                low_quality_rejected = bool(annual_quality_eval.get("rejected_low_quality"))
                if low_quality_rejected:
                    local_fallback_rejected_low_quality += 1
                    local_fallback_annual_non_extractable += 1
                    local_fallback_errors.append(
                        f"{source_id} downgraded to {extraction_status}: {annual_quality_eval.get('reject_reason')}"
                    )
                inferred_date = extraction_meta.get("inferred_date")
                if not fecha_pub and inferred_date:
                    fecha_pub = str(inferred_date)
                    fecha_source = str(extraction_meta.get("date_source") or "document")
                    fecha_estimated = False
                elif not fecha_pub:
                    fecha_pub = None
                    fecha_source = "unknown"
                    fecha_estimated = True

                source: Dict[str, Any] = {
                    "source_id": source_id,
                    "categoria": "REGULATORIO",
                    "tipo": _tipo,
                    "titulo": title,
                    "url": doc_url,
                    "publicador": "Company IR / Local regulator",
                    "fecha_publicacion": fecha_pub,
                    "fecha_publicacion_estimated": fecha_estimated,
                    "fecha_source": fecha_source,
                    "fecha_recuperacion": dt.date.today().isoformat(),
                    "idioma": "en",
                    "fiabilidad": "B",
                    "relevancia": "ALTA",
                    "notas": f"Fallback local no-US ({regulator_code}).",
                    "cita_rapida": quote or str(cand.get("snippet") or "")[:180],
                    "selection_score": float(cand.get("selection_score", 0.0)),
                    "discovered_from": str(cand.get("discovered_from") or ""),
                    "origen_regulatorio_local": True,
                    "regulator_code": regulator_code,
                    "extraction_status": extraction_status,
                    "extraction_reason": extraction_reason,
                    "extractor": extractor,
                    "text_chars": text_chars,
                    "content_hash": str(extraction_meta.get("content_hash") or ""),
                    "contenido_disponible": extraction_status == "OK",
                    "clean_md_mode": clean_md_mode,
                    "clean_md_status": clean_md_status,
                    "clean_md_reason": clean_md_reason,
                    "clean_md_chars": clean_md_chars,
                }
                if local_path_val:
                    source["local_path"] = local_path_val
                out["fuentes"].append(source)
                local_fallback_added += 1
                if extraction_status == "OK":
                    local_fallback_extractable_added += 1

                if _tipo in {"ANNUAL_REPORT", "10-K", "20-F", "40-F"} and extraction_status == "OK" and text_chars < 10000:
                    low_text_note = (
                        f"Annual filing with low extracted text volume ({text_chars} chars)."
                    )
                    source["extraction_reason"] = f"{source.get('extraction_reason', '')} {low_text_note}".strip()
                    local_fallback_errors.append(f"{source_id} warning: {low_text_note}")
                elif extraction_status != "OK" and not low_quality_rejected:
                    local_fallback_errors.append(
                        f"{source_id} extraction_status={extraction_status}: {extraction_reason or 'sin detalle'}"
                    )

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
        "sources_added_total": local_fallback_added,
        "sources_extractable_added": local_fallback_extractable_added,
        "sources_rejected_low_quality": local_fallback_rejected_low_quality,
        "annual_non_extractable_count": local_fallback_annual_non_extractable,
        "umbraco_modules_detected": local_fallback_umbraco_modules_detected,
        "umbraco_rows_collected": local_fallback_umbraco_rows_collected,
        "umbraco_candidates_added": local_fallback_umbraco_candidates_added,
        "umbraco_api_errors": local_fallback_umbraco_api_errors,
        "clean_md_generated_html": local_fallback_clean_md_generated_html,
        "clean_md_generated_pdf": local_fallback_clean_md_generated_pdf,
        "clean_md_rejected_quality": local_fallback_clean_md_rejected_quality,
        "clean_md_generation_errors": local_fallback_clean_md_generation_errors,
        "clean_md_rejection_samples": local_fallback_clean_md_rejection_samples[:10],
        "exchange": exchange,
        "country": country,
        "web_ir": web_ir,
    }
    if local_fallback_attempted:
        out.setdefault("log", {}).setdefault("limitaciones", []).append(
            "Local fallback summary: "
            f"added_total={local_fallback_added}, "
            f"extractable_added={local_fallback_extractable_added}, "
            f"rejected_low_quality={local_fallback_rejected_low_quality}, "
            f"annual_non_extractable={local_fallback_annual_non_extractable}, "
            f"umbraco_modules={local_fallback_umbraco_modules_detected}, "
            f"umbraco_rows={local_fallback_umbraco_rows_collected}, "
            f"umbraco_candidates={local_fallback_umbraco_candidates_added}, "
            f"umbraco_api_errors={local_fallback_umbraco_api_errors}, "
            f"clean_md_html={local_fallback_clean_md_generated_html}, "
            f"clean_md_pdf={local_fallback_clean_md_generated_pdf}, "
            f"clean_md_rejected={local_fallback_clean_md_rejected_quality}, "
            f"clean_md_errors={local_fallback_clean_md_generation_errors}."
        )
    if local_fallback_errors:
        out.setdefault("log", {}).setdefault("limitaciones", []).extend(local_fallback_errors)

    if clean_md_diag_records:
        diag_dir = case_dir / "_diagnostics" / "clean_md_generation"
        diag_dir.mkdir(parents=True, exist_ok=True)
        diag_path = diag_dir / "clean_md_meta.jsonl"
        with diag_path.open("w", encoding="utf-8") as fh:
            for rec in clean_md_diag_records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

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
