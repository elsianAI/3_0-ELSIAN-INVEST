#!/usr/bin/env python3
"""Compound PREFETCH runner — runs sec_fetcher, market_data, transcript_finder in parallel.

This is the orchestrator for the PREFETCH step in the pipeline DAG.
Each sub-runner is executed as a subprocess; failures are logged but
do not block other runners (best-effort).

Usage:
    python3 scripts/runners/prefetch_runner.py --ticker CRTO --case-dir casos/CRTO/2026-02-14_Codex
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import concurrent.futures
from pathlib import Path


RUNNERS = [
    "scripts/runners/sec_fetcher_v2_runner.py",
    "scripts/runners/market_data_v1_runner.py",
    "scripts/runners/transcript_finder_v2_runner.py",
]

RUNNER_EXTRA_ARGS = {
    "sec_fetcher_v2_runner.py": ["--exchange", "--country", "--web-ir"],
    "market_data_v1_runner.py": ["--exchange", "--country", "--web-ir"],
    "transcript_finder_v2_runner.py": ["--exchange", "--country", "--web-ir"],
}


def build_runner_cmd(
    runner_path: str, ticker: str, case_dir: str, cli_args: argparse.Namespace
) -> list[str]:
    cmd = [sys.executable, runner_path, "--ticker", ticker, "--case-dir", case_dir]
    runner_name = Path(runner_path).name
    for flag in RUNNER_EXTRA_ARGS.get(runner_name, []):
        attr = flag.lstrip("-").replace("-", "_")
        value = getattr(cli_args, attr, "")
        if value:
            cmd.extend([flag, value])
    return cmd


def run_one(
    runner_path: str,
    ticker: str,
    case_dir: str,
    workspace: Path,
    cli_args: argparse.Namespace,
) -> dict:
    full = workspace / runner_path
    if not full.exists():
        return {"runner": runner_path, "ok": False, "error": f"Not found: {full}"}

    try:
        cmd = build_runner_cmd(str(full), ticker, case_dir, cli_args)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(workspace),
        )
        return {
            "runner": runner_path,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:500],
            "stderr": proc.stderr[:500],
        }
    except subprocess.TimeoutExpired:
        return {"runner": runner_path, "ok": False, "error": "timeout"}
    except Exception as e:
        return {"runner": runner_path, "ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="PREFETCH — parallel source fetching")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--exchange", default="")
    parser.add_argument("--country", default="")
    parser.add_argument("--web-ir", default="")
    args = parser.parse_args()

    workspace = Path(__file__).resolve().parent.parent.parent
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(run_one, r, args.ticker, args.case_dir, workspace, args): r
            for r in RUNNERS
        }
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            status = "OK" if res["ok"] else "FAIL"
            print(f"[prefetch] {status}: {res['runner']}")
            if not res["ok"]:
                print(f"           {res.get('error', res.get('stderr', ''))[:200]}")
            results.append(res)

    ok_count = sum(1 for r in results if r["ok"])
    print(f"[prefetch] {ok_count}/{len(results)} runners succeeded")

    # Fail only if ALL runners failed
    if ok_count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
