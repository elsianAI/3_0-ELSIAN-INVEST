"""EU regulators filing acquisition — stub for manual bootstrap.

For EU cases, filings are placed manually in cases/{TICKER}/filings/.
This module detects existing content and generates a manifest without downloading.
Future: add fetchers for AMF, CNMV, FCA when needed.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict

from deterministic.src.schemas import AcquisitionResult


def fetch_eu_manual(case_dir: str) -> AcquisitionResult:
    """Generate manifest from manually placed filings.

    Reads case.json for expected count, scans filings/ for actual files.
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

    # Count existing filings
    existing_files: list[str] = []
    if filings_dir.exists():
        for f in sorted(filings_dir.iterdir()):
            if f.is_file() and f.suffix in {
                ".md",
                ".txt",
                ".htm",
                ".html",
                ".pdf",
            }:
                existing_files.append(f.name)

    downloaded = len(existing_files)
    coverage_pct = (
        (downloaded / expected_count * 100.0) if expected_count > 0 else 0.0
    )

    gaps = []
    if downloaded < expected_count:
        gaps.append(
            f"Expected {expected_count} filings, found {downloaded}. "
            f"Place missing filings in {filings_dir}/"
        )

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
            f"Expected: {expected_count}."
        ),
        download_date=dt.date.today().isoformat(),
    )
