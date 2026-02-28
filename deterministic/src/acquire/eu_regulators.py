"""EU regulators filing acquisition — import from raw filings.

For EU cases, filings come from the pipeline 3.0 IR crawling output
(``casos/{TICKER}/_raw_filings/``) or are placed manually in
``cases/{TICKER}/filings/``.

When ``raw_filings_dir`` is configured in case.json and the local
``filings/`` directory is empty, this module copies the relevant raw
files, generates ``.clean.md`` from any HTML siblings, and produces
a filing manifest.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

from deterministic.src.acquire.html_to_markdown import convert as html_to_markdown
from deterministic.src.acquire.pdf_to_text import extract_pdf_text_from_file
from deterministic.src.schemas import AcquisitionResult


# File types that the extraction pipeline can consume.
_TEXT_SUFFIXES = {".md", ".txt", ".htm", ".html", ".pdf"}


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

    If filings/ is empty and raw_filings_dir is configured in case.json,
    imports files from the raw filings directory.  Otherwise scans
    existing filings/ content and generates a manifest.
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

    # If filings/ is empty, try importing from raw_filings_dir
    filings_dir.mkdir(parents=True, exist_ok=True)
    has_existing = any(
        f.is_file() and f.suffix in _TEXT_SUFFIXES
        for f in filings_dir.iterdir()
    ) if filings_dir.exists() else False

    imported_count = 0
    if not has_existing:
        raw_dir_rel = case_config.get("raw_filings_dir", "")
        if raw_dir_rel:
            raw_dir = (case_path / raw_dir_rel).resolve()
            imported_count = _import_raw_filings(raw_dir, filings_dir)

    # Count existing filings
    existing_files: list[str] = []
    if filings_dir.exists():
        for f in sorted(filings_dir.iterdir()):
            if f.is_file() and f.suffix in _TEXT_SUFFIXES:
                existing_files.append(f.name)

    downloaded = len(existing_files)
    coverage_pct = (
        (downloaded / expected_count * 100.0) if expected_count > 0 else 0.0
    )

    gaps: list[str] = []
    if downloaded == 0:
        gaps.append(
            f"No filings found. Place files in {filings_dir}/ "
            f"or configure raw_filings_dir in case.json."
        )
    elif downloaded < expected_count:
        gaps.append(
            f"Expected {expected_count} filings, found {downloaded}. "
            f"Place missing filings in {filings_dir}/"
        )

    import_note = ""
    if imported_count > 0:
        import_note = f" Imported {imported_count} source groups from raw_filings_dir."

    return AcquisitionResult(
        ticker=ticker,
        source="eu_manual",
        filings_downloaded=downloaded,
        filings_failed=0,
        filings_coverage_pct=round(min(coverage_pct, 100.0), 1),
        coverage={
            "manual": {
                "expected": expected_count,
                "found": downloaded,
                "files": existing_files,
            }
        },
        gaps=gaps,
        notes=(
            f"EU manual bootstrap. {downloaded} filings found in filings/. "
            f"Expected: {expected_count}.{import_note}"
        ),
        download_date=dt.date.today().isoformat(),
    )
