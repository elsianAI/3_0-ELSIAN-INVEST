#!/usr/bin/env python3
"""Purge .clean.md files that fail the semantic quality gate.

Scans all *.clean.md under casos/ and _raw_filings/ and deletes those
that don't pass _is_clean_md_useful() — the same gate used at generation
time and by prompt_builder / sources_compiler.

Usage:
    python3 scripts/purge_bad_clean_md.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _is_clean_md_useful(text: str) -> bool:
    """Semantic quality gate (duplicated from clean_md_extractor to be standalone)."""
    import re

    if not text:
        return False
    if text.count("_Section not found in filing._") >= 4:
        return False
    numeric_rows = re.findall(r"^\|.*\d[\d,\.]*.*\|$", text, re.MULTILINE)
    if len(numeric_rows) < 5:
        return False
    for section_name in ("INCOME STATEMENT", "BALANCE SHEET", "CASH FLOW"):
        idx = text.find(f"## {section_name}")
        if idx < 0:
            continue
        next_section = text.find("\n## ", idx + 1)
        section_text = text[idx:next_section] if next_section > 0 else text[idx:]
        if "_Section not found" in section_text:
            continue
        section_numeric = re.findall(r"^\|.*\d[\d,\.]*.*\|$", section_text, re.MULTILINE)
        if len(section_numeric) >= 3:
            return True
    return False


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    scan_dirs = [REPO_ROOT / "casos"]
    all_clean = []
    for d in scan_dirs:
        if d.exists():
            all_clean.extend(d.rglob("*.clean.md"))

    purged = 0
    kept = 0
    for path in sorted(all_clean):
        try:
            content = path.read_text(errors="replace")
        except Exception:
            continue
        if _is_clean_md_useful(content):
            kept += 1
        else:
            purged += 1
            rel = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
            if dry_run:
                print(f"  [DRY-RUN] Would delete: {rel}")
            else:
                path.unlink()
                print(f"  Deleted: {rel}")

    print(f"\nTotal scanned: {purged + kept}")
    print(f"  Kept:    {kept}")
    print(f"  Purged:  {purged}")
    if dry_run:
        print("  (dry-run mode — no files were deleted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
