"""CLI entry point for the deterministic extraction module.

Usage:
    python3 -m deterministic.cli acquire TZOO
    python3 -m deterministic.cli extract TZOO
    python3 -m deterministic.cli eval TZOO
    python3 -m deterministic.cli run TZOO
    python3 -m deterministic.cli run --all
    python3 -m deterministic.cli dashboard
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_case_dir(ticker: str) -> str:
    """Find the case directory for a ticker."""
    base = Path(__file__).parent / "cases" / ticker.upper()
    if base.exists():
        return str(base)
    # Try lowercase
    base_low = Path(__file__).parent / "cases" / ticker.lower()
    if base_low.exists():
        return str(base_low)
    return str(base)


def _get_pipeline():
    from deterministic.src.pipeline import DeterministicPipeline

    config_dir = str(Path(__file__).parent / "config")
    return DeterministicPipeline(config_dir=config_dir)


def cmd_acquire(args: argparse.Namespace) -> int:
    pipeline = _get_pipeline()
    case_dir = _find_case_dir(args.ticker)
    print(f"[acquire] {args.ticker} -> {case_dir}")

    result = pipeline.acquire(case_dir)
    print(f"  Source: {result.source}")
    print(f"  Downloaded: {result.filings_downloaded}")
    print(f"  Failed: {result.filings_failed}")
    print(f"  Coverage: {result.filings_coverage_pct}%")
    if result.gaps:
        print(f"  Gaps: {result.gaps}")
    print(f"  Notes: {result.notes}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    pipeline = _get_pipeline()
    case_dir = _find_case_dir(args.ticker)
    print(f"[extract] {args.ticker} -> {case_dir}")

    result = pipeline.extract(case_dir)
    print(f"  Filings used: {result.filings_used}")
    print(f"  Periods: {len(result.periods)}")
    for period_key, period in sorted(result.periods.items()):
        print(f"    {period_key}: {len(period.fields)} fields")
        for fname, fr in sorted(period.fields.items()):
            print(f"      {fname}: {fr.value} ({fr.scale}, {fr.confidence})")
    print(f"  Audit: extracted={result.audit.fields_extracted}, discarded={result.audit.fields_discarded}")

    # Write extraction result
    out_path = Path(case_dir) / "extraction_result.json"
    out_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Written: {out_path}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    if args.all:
        return cmd_dashboard_eval()

    pipeline = _get_pipeline()
    case_dir = _find_case_dir(args.ticker)
    print(f"[eval] {args.ticker} -> {case_dir}")

    report = pipeline.evaluate(case_dir)
    _print_eval_report(report)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.all:
        return cmd_dashboard(args)

    pipeline = _get_pipeline()
    case_dir = _find_case_dir(args.ticker)
    print(f"[run] {args.ticker} -> {case_dir}")
    print()

    acq, ext, evl = pipeline.run(case_dir)

    print(f"--- ACQUIRE ---")
    print(f"  Source: {acq.source}")
    print(f"  Downloaded: {acq.filings_downloaded}")
    print(f"  Coverage: {acq.filings_coverage_pct}%")
    print()

    print(f"--- EXTRACT ---")
    print(f"  Filings used: {ext.filings_used}")
    print(f"  Periods: {len(ext.periods)}")
    for period_key, period in sorted(ext.periods.items()):
        print(f"    {period_key}: {len(period.fields)} fields")
    print()

    print(f"--- EVALUATE ---")
    _print_eval_report(evl)

    # Write extraction result
    out_path = Path(case_dir) / "extraction_result.json"
    out_path.write_text(
        json.dumps(ext.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    pipeline = _get_pipeline()
    cases_dir = str(Path(__file__).parent / "cases")
    print(f"[dashboard] Evaluating all cases in {cases_dir}")
    print()

    report = pipeline.dashboard(cases_dir)

    # Print table
    print("DETERMINISTIC PIPELINE DASHBOARD")
    print("=================================")
    header = f"{'Case':<6} | {'Source':<8} | {'Filings':>7} | {'Periods':>7} | {'Expected':>8} | {'Matched':>7} | {'Score':>6}"
    sep = f"{'------':<6}-+-{'--------':<8}-+-{'-------':>7}-+-{'-------':>7}-+-{'--------':>8}-+-{'-------':>7}-+-{'------':>6}"
    print(header)
    print(sep)

    for row in report.rows:
        print(
            f"{row.ticker:<6} | {row.source:<8} | {row.filings:>7} | "
            f"{row.periods:>7} | {row.expected:>8} | {row.matched:>7} | "
            f"{row.score:>5.1f}%"
        )

    print(sep)
    print(
        f"{'TOTAL':<6} | {'':8} | {report.total_filings:>7} | "
        f"{report.total_periods:>7} | {report.total_expected:>8} | "
        f"{report.total_matched:>7} | {report.total_score:>5.1f}%"
    )

    return 0


def cmd_dashboard_eval() -> int:
    """Run eval --all: evaluate all cases."""
    pipeline = _get_pipeline()
    cases_dir = Path(__file__).parent / "cases"

    for case_subdir in sorted(cases_dir.iterdir()):
        if not case_subdir.is_dir():
            continue
        case_json = case_subdir / "case.json"
        if not case_json.exists():
            continue

        print(f"\n[eval] {case_subdir.name}")
        try:
            report = pipeline.evaluate(str(case_subdir))
            _print_eval_report(report)
        except Exception as exc:
            print(f"  ERROR: {exc}")

    return 0


def _print_eval_report(report) -> None:
    print(f"  Score: {report.score:.1f}% ({report.matched}/{report.total_expected})")
    print(f"  Matched: {report.matched}")
    print(f"  Wrong: {report.wrong}")
    print(f"  Missed: {report.missed}")
    print(f"  Extra: {report.extra}")
    if report.filings_coverage_pct > 0:
        print(f"  Filings coverage: {report.filings_coverage_pct:.1f}%")
    print(f"  Required fields coverage: {report.required_fields_coverage_pct:.1f}%")

    # Detail: show wrong and missed
    wrongs = [d for d in report.details if d.status == "wrong"]
    if wrongs:
        print(f"  WRONG ({len(wrongs)}):")
        for d in wrongs[:10]:
            print(f"    {d.period}/{d.field_name}: expected={d.expected}, actual={d.actual}")

    missings = [d for d in report.details if d.status == "missed"]
    if missings:
        print(f"  MISSED ({len(missings)}):")
        for d in missings[:10]:
            print(f"    {d.period}/{d.field_name}: expected={d.expected}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="deterministic",
        description="Deterministic financial data extraction pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # acquire
    p_acquire = subparsers.add_parser("acquire", help="Download filings for a case")
    p_acquire.add_argument("ticker", help="Ticker symbol (e.g. TZOO)")

    # extract
    p_extract = subparsers.add_parser("extract", help="Extract data from downloaded filings")
    p_extract.add_argument("ticker", help="Ticker symbol")

    # eval
    p_eval = subparsers.add_parser("eval", help="Evaluate extraction against expected.json")
    p_eval.add_argument("ticker", nargs="?", default="", help="Ticker symbol")
    p_eval.add_argument("--all", action="store_true", help="Evaluate all cases")

    # run
    p_run = subparsers.add_parser("run", help="Full pipeline: acquire + extract + evaluate")
    p_run.add_argument("ticker", nargs="?", default="", help="Ticker symbol")
    p_run.add_argument("--all", action="store_true", help="Run all cases")

    # dashboard
    subparsers.add_parser("dashboard", help="Summary dashboard of all cases")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "acquire": cmd_acquire,
        "extract": cmd_extract,
        "eval": cmd_eval,
        "run": cmd_run,
        "dashboard": cmd_dashboard,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
