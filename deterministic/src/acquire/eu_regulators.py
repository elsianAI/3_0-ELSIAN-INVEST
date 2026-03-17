"""EU regulators filing acquisition — HTTP download + raw filings import.

For EU cases, filings are acquired via two mechanisms (in order):

1. **HTTP download** (preferred): ``case.json`` declares a ``filings_sources``
   list.  Each entry has ``url``, ``filename``, ``filing_type`` and optionally
   ``period_end``.  This module downloads any missing files using a rate-limited
   HTTP client, then converts PDFs to ``.txt`` and HTML to ``.clean.md``.

2. **Raw filings import** (legacy/fallback): when ``raw_filings_dir`` is
   configured in case.json and the local ``filings/`` directory is still empty
   after the HTTP step, this module copies the relevant raw files from the
   pipeline 3.0 IR crawling output (``casos/{TICKER}/_raw_filings/``).

Both mechanisms are fully generic — any EU case can use them by populating
``filings_sources`` and/or ``raw_filings_dir`` in its ``case.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from deterministic.src.acquire.html_to_markdown import convert as html_to_markdown
from deterministic.src.acquire.pdf_to_text import extract_pdf_text_from_file
from deterministic.src.schemas import AcquisitionResult


# File types that the extraction pipeline can consume.
_TEXT_SUFFIXES = {".md", ".txt", ".htm", ".html", ".pdf"}

# ── HTTP client ──────────────────────────────────────────────────────

USER_AGENT = "ELSIAN-INVEST-Bot/1.0 (research; bot@elsian-invest.local)"
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT = 60
_RATE_LIMIT = 0.5  # seconds between requests — be polite with EU IR sites


def _http_get(url: str, retries: int = 2) -> Optional[bytes]:
    """Download *url* and return raw bytes, or None on failure."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            if attempt == retries:
                print(f"  [eu_regulators] download failed: {url} — {exc}")
                return None
            time.sleep(1.0)
    return None  # unreachable


# ── HTTP source download ─────────────────────────────────────────────


def _download_sources(sources: List[Dict[str, Any]], filings_dir: Path) -> int:
    """Download each entry in *sources* into *filings_dir* if not already present.

    Each source dict must have ``url`` and ``filename`` keys.  After download:
    - PDFs are extracted to a sibling ``.txt`` file.
    - HTML files are converted to a sibling ``.clean.md`` file.

    Returns the number of new files downloaded.
    """
    filings_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0

    for src in sources:
        url: str = src.get("url", "").strip()
        filename: str = src.get("filename", "").strip()
        if not url or not filename:
            continue

        dst = filings_dir / filename
        if dst.exists():
            continue  # already present — skip

        print(f"  [eu_regulators] downloading {filename} …")
        content = _http_get(url)
        if content is None:
            continue

        dst.write_bytes(content)
        downloaded += 1
        time.sleep(_RATE_LIMIT)

        suffix = dst.suffix.lower()

        # PDF → .txt
        if suffix == ".pdf":
            txt_path = filings_dir / (dst.stem + ".txt")
            if not txt_path.exists():
                text = extract_pdf_text_from_file(str(dst))
                if text.strip():
                    txt_path.write_text(text, encoding="utf-8")

        # HTML → .clean.md
        elif suffix in {".htm", ".html"}:
            md_path = filings_dir / (dst.stem + ".clean.md")
            if not md_path.exists():
                clean_md = html_to_markdown(dst)
                if clean_md and clean_md.strip():
                    md_path.write_text(clean_md, encoding="utf-8")

    return downloaded


def _import_raw_filings(raw_dir: Path, filings_dir: Path) -> int:
    """Copy raw filings into the deterministic filings/ directory.

    Selects ANNUAL_REPORT and REGULATORY_FILING files (excluding
    duplicate SRC_SEC_* and SRC_PR_* channel variants).  Copies .txt
    and .pdf files, generates .clean.md from .htm/.html via
    html_to_markdown, and generates .txt from .pdf when missing.

    Returns the number of source groups imported.
    """
    if not raw_dir.exists():
        return 0

    filings_dir.mkdir(parents=True, exist_ok=True)

    # Gather unique source groups (SRC_NNN prefix), excluding
    # duplicate channel variants (SRC_SEC_*, SRC_PR_*).
    groups: Dict[str, List[Path]] = {}
    for f in sorted(raw_dir.iterdir()):
        if not f.is_file():
            continue
        name = f.name
        # Skip channel duplicates
        if name.startswith("SRC_SEC_") or name.startswith("SRC_PR_"):
            continue
        # Extract group prefix (e.g. SRC_001)
        m = re.match(r"(SRC_\d+)", name)
        if not m:
            # Also handle standalone files like tp-press-release-*.pdf
            groups.setdefault(name.split(".")[0], []).append(f)
            continue
        groups.setdefault(m.group(1), []).append(f)

    imported = 0
    for _prefix, files in sorted(groups.items()):
        # Classify files by extension
        txt_files = [f for f in files if f.suffix == ".txt"]
        pdf_files = [f for f in files if f.suffix == ".pdf"]
        htm_files = [f for f in files if f.suffix in {".htm", ".html"}]
        md_files = [f for f in files if f.name.endswith(".clean.md")]

        # Must have at least a .txt or .pdf to be useful
        if not txt_files and not pdf_files and not htm_files:
            continue

        # Copy .txt files
        for src in txt_files:
            dst = filings_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

        # Copy .pdf files
        for src in pdf_files:
            dst = filings_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

        # Generate .txt from .pdf if no .txt exists
        if not txt_files and pdf_files:
            for pdf in pdf_files:
                txt_name = pdf.stem + ".txt"
                txt_dst = filings_dir / txt_name
                if not txt_dst.exists():
                    text = extract_pdf_text_from_file(str(pdf))
                    if text.strip():
                        txt_dst.write_text(text, encoding="utf-8")

        # Copy existing .clean.md files
        for src in md_files:
            dst = filings_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

        # Generate .clean.md from .htm/.html if no .clean.md exists
        if not md_files and htm_files:
            for htm in htm_files:
                md_name = htm.stem + ".clean.md"
                # Avoid generating .clean.clean.md
                if htm.name.endswith(".clean.md"):
                    continue
                md_dst = filings_dir / md_name
                if not md_dst.exists():
                    clean_md = html_to_markdown(htm)
                    if clean_md and clean_md.strip():
                        md_dst.write_text(clean_md, encoding="utf-8")

        imported += 1

    return imported


def fetch_eu_manual(case_dir: str) -> AcquisitionResult:
    """Acquire filings for an EU case.

    Acquisition order:

    1. **HTTP download** — if ``filings_sources`` is defined in case.json,
       download any missing files from the declared URLs.
    2. **Raw filings import** — if ``raw_filings_dir`` is configured and
       ``filings/`` is still empty after step 1, copy files from the local
       raw filings directory (pipeline 3.0 IR crawl output).

    Both steps are idempotent: already-present files are never re-downloaded
    or re-copied.
    """
    case_path = Path(case_dir)
    filings_dir = case_path / "filings"

    # Read case.json
    case_json_path = case_path / "case.json"
    case_config: Dict[str, Any] = {}
    if case_json_path.exists():
        case_config = json.loads(case_json_path.read_text(encoding="utf-8"))

    ticker = case_config.get("ticker", case_path.name)
    expected_count = case_config.get("filings_expected_count", 0)

    filings_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: HTTP download from filings_sources ───────────────────
    http_downloaded = 0
    sources: List[Dict[str, Any]] = case_config.get("filings_sources", [])
    if sources:
        http_downloaded = _download_sources(sources, filings_dir)

    # ── Step 2: raw_filings_dir import (fallback / supplement) ───────
    # Run if filings/ is still empty after HTTP step.
    imported_count = 0
    has_existing = any(
        f.is_file() and f.suffix in _TEXT_SUFFIXES
        for f in filings_dir.iterdir()
    )
    if not has_existing:
        raw_dir_rel = case_config.get("raw_filings_dir", "")
        if raw_dir_rel:
            raw_dir = (case_path / raw_dir_rel).resolve()
            imported_count = _import_raw_filings(raw_dir, filings_dir)

    # ── Inventory ────────────────────────────────────────────────────
    existing_files: List[str] = sorted(
        f.name
        for f in filings_dir.iterdir()
        if f.is_file() and f.suffix in _TEXT_SUFFIXES
    )

    found = len(existing_files)
    coverage_pct = (found / expected_count * 100.0) if expected_count > 0 else 0.0

    gaps: List[str] = []
    if found == 0:
        gaps.append(
            f"No filings found. Add filings_sources URLs to case.json or "
            f"place files in {filings_dir}/."
        )
    elif found < expected_count:
        gaps.append(
            f"Expected {expected_count} filings, found {found}."
        )

    notes_parts = [f"EU acquisition. {found} filings in filings/."]
    if http_downloaded:
        notes_parts.append(f"HTTP-downloaded: {http_downloaded} new file(s).")
    if imported_count:
        notes_parts.append(f"Imported {imported_count} group(s) from raw_filings_dir.")
    notes_parts.append(f"Expected: {expected_count}.")

    return AcquisitionResult(
        ticker=ticker,
        source="eu_manual",
        filings_downloaded=found,
        filings_failed=0,
        filings_coverage_pct=round(min(coverage_pct, 100.0), 1),
        coverage={
            "http": {
                "sources_declared": len(sources),
                "downloaded_new": http_downloaded,
            },
            "raw_import": {
                "groups_imported": imported_count,
            },
            "total": {
                "expected": expected_count,
                "found": found,
                "files": existing_files,
            },
        },
        gaps=gaps,
        notes=" ".join(notes_parts),
        download_date=dt.date.today().isoformat(),
    )
