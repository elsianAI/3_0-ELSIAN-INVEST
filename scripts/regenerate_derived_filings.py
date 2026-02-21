#!/usr/bin/env python3
"""One-shot script to generate .ixbrl.json and .clean.md for existing filings.

Scans all _raw_filings directories and generates the new derived files
for any .htm/.html financial filing that doesn't already have them.

Usage:
    python3 scripts/regenerate_derived_filings.py [--ticker INMD] [--force]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT))

from scripts.runners.ixbrl_extractor import extract_ixbrl_facts
from scripts.runners.clean_md_extractor import extract_financial_tables

import json

# Filing types that contain financial statements
FINANCIAL_TYPES = re.compile(r"10-K|10K|20-F|20F|10-Q|10Q|6-K|6K", re.IGNORECASE)


def process_file(htm_path: Path, force: bool = False) -> dict:
    """Generate .ixbrl.json and .clean.md for one .htm file."""
    stem = htm_path.stem  # e.g., SRC_002_20-F_FY2025
    results = {"file": htm_path.name, "ixbrl": "skipped", "clean_md": "skipped"}

    # Check if this is a financial filing type
    if not FINANCIAL_TYPES.search(stem):
        results["ixbrl"] = "not_financial"
        results["clean_md"] = "not_financial"
        return results

    # iXBRL extraction
    ixbrl_path = htm_path.parent / f"{stem}.ixbrl.json"
    if force or not ixbrl_path.exists():
        try:
            data = extract_ixbrl_facts(htm_path)
            ixbrl_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            n_facts = data["meta"]["total_relevant_tags"]
            n_concepts = len(data["meta"]["canonical_concepts_found"])
            results["ixbrl"] = f"ok ({n_facts} facts, {n_concepts} concepts)"
        except Exception as e:
            results["ixbrl"] = f"error: {e}"

    # .clean.md extraction
    clean_path = htm_path.parent / f"{stem}.clean.md"
    if force or not clean_path.exists():
        try:
            md = extract_financial_tables(htm_path)
            clean_path.write_text(md, encoding="utf-8")
            results["clean_md"] = f"ok ({len(md):,} chars)"
        except Exception as e:
            results["clean_md"] = f"error: {e}"

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate .ixbrl.json + .clean.md for existing filings")
    parser.add_argument("--ticker", default="", help="Process only this ticker (default: all)")
    parser.add_argument("--force", action="store_true", help="Regenerate even if files already exist")
    args = parser.parse_args()

    casos_dir = REPO_ROOT / "casos"
    if not casos_dir.exists():
        print("ERROR: casos/ directory not found")
        return 1

    # Find all _raw_filings directories
    raw_dirs = sorted(casos_dir.glob("*/_raw_filings"))
    if args.ticker:
        raw_dirs = [d for d in raw_dirs if d.parent.name.upper() == args.ticker.upper()]

    if not raw_dirs:
        print(f"No _raw_filings directories found" +
              (f" for ticker {args.ticker}" if args.ticker else ""))
        return 1

    total = 0
    success = 0
    for raw_dir in raw_dirs:
        ticker = raw_dir.parent.name
        htm_files = sorted(raw_dir.glob("*.htm")) + sorted(raw_dir.glob("*.html"))
        if not htm_files:
            continue

        print(f"\n{'='*60}")
        print(f"Ticker: {ticker} — {len(htm_files)} .htm files")
        print(f"{'='*60}")

        for htm in htm_files:
            total += 1
            result = process_file(htm, force=args.force)
            ixbrl_ok = result["ixbrl"].startswith("ok")
            clean_ok = result["clean_md"].startswith("ok")
            if ixbrl_ok or clean_ok:
                success += 1

            status = "✓" if (ixbrl_ok or clean_ok) else "—"
            print(f"  {status} {result['file']}")
            print(f"      iXBRL: {result['ixbrl']}")
            print(f"      clean: {result['clean_md']}")

    print(f"\nDone: {success}/{total} files processed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
