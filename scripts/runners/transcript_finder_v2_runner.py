#!/usr/bin/env python3
"""Earnings transcript & investor presentation fetcher for ELSIAN INVEST pipeline.

Searches Fintool.com and company IR pages for earnings call transcripts and
investor presentations.  Produces SourcesPack_v1 JSON + downloaded PDFs/HTML.

Usage:
    python3 scripts/runners/transcript_finder_v2_runner.py --ticker CRTO --case-dir casos/CRTO/2026-02-14

Política de faltantes: ver _operativa/POLITICA_FALTANTES.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import sys
import warnings
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL 1.1.1+")

try:
    from urllib3.exceptions import NotOpenSSLWarning  # type: ignore

    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

USER_AGENT = "ELSIAN-INVEST-Bot/1.0 (research; bot@elsian-invest.local)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
ALT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": HEADERS["Accept"],
}
TIMEOUT = 45
NON_US_EXCHANGES = {"LSE", "AIM", "SEHK", "HKEX", "ASX", "EPA", "TSX", "OTRA"}
US_COUNTRIES = {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}
LEGAL_ENTITY_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "companies",
    "limited",
    "ltd",
    "plc",
    "llc",
    "sa",
    "spa",
    "ag",
    "nv",
    "fpo",
    "holdings",
    "holding",
    "group",
}
TITLE_ISSUER_PATTERNS = (
    re.compile(r"^(.+?)\s*-\s*Earnings Call", re.IGNORECASE),
    re.compile(r"^(.+?)\s*\(([A-Z]{1,6})\)\s+Q[1-4]", re.IGNORECASE),
    re.compile(r"^(.+?)\s+Q[1-4]\s+\d{4}\s+Earnings", re.IGNORECASE),
)

IR_PRESENTATION_PATHS = (
    "/news-events/presentations",
    "/financial-information/financial-results",
    "/events-presentations",
    "/events-and-presentations",
    "/investor-relations/events-and-presentations",
    "/reports-results-and-presentations",
    "/results",
    "/reports",
    "/financial-results",
    "/announcements",
    "/publications",
    "/news",
    "/documents",
)
IR_DOC_KEYWORDS = (
    "presentation",
    "investor",
    "earnings",
    "results",
    "deck",
    "slides",
    "annual report",
    "interim report",
    "financial report",
    "report and accounts",
    "registration document",
    "trading update",
    "full year results",
    "half year results",
)
IR_HTML_HINTS = (
    "results",
    "report",
    "announcement",
    "rns",
    "earnings",
    "financial",
    "trading update",
    "press release",
    "regulatory story",
)
IR_HTML_STRONG_DOC_HINTS = (
    "annual results",
    "full year",
    "full-year",
    "registration document",
    "universal registration document",
    "integrated report",
    "interim results",
    "financial results",
)
NAV_HINTS = (
    "home",
    "search",
    "menu",
    "investor relations",
    "corporate governance",
    "cookie",
    "privacy",
    "latest news",
    "announcements",
    "publications",
    "financials",
)
FIN_HINTS = (
    "revenue",
    "income",
    "profit",
    "eps",
    "ebit",
    "ebitda",
    "cash flow",
    "balance sheet",
    "assets",
    "liabilities",
    "equity",
    "dividend",
    "capex",
)
ANNUAL_DOC_HINTS = (
    "urd",
    "universal registration document",
    "document d'enregistrement universel",
    "annual report",
    "integrated report",
)


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_iso() -> str:
    return dt.date.today().isoformat()


def clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = clean_ws(value).upper()
    if not raw:
        return None
    if raw in {"USA", "UNITED STATES", "UNITED STATES OF AMERICA"}:
        return "US"
    if raw == "AUSTRALIA":
        return "AU"
    return raw


def normalize_exchange(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = clean_ws(value).upper()
    if not raw:
        return None
    if "OTC" in raw:
        return "OTC"
    return raw


def _normalize_entity_name(value: Optional[str]) -> str:
    text = clean_ws(str(value or "")).lower()
    if not text:
        return ""
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"\([^\)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = []
    for token in text.split():
        if token in LEGAL_ENTITY_SUFFIXES:
            continue
        tokens.append(token)
    return " ".join(tokens).strip()


def _extract_company_from_title(title: Optional[str]) -> List[str]:
    t = clean_ws(str(title or ""))
    if not t:
        return []
    out: List[str] = []
    for pattern in TITLE_ISSUER_PATTERNS:
        m = pattern.search(t)
        if not m:
            continue
        cand = clean_ws(m.group(1))
        if cand:
            out.append(cand)
    if " - " in t:
        first = clean_ws(t.split(" - ", 1)[0])
        if first:
            out.append(first)
    deduped: List[str] = []
    seen = set()
    for cand in out:
        norm = _normalize_entity_name(cand)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(cand)
    return deduped


def _is_weak_target_alias(alias_norm: str, ticker_norm: str) -> bool:
    if not alias_norm:
        return True
    if alias_norm == ticker_norm:
        return True
    tokens = alias_norm.split()
    if len(alias_norm) < 5:
        return True
    if len(tokens) == 1 and len(tokens[0]) <= 4:
        return True
    return False


def _build_target_aliases(
    ticker: str,
    empresa: Dict[str, Any],
    sec_empresa: Dict[str, Any],
    src_empresa: Dict[str, Any],
) -> Tuple[List[str], str]:
    raw_aliases = [
        empresa.get("nombre"),
        sec_empresa.get("nombre"),
        src_empresa.get("nombre"),
    ]
    ticker_norm = _normalize_entity_name(ticker)
    strong_aliases: List[str] = []
    seen = set()
    for raw in raw_aliases:
        norm = _normalize_entity_name(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if _is_weak_target_alias(norm, ticker_norm):
            continue
        strong_aliases.append(norm)
    quality = "STRONG" if strong_aliases else "WEAK"
    return strong_aliases, quality


def _score_issuer_pair(target_norm: str, candidate_norm: str) -> float:
    target_tokens = set(target_norm.split())
    candidate_tokens = set(candidate_norm.split())
    union = target_tokens | candidate_tokens
    jaccard = (len(target_tokens & candidate_tokens) / len(union)) if union else 0.0
    seq_ratio = difflib.SequenceMatcher(None, target_norm, candidate_norm).ratio()
    score = max(jaccard, seq_ratio)

    if (
        len(target_tokens) >= 2
        and len(candidate_tokens) >= 2
        and min(len(target_norm), len(candidate_norm)) >= 6
        and (target_norm in candidate_norm or candidate_norm in target_norm)
    ):
        score = max(score, 0.90)
    return score


def _issuer_match_decision(
    target_aliases: List[str],
    issuer_candidates: List[str],
    ticker: str,
) -> Tuple[str, float, str, str]:
    if not target_aliases:
        return "MISMATCH", 0.0, "", "target identity weak: no robust target aliases available"
    if not issuer_candidates:
        return "MISMATCH", 0.0, target_aliases[0], "no issuer candidates found in transcript metadata/title"

    best_score = -1.0
    best_target = ""
    best_candidate = ""
    for target_norm in target_aliases:
        for candidate in issuer_candidates:
            candidate_norm = _normalize_entity_name(candidate)
            if not candidate_norm:
                continue
            score = _score_issuer_pair(target_norm, candidate_norm)
            if score > best_score:
                best_score = score
                best_target = target_norm
                best_candidate = candidate_norm

    if best_score < 0:
        return "MISMATCH", 0.0, target_aliases[0], "issuer candidates normalized to empty values"

    target_token_count = len(best_target.split())
    threshold = 0.45 if (target_token_count >= 2 or len(best_target) >= 6) else 0.75
    status = "MATCH" if best_score >= threshold else "MISMATCH"
    reason = (
        f"target='{best_target}' candidate='{best_candidate}' "
        f"score={best_score:.2f} threshold={threshold:.2f}"
    )
    if status == "MISMATCH" and _normalize_entity_name(ticker) in {best_target, best_candidate}:
        reason = f"{reason}; ticker collision detected"
    return status, best_score, best_target, reason


def first_25_words(text: str) -> str:
    words = re.findall(r"\S+", text or "")
    return " ".join(words[:25])


def safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")


def raw_dir_local_path(raw_dir: Path, filename: str) -> str:
    """Return repo-root-relative path for a file in raw_dir."""
    full = raw_dir / filename
    try:
        return str(full.relative_to(REPO_ROOT))
    except ValueError:
        return f"_raw_filings/{filename}"


def parse_human_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = clean_ws(value)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_date_in_text(text: str) -> Optional[str]:
    value = clean_ws(text)
    if not value:
        return None

    for match in re.findall(r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", value):
        parsed = parse_human_date(match)
        if parsed:
            return parsed

    for match in re.findall(r"(20\d{2}-\d{2}-\d{2})", value):
        parsed = parse_human_date(match)
        if parsed:
            return parsed
    return None


def normalize_period(period_raw: Optional[str]) -> str:
    value = clean_ws((period_raw or "").replace("_", "-")).upper()
    value = value.replace(" ", "-")
    m_q = re.match(r"Q([1-4])[-]?((?:19|20)\d{2})$", value)
    if m_q:
        return f"Q{m_q.group(1)}-{m_q.group(2)}"
    m_q_short = re.match(r"Q([1-4])[-]?(\d{2})$", value)
    if m_q_short:
        return f"Q{m_q_short.group(1)}-20{m_q_short.group(2)}"
    m_q2 = re.match(r"Q([1-4])[-]?FY[-]?((?:19|20)\d{2})$", value)
    if m_q2:
        return f"Q{m_q2.group(1)}-{m_q2.group(2)}"
    m_fy = re.match(r"FY[-]?((?:19|20)\d{2})$", value)
    if m_fy:
        return f"FY{m_fy.group(1)}"
    m_q3 = re.match(r"([1-4])Q[-]?((?:19|20)\d{2})$", value)
    if m_q3:
        return f"Q{m_q3.group(1)}-{m_q3.group(2)}"
    m_q3_short = re.match(r"([1-4])Q[-]?(\d{2})$", value)
    if m_q3_short:
        return f"Q{m_q3_short.group(1)}-20{m_q3_short.group(2)}"
    m_slug = re.match(r"Q([1-4])-((?:19|20)\d{2})", value)
    if m_slug:
        return f"Q{m_slug.group(1)}-{m_slug.group(2)}"
    return safe_slug(value) or "UNKNOWN"


def period_sort_key(slug: str) -> Tuple[int, int]:
    low = slug.lower().strip()
    m = re.match(r"q([1-4])-(\d{4})", low)
    if m:
        return (int(m.group(2)), int(m.group(1)))
    m_fy = re.match(r"fy[-]?(\d{4})", low)
    if m_fy:
        return (int(m_fy.group(1)), 4)
    return (0, 0)


def infer_tema(text: str) -> str:
    low = (text or "").lower()
    if any(k in low for k in ("revenue", "sales", "net sales", "income")):
        return "ingresos"
    if any(k in low for k in ("guidance", "outlook", "expect")):
        return "guidance"
    if any(k in low for k in ("margin", "ebitda", "profit")):
        return "margen"
    if any(k in low for k in ("debt", "cash", "liquidity")):
        return "deuda"
    if any(k in low for k in ("risk", "tariff", "headwind", "uncertain")):
        return "riesgos"
    return "otro"


def _get_with_retry(session: requests.Session, url: str) -> requests.Response:
    """GET with 1 retry on 429/5xx or connection errors (3s backoff)."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except (requests.exceptions.HTTPError, requests.exceptions.ConnectionError) as exc:
        import time
        status = getattr(getattr(exc, "response", None), "status_code", 0)
        host = urlparse(url).netloc.lower()
        if status in (429, 500, 502, 503, 504) or isinstance(exc, requests.exceptions.ConnectionError):
            time.sleep(3)
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            return resp
        if status == 403 and "fintool.com" not in host:
            time.sleep(1)
            resp = session.get(url, headers=ALT_HEADERS, timeout=TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            return resp
        raise


def request_text(session: requests.Session, url: str) -> str:
    resp = _get_with_retry(session, url)
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def request_bytes(session: requests.Session, url: str) -> bytes:
    resp = _get_with_retry(session, url)
    return resp.content


def parse_next_data(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("script", id="__NEXT_DATA__")
    if not node or not node.text:
        raise ValueError("No se encontró __NEXT_DATA__ en la página de transcript.")
    return json.loads(node.text)


def build_transcript_text(page_props: Dict[str, Any]) -> str:
    company = page_props.get("companyName") or page_props.get("ticker") or "UNKNOWN"
    display_period = page_props.get("displayPeriod") or page_props.get("period") or "UNKNOWN"
    title = page_props.get("title") or f"{company} Earnings Call Transcript"
    published_at = page_props.get("publishedAt") or "UNKNOWN"

    lines: List[str] = []
    lines.append(f"{title}")
    lines.append(f"Company: {company}")
    lines.append(f"Period: {display_period}")
    lines.append(f"Published: {published_at}")
    lines.append("")

    executive_summary = page_props.get("executiveSummary") or []
    if isinstance(executive_summary, list) and executive_summary:
        lines.append("EXECUTIVE SUMMARY")
        for item in executive_summary:
            item_text = clean_ws(str(item))
            if item_text:
                lines.append(f"- {item_text}")
        lines.append("")

    transcript_obj = page_props.get("transcript") or {}
    sections = transcript_obj.get("transcript") if isinstance(transcript_obj, dict) else []
    lines.append("FULL TRANSCRIPT")
    if isinstance(sections, list):
        for block in sections:
            if not isinstance(block, dict):
                continue
            speaker = clean_ws(str(block.get("name") or "UNKNOWN"))
            session = clean_ws(str(block.get("session") or "session"))
            lines.append("")
            lines.append(f"[{speaker}] ({session})")
            speech = block.get("speech") or []
            if isinstance(speech, list):
                for chunk in speech:
                    chunk_text = clean_ws(str(chunk))
                    if chunk_text:
                        lines.append(chunk_text)
            elif speech:
                lines.append(clean_ws(str(speech)))
    return "\n".join(lines).strip() + "\n"


def extract_transcript_periods(index_html: str, ticker: str) -> List[str]:
    pattern = re.compile(
        rf"/app/research/companies/{re.escape(ticker.upper())}/documents/transcripts/([a-z0-9-]+)",
        re.IGNORECASE,
    )
    periods = sorted(set(pattern.findall(index_html)), key=period_sort_key, reverse=True)
    return periods


def strip_html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _normalize_text_for_hash(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _content_hash(text: str) -> str:
    normalized = _normalize_text_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def _is_low_financial_density(text: str, window: int = 2000) -> bool:
    sample = _normalize_text_for_hash(text)[:window]
    if not sample:
        return True
    fin_hits = sum(1 for k in FIN_HINTS if k in sample)
    num_hits = len(re.findall(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?%\b", sample))
    return fin_hits < 2 and num_hits < 2


def is_navigation_like_source(title: str, text: str, url: str) -> bool:
    low_url = (url or "").lower()
    if low_url.endswith(".pdf"):
        return False
    sample = _normalize_text_for_hash(text)[:2500]
    title_low = _normalize_text_for_hash(title)
    nav_hits = sum(1 for k in NAV_HINTS if k in sample or k in title_low or k in low_url)
    index_like_url = any(
        p in low_url
        for p in (
            "/investor-relations",
            "/announcements",
            "/news",
            "/publications",
            "/finance-kit",
        )
    )
    if "search home android smartpos" in sample:
        return True
    if index_like_url and _is_low_financial_density(sample):
        return True
    return nav_hits >= 4 and _is_low_financial_density(sample)


def classify_presentation_source_type(title: str, url: str, row_text: str = "") -> str:
    """Classify presentation-like sources into annual docs vs generic presentations."""
    combined = clean_ws(f"{title} {row_text} {url}".lower())
    normalized = re.sub(r"[-_/]+", " ", combined)
    if any(h in normalized for h in ANNUAL_DOC_HINTS):
        return "ANNUAL_REPORT"
    return "INVESTOR_PRESENTATION"


def _has_html_doc_evidence(
    *,
    period: str,
    fecha_evento: Optional[str],
    context_norm: str,
    low_url: str,
) -> bool:
    if period != "UNKNOWN" or bool(fecha_evento):
        return True
    merged = f"{context_norm} {low_url}"
    has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", merged))
    if not has_year:
        return False
    if any(hint in merged for hint in IR_HTML_STRONG_DOC_HINTS):
        return True
    if re.search(r"\bq[1-4]\b", merged):
        return True
    if re.search(r"\bh[12]\b", merged):
        return True
    return False


def _is_index_like_html_url(low_url: str) -> bool:
    if "engagestream" in low_url and re.search(r"/register/?(?:$|[?#])", low_url):
        return True
    if re.search(r"/register/?(?:$|[?#])", low_url):
        return True
    if "signup" in low_url:
        return True
    patterns = (
        r"/investors/investors-homepage/?$",
        r"/investors/?$",
        r"/en-us/?$",
        r"/publications-and-events/?$",
        r"/publications-and-events/(?:press-releases|financial-publications|site-visits-investor-days|other-presentations|regulated-information)/?$",
    )
    return any(re.search(pat, low_url) for pat in patterns)


def extract_presentation_rows(
    ir_html: str,
    base_url: str,
) -> Tuple[List[Tuple[str, str, Optional[str], str, str]], List[Dict[str, str]]]:
    soup = BeautifulSoup(ir_html, "html.parser")
    rows: List[Tuple[str, str, Optional[str], str, str]] = []
    rejected: List[Dict[str, str]] = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        low_url = full_url.lower()
        if low_url.startswith(("mailto:", "javascript:")):
            continue
        if "sec-filings" in low_url:
            continue
        if "/news/" in low_url and "presentation" not in low_url:
            continue

        parent = a.find_parent(["li", "tr", "div", "section", "article"])
        text = clean_ws(a.get_text(" ", strip=True))
        row_text = clean_ws(parent.get_text(" ", strip=True) if parent else text)
        context = clean_ws(f"{row_text} {full_url}".lower())
        context_norm = re.sub(r"[-_/]+", " ", context)
        if not any(k in context_norm for k in IR_DOC_KEYWORDS):
            continue
        is_pdf = ".pdf" in low_url
        if not is_pdf and not any(h in context_norm for h in IR_HTML_HINTS):
            continue

        period_match = re.search(
            r"(Q[1-4][\s_-]*(?:20)?\d{2}|[1-4]Q[\s_-]*(?:20)?\d{2}|FY[\s_-]*(?:20)?\d{2}|20\d{2})",
            f"{row_text} {full_url}",
            re.IGNORECASE,
        )
        period = normalize_period(period_match.group(1) if period_match else None)
        fecha_evento = parse_date_in_text(row_text) or parse_date_in_text(full_url)
        if not is_pdf:
            if _is_index_like_html_url(low_url):
                rejected.append(
                    {
                        "url": full_url,
                        "title": text or row_text[:180],
                        "reason": "navigation_or_index_html",
                        "detail": "index_like_url",
                    }
                )
                continue
            if not _has_html_doc_evidence(
                period=period,
                fecha_evento=fecha_evento,
                context_norm=context_norm,
                low_url=low_url,
            ):
                rejected.append(
                    {
                        "url": full_url,
                        "title": text or row_text[:180],
                        "reason": "navigation_or_index_html",
                        "detail": "html_without_document_evidence",
                    }
                )
                continue
            if is_navigation_like_source(text or row_text[:120], f"{row_text} {full_url}", full_url):
                rejected.append(
                    {
                        "url": full_url,
                        "title": text or row_text[:180],
                        "reason": "navigation_or_index_html",
                        "detail": "navigation_like_pattern",
                    }
                )
                continue
        rows.append((full_url, period, fecha_evento, row_text or text, "pdf" if is_pdf else "html"))

    # Dedup by URL and keep latest periods first.
    seen_url: set[str] = set()
    seen_name: set[str] = set()
    deduped: List[Tuple[str, str, Optional[str], str, str]] = []
    for href, period, fecha_evento, row_text, doc_kind in sorted(
        rows, key=lambda x: period_sort_key(x[1].lower()), reverse=True
    ):
        basename = Path(urlparse(href).path).name.lower()
        if href in seen_url:
            continue
        if basename and basename in seen_name:
            continue
        seen_url.add(href)
        if basename:
            seen_name.add(basename)
        deduped.append((href, period, fecha_evento, row_text, doc_kind))
    return deduped, rejected


def normalize_web_ir(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    candidate = clean_ws(url)
    if not candidate:
        return None
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    return candidate.rstrip("/")


def read_sec_context(case_dir: Path) -> Dict[str, Any]:
    sec_path = case_dir / "_sec_fetcher_output.json"
    if not sec_path.exists():
        return {}
    try:
        data = json.loads(sec_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


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
            if isinstance(data, dict):
                empresa = data.get("empresa")
                if isinstance(empresa, dict):
                    return empresa
        except Exception:
            continue
    return {}


def _derive_ir_roots(base_url: str) -> List[str]:
    parsed = urlparse(base_url)
    host_root = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    path = parsed.path.strip("/")
    segments = [seg for seg in path.split("/") if seg]
    original_segments = list(segments)
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
        norm = normalize_web_ir(root)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(norm)
    return deduped


def build_ir_pages(web_ir: Optional[str]) -> List[str]:
    base = normalize_web_ir(web_ir)
    if not base:
        return []
    pages: List[str] = [base]
    homepage_tail_re = re.compile(r"/(?:investors-homepage|investor-homepage|homepage|home)$")
    for root in _derive_ir_roots(base):
        pages.append(root)
        low_path = (urlparse(root).path or "").rstrip("/").lower()
        if homepage_tail_re.search(low_path):
            continue
        for suffix in IR_PRESENTATION_PATHS:
            pages.append(urljoin(root + "/", suffix.lstrip("/")))
    return list(dict.fromkeys(pages))


def main() -> int:
    parser = argparse.ArgumentParser(description="TRANSCRIPT_FINDER_V2 runner")
    parser.add_argument("--ticker", required=True, help="Ticker, e.g., IBTA")
    parser.add_argument("--case-dir", required=True, help="Case directory, e.g., casos/IBTA/2026-02-13")
    parser.add_argument("--raw-dir", default="", help="Raw filings directory (default: casos/{T}/_raw_filings)")
    parser.add_argument("--company-name", default="", help="Canonical company name hint for issuer matching")
    parser.add_argument("--exchange", default="", help="Exchange hint (e.g., ASX, NYSE)")
    parser.add_argument("--country", default="", help="Country hint (e.g., AU, US)")
    parser.add_argument("--web-ir", default="", help="Investor Relations base URL (override)")
    parser.add_argument("--max-transcripts", type=int, default=8, help="Maximum transcripts to include")
    parser.add_argument("--max-presentations", type=int, default=8, help="Maximum presentations to include")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    case_dir = Path(args.case_dir).resolve()
    if args.raw_dir:
        raw_dir = Path(args.raw_dir).resolve()
    else:
        raw_dir = case_dir.parent / "_raw_filings"  # ticker-level
    raw_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    sec_ctx = read_sec_context(case_dir)
    sec_empresa = sec_ctx.get("empresa", {}) if isinstance(sec_ctx, dict) else {}
    src_empresa = read_sources_context(case_dir)

    exchange = (
        normalize_exchange(args.exchange)
        or normalize_exchange(src_empresa.get("bolsa"))
        or normalize_exchange(sec_empresa.get("bolsa"))
    )
    country = (
        normalize_country(args.country)
        or normalize_country(src_empresa.get("pais"))
        or normalize_country(sec_empresa.get("pais"))
    )

    empresa: Dict[str, Any] = {
        "ticker": ticker,
        "nombre": src_empresa.get("nombre") or sec_empresa.get("nombre") or ticker,
        "cik": sec_empresa.get("cik"),
        "web_ir": normalize_web_ir(src_empresa.get("web_ir")) or normalize_web_ir(sec_empresa.get("web_ir")),
        "bolsa": exchange,
        "pais": country,
    }
    if clean_ws(args.company_name):
        empresa["nombre"] = clean_ws(args.company_name)
    for key in ("sector", "industria"):
        if src_empresa.get(key):
            empresa[key] = src_empresa[key]
        elif sec_empresa.get(key):
            empresa[key] = sec_empresa[key]
    web_ir_override = normalize_web_ir(args.web_ir)
    if web_ir_override:
        empresa["web_ir"] = web_ir_override

    out: Dict[str, Any] = {
        "version_esquema": "SourcesPack_v1",
        "fetcher": "TRANSCRIPT_FINDER",
        "ticker": ticker,
        "empresa": empresa,
        "fecha_corte": today_iso(),
        "fuentes": [],
        "fuentes_descartadas": [],
        "faltantes": [],
        "cache_stats": {
            "archivos_descargados": 0,
            "archivos_fallidos": 0,
            "directorio": str(raw_dir.relative_to(REPO_ROOT)) if raw_dir.is_relative_to(REPO_ROOT) else "_raw_filings/",
        },
        "sub_agent": "TRANSCRIPT_FINDER",
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

    def log_lim(msg: str) -> None:
        out.setdefault("log", {}).setdefault("limitaciones", []).append(msg)

    target_aliases, target_identity_quality = _build_target_aliases(
        ticker=ticker,
        empresa=empresa,
        sec_empresa=sec_empresa if isinstance(sec_empresa, dict) else {},
        src_empresa=src_empresa if isinstance(src_empresa, dict) else {},
    )
    if target_identity_quality == "WEAK":
        log_lim(
            "Transcript issuer matching running in fail-closed mode: "
            "target identity is weak (ticker-only or short alias)."
        )

    # --------------------
    # 1) Earnings transcripts (Fintool)
    # --------------------
    transcript_source_idx = 1
    rejected_transcripts_entity = 0
    if exchange and exchange in NON_US_EXCHANGES:
        periods = []
        log_lim(
            f"Skipping Fintool transcripts for non-US exchange ({exchange}); "
            "coverage expected from IR presentations/announcements."
        )
    else:
        try:
            transcript_index_url = f"https://fintool.com/app/research/companies/{ticker}/documents/transcripts"
            transcript_index_html = request_text(session, transcript_index_url)
            periods = extract_transcript_periods(transcript_index_html, ticker)[: args.max_transcripts]
        except Exception as exc:
            periods = []
            log_lim(f"No se pudo cargar índice de transcripts Fintool: {exc}")
    for period_slug in periods:
        source_id = f"SRC_TR_{transcript_source_idx:03d}"
        transcript_source_idx += 1
        period_norm = normalize_period(period_slug)
        transcript_url = f"https://fintool.com/app/research/companies/{ticker}/documents/transcripts/{period_slug}"

        try:
            html = request_text(session, transcript_url)
            next_data = parse_next_data(html)
            page_props = next_data.get("props", {}).get("pageProps", {})
            page_ticker = clean_ws(str(page_props.get("ticker") or "")).upper()

            display_period = normalize_period(page_props.get("displayPeriod") or period_slug)
            title = clean_ws(str(page_props.get("title") or f"{ticker} Earnings Call Transcript - {display_period}"))
            published = parse_human_date(page_props.get("publishedAt")) or parse_human_date(
                BeautifulSoup(html, "html.parser").find("meta", attrs={"property": "article:published_time"}).get("content")
                if BeautifulSoup(html, "html.parser").find("meta", attrs={"property": "article:published_time"})
                else None
            )
            transcript_text = build_transcript_text(page_props)
            first_line = clean_ws(transcript_text.splitlines()[0]) if transcript_text else ""

            issuer_candidates: List[str] = []
            company_name = clean_ws(str(page_props.get("companyName") or ""))
            if company_name:
                issuer_candidates.append(company_name)
            issuer_candidates.extend(_extract_company_from_title(title))
            issuer_candidates.extend(_extract_company_from_title(first_line))
            deduped_candidates: List[str] = []
            seen_norm = set()
            for cand in issuer_candidates:
                norm = _normalize_entity_name(cand)
                if not norm or norm in seen_norm:
                    continue
                seen_norm.add(norm)
                deduped_candidates.append(cand)
            issuer_candidates = deduped_candidates

            if target_identity_quality == "WEAK":
                rejected_transcripts_entity += 1
                reject_reason = (
                    "target identity weak (ticker-only/short alias); "
                    "fail-closed to avoid ticker collision"
                )
                out["fuentes_descartadas"].append(
                    {
                        "source_id": source_id,
                        "url": transcript_url,
                        "title": title,
                        "issuer_candidates": issuer_candidates,
                        "best_target": None,
                        "best_score": 0.0,
                        "reason": reject_reason,
                        "status": "REJECTED_ENTITY_MISMATCH",
                    }
                )
                log_lim(f"{source_id} rejected entity mismatch: {reject_reason}")
                continue

            issuer_match, issuer_score, issuer_best_target, issuer_reason = _issuer_match_decision(
                target_aliases=target_aliases,
                issuer_candidates=issuer_candidates,
                ticker=ticker,
            )
            if issuer_match != "MATCH":
                rejected_transcripts_entity += 1
                if page_ticker and page_ticker == ticker:
                    issuer_reason = f"{issuer_reason}; ticker collision detected (same ticker, different issuer text)"
                out["fuentes_descartadas"].append(
                    {
                        "source_id": source_id,
                        "url": transcript_url,
                        "title": title,
                        "issuer_candidates": issuer_candidates,
                        "best_target": issuer_best_target or None,
                        "best_score": round(float(issuer_score or 0.0), 3),
                        "reason": issuer_reason,
                        "status": "REJECTED_ENTITY_MISMATCH",
                    }
                )
                log_lim(
                    f"{source_id} rejected entity mismatch: {issuer_reason} "
                    f"(candidates={issuer_candidates[:3]})"
                )
                continue

            base = f"{source_id}_TRANSCRIPT_{safe_slug(display_period)}"
            html_name = f"{base}.html"
            txt_name = f"{base}.txt"
            (raw_dir / html_name).write_text(html, encoding="utf-8")
            (raw_dir / txt_name).write_text(transcript_text, encoding="utf-8")

            executive_summary = page_props.get("executiveSummary") or []
            notes = ""
            if isinstance(executive_summary, list) and executive_summary:
                notes = clean_ws(str(executive_summary[0]))[:280]
            if not notes:
                notes = f"Transcript for {display_period} from Fintool."

            extractos: List[Dict[str, str]] = []
            if isinstance(executive_summary, list):
                for chunk in executive_summary[:2]:
                    chunk_text = clean_ws(str(chunk))
                    if chunk_text:
                        extractos.append(
                            {
                                "texto": first_25_words(chunk_text),
                                "ubicacion": "Executive Summary",
                                "tema": infer_tema(chunk_text),
                            }
                        )
            if not extractos:
                extractos.append(
                    {
                        "texto": first_25_words(transcript_text),
                        "ubicacion": "Full transcript",
                        "tema": "otro",
                    }
                )

            out["fuentes"].append(
                {
                    "source_id": source_id,
                    "categoria": "TRANSCRIPCION",
                    "tipo": "EARNINGS_TRANSCRIPT",
                    "titulo": f"Earnings Call Transcript - {display_period}",
                    "url": transcript_url,
                    "local_path": raw_dir_local_path(raw_dir, txt_name),
                    "publicador": "Fintool",
                    "fecha_publicacion": published,
                    "fecha_evento": published,
                    "fecha_recuperacion": today_iso(),
                    "idioma": "en",
                    "fiabilidad": "A",
                    "relevancia": "ALTA" if transcript_source_idx <= 5 else "MEDIA",
                    "periodo": display_period,
                    "contenido_disponible": True,
                    "notas": notes,
                    "extractos": extractos,
                    "extraction_status": "OK",
                    "extraction_reason": "",
                    "extractor": "html_text",
                    "text_chars": len(transcript_text),
                    "content_hash": _content_hash(transcript_text),
                    "issuer_match": issuer_match,
                    "issuer_match_score": round(issuer_score, 3),
                    "issuer_match_reason": issuer_reason,
                }
            )
            out["cache_stats"]["archivos_descargados"] += 1
        except Exception as exc:
            out["cache_stats"]["archivos_fallidos"] += 1
            log_lim(f"{source_id} ({transcript_url}) error descarga/procesado: {exc}")

    # --------------------
    # 2) Investor presentations (Company IR)
    # --------------------
    presentation_source_idx = 1
    presentation_rows: List[Tuple[str, str, Optional[str], str, str]] = []
    presentation_rejected_rows: List[Dict[str, str]] = []
    web_ir_to_use = web_ir_override or empresa.get("web_ir")
    if web_ir_to_use:
        try:
            # Import from same directory (runners are launched as subprocesses)
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "ir_url_resolver",
                str(Path(__file__).resolve().parent / "ir_url_resolver.py"),
            )
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            resolved = _mod.resolve_ir_base_url(web_ir_to_use, session, timeout=10)
            if resolved and resolved != normalize_web_ir(web_ir_to_use):
                print(f"[transcript_finder] Resolved IR: {web_ir_to_use} -> {resolved}", file=sys.stderr)
                web_ir_to_use = resolved
                empresa["web_ir"] = resolved
        except Exception as exc:
            print(f"[transcript_finder] IR resolver failed: {exc}", file=sys.stderr)
    ir_pages = build_ir_pages(web_ir_to_use)
    if not ir_pages:
        log_lim(f"Sin web_ir en contexto local para {ticker}; no se pudo intentar scrapeo de presentaciones IR.")
    else:
        for ir_page in ir_pages:
            try:
                ir_html = request_text(session, ir_page)
                rows, rejected_rows = extract_presentation_rows(ir_html, ir_page)
                presentation_rows.extend(rows)
                for rej in rejected_rows:
                    rej["discovered_from"] = ir_page
                presentation_rejected_rows.extend(rejected_rows)
            except Exception as exc:
                log_lim(f"No se pudo cargar/scrapear IR page {ir_page}: {exc}")
    if presentation_rejected_rows:
        for idx, rej in enumerate(presentation_rejected_rows, 1):
            out["fuentes_descartadas"].append(
                {
                    "source_id": f"SRC_PR_REJ_{idx:03d}",
                    "url": rej.get("url"),
                    "title": rej.get("title"),
                    "status": "REJECTED_NAVIGATION_OR_INDEX_HTML",
                    "reason": rej.get("reason") or "navigation_or_index_html",
                    "detail": rej.get("detail"),
                    "discovered_from": rej.get("discovered_from"),
                }
            )
        log_lim(
            "Investor presentation HTML rows discarded as navigation/index: "
            f"{len(presentation_rejected_rows)}"
        )
    if presentation_rows:
        dedup_by_url = {row[0]: row for row in presentation_rows}
        dedup_by_name: Dict[str, Tuple[str, str, Optional[str], str, str]] = {}
        for row in dedup_by_url.values():
            basename = Path(urlparse(row[0]).path).name.lower()
            key = basename or row[0]
            if key not in dedup_by_name:
                dedup_by_name[key] = row
        presentation_rows = sorted(
            dedup_by_name.values(),
            key=lambda x: (
                x[2] or "0000-00-00",
                period_sort_key((x[1] or "").lower()),
            ),
            reverse=True,
        )[: args.max_presentations]

    for href, period, fecha_evento, row_text, doc_kind in presentation_rows:
        source_id = f"SRC_PR_{presentation_source_idx:03d}"
        presentation_source_idx += 1
        source_tipo = classify_presentation_source_type(row_text or "", href, row_text or "")

        try:
            base = f"{source_id}_PRESENTATION_{safe_slug(period)}"
            txt_name = f"{base}.txt"
            if doc_kind == "pdf":
                pdf_data = request_bytes(session, href)
                pdf_reader = PdfReader(BytesIO(pdf_data))
                slide_text_chunks: List[str] = []
                for page in pdf_reader.pages:
                    page_text = page.extract_text() or ""
                    page_text = clean_ws(page_text)
                    if page_text:
                        slide_text_chunks.append(page_text)
                slide_text = "\n\n".join(slide_text_chunks).strip()

                if not slide_text:
                    raise ValueError("PDF sin texto extraíble")

                pdf_name = f"{base}.pdf"
                (raw_dir / pdf_name).write_bytes(pdf_data)
                (raw_dir / txt_name).write_text(slide_text + "\n", encoding="utf-8")

                file_name = unquote(Path(urlparse(href).path).name).replace("+", " ")
                pretty_name = (
                    re.sub(r"\.pdf$", "", file_name, flags=re.IGNORECASE).strip()
                    or f"{ticker} Presentation {period}"
                )
            else:
                html = request_text(session, href)
                slide_text = strip_html_to_text(html).strip()
                if not slide_text:
                    raise ValueError("HTML sin texto extraíble")
                if is_navigation_like_source(clean_ws(row_text) or period, slide_text, href):
                    log_lim(f"{source_id} ({href}) descartada por contenido navegación/índice.")
                    continue

                html_name = f"{base}.html"
                (raw_dir / html_name).write_text(html, encoding="utf-8")
                (raw_dir / txt_name).write_text(slide_text + "\n", encoding="utf-8")
                pretty_name = clean_ws(row_text) or f"{ticker} IR Update {period}"
            notes = clean_ws(row_text)[:280] if row_text else f"Investor presentation for {period}."

            out["fuentes"].append(
                {
                    "source_id": source_id,
                    "categoria": "IR",
                    "tipo": source_tipo,
                    "titulo": pretty_name,
                    "url": href,
                    "local_path": raw_dir_local_path(raw_dir, txt_name),
                    "publicador": "Company IR",
                    "fecha_publicacion": fecha_evento,
                    "fecha_evento": fecha_evento,
                    "fecha_recuperacion": today_iso(),
                    "idioma": "en",
                    "fiabilidad": "A",
                    "relevancia": "ALTA" if presentation_source_idx <= 4 else "MEDIA",
                    "periodo": period,
                    "contenido_disponible": True,
                    "notas": f"{notes} Format: {doc_kind.upper()}.",
                    "extractos": [
                        {
                            "texto": first_25_words(slide_text),
                            "ubicacion": "Slides",
                            "tema": infer_tema(slide_text),
                        }
                    ],
                    "extraction_status": "OK",
                    "extraction_reason": "",
                    "extractor": "pypdf" if doc_kind == "pdf" else "html_text",
                    "text_chars": len(slide_text),
                    "content_hash": _content_hash(slide_text),
                    "issuer_match": "UNKNOWN",
                    "issuer_match_score": 0.0,
                    "issuer_match_reason": "Not evaluated for investor presentation.",
                }
            )
            out["cache_stats"]["archivos_descargados"] += 1
        except Exception as exc:
            out["cache_stats"]["archivos_fallidos"] += 1
            log_lim(f"{source_id} ({href}) error descarga/procesado: {exc}")

    # --------------------
    # 2b) SEC cache fallback (when transcript/presentation coverage is short)
    # --------------------
    country_norm = clean_ws(str(empresa.get("pais") or "")).upper()
    exchange_norm = clean_ws(str(empresa.get("bolsa") or "")).upper()
    non_us_hint = (
        (country_norm and country_norm not in US_COUNTRIES)
        or exchange_norm in NON_US_EXCHANGES
        or (not empresa.get("cik") and country_norm not in US_COUNTRIES)
    )
    target_min_sources = 4 if non_us_hint else 6
    if len(out["fuentes"]) < target_min_sources:
        existing_paths = {
            str(src.get("local_path"))
            for src in out["fuentes"]
            if isinstance(src, dict) and src.get("local_path")
        }
        fallback_idx = 1
        for sec_src in (sec_ctx.get("fuentes") or []):
            if len(out["fuentes"]) >= target_min_sources:
                break
            if not isinstance(sec_src, dict):
                continue
            local_path = str(sec_src.get("local_path") or "").strip()
            if not local_path or local_path in existing_paths:
                continue
            text_path = Path(local_path)
            if not text_path.is_absolute():
                text_path = case_dir / local_path
            if not text_path.exists():
                continue
            try:
                raw_text = text_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            cleaned = clean_ws(raw_text)
            if len(cleaned) < 40:
                continue

            source_id = f"SRC_PR_FBK_{fallback_idx:03d}"
            fallback_idx += 1
            period = normalize_period(sec_src.get("fecha_publicacion") or today_iso())
            tipo_sec = clean_ws(str(sec_src.get("tipo") or "SEC"))
            fallback_tipo = classify_presentation_source_type(
                clean_ws(str(sec_src.get("titulo") or tipo_sec)),
                clean_ws(str(sec_src.get("url") or "")),
                clean_ws(str(sec_src.get("notas") or "")),
            )
            out["fuentes"].append(
                {
                    "source_id": source_id,
                    "categoria": "IR",
                    "tipo": fallback_tipo,
                    "titulo": f"SEC Filing Context - {tipo_sec} - {period}",
                    "url": sec_src.get("url") or "",
                    "local_path": local_path,
                    "publicador": "SEC (cache fallback)",
                    "fecha_publicacion": sec_src.get("fecha_publicacion"),
                    "fecha_evento": sec_src.get("fecha_publicacion"),
                    "fecha_recuperacion": today_iso(),
                    "idioma": "en",
                    "fiabilidad": "B",
                    "relevancia": "MEDIA",
                    "periodo": period,
                    "contenido_disponible": True,
                    "notas": "Fallback desde SEC cache para completar cobertura mínima de contexto.",
                    "extractos": [
                        {
                            "texto": first_25_words(cleaned),
                            "ubicacion": "SEC cached filing",
                            "tema": infer_tema(cleaned),
                        }
                    ],
                    "extraction_status": "OK",
                    "extraction_reason": "",
                    "extractor": "sec_cache",
                    "text_chars": len(cleaned),
                    "content_hash": _content_hash(cleaned),
                    "issuer_match": "UNKNOWN",
                    "issuer_match_score": 0.0,
                    "issuer_match_reason": "Inherited from SEC cache fallback.",
                }
            )
            out["cache_stats"]["archivos_descargados"] += 1
            existing_paths.add(local_path)

    # --------------------
    # 3) Missing items
    # --------------------
    transcript_count = sum(1 for src in out["fuentes"] if src.get("tipo") == "EARNINGS_TRANSCRIPT")
    presentation_count = sum(1 for src in out["fuentes"] if src.get("tipo") == "INVESTOR_PRESENTATION")

    if transcript_count == 0:
        if rejected_transcripts_entity > 0:
            add_missing(
                "Earnings transcripts",
                "ALTO",
                f"Se rechazaron {rejected_transcripts_entity} transcripts por mismatch de emisor.",
                f"Verificar ticker/exchange/issuer de {ticker} y revisar manualmente fuentes IR/transcripts.",
            )
        else:
            add_missing(
                "Earnings transcripts",
                "CRITICO",
                "No se localizaron transcripts públicas para el ticker.",
                f"Buscar en IR de {ticker}, Fintool o Seeking Alpha; si hay paywall, solicitar transcript a IR.",
            )
    elif transcript_count < 4:
        add_missing(
            "Últimas 4 earnings transcripts",
            "ALTO",
            f"Solo se localizaron {transcript_count} transcripts en fuentes públicas.",
            "Completar en proveedor alternativo (Seeking Alpha/FactSet) o solicitar histórico a Investor Relations.",
        )

    if presentation_count == 0:
        add_missing(
            "Investor presentations",
            "ALTO",
            "No se localizaron presentaciones públicas accesibles.",
            f"Revisar IR de {ticker} > News/Events/Presentations o solicitar deck al equipo de IR.",
        )

    out_path = case_dir / "_transcript_finder_output.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ticker": ticker,
                "case_dir": str(case_dir),
                "output": str(out_path),
                "sources": len(out["fuentes"]),
                "transcripts": transcript_count,
                "transcripts_rejected_entity": rejected_transcripts_entity,
                "presentations": presentation_count,
                "downloaded": out["cache_stats"]["archivos_descargados"],
                "failed": out["cache_stats"]["archivos_fallidos"],
                "missing": len(out["faltantes"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
