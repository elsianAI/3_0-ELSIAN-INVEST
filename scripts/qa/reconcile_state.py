#!/usr/bin/env python3
"""Reconcile sub-step state against existing TRUTH_PACK artifacts.

Dry-run by default.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.state import load_state, mark_step_done, save_state


def _valid_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def _latest_valid(pattern: str, case_dir: Path) -> Path | None:
    candidates = [p for p in case_dir.glob(pattern) if p.is_file() and _valid_json(p)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _iter_case_dirs(casos_dir: Path, tickers: list[str], date_filter: str | None) -> list[Path]:
    out: list[Path] = []
    for ticker in tickers:
        ticker_dir = casos_dir / ticker
        if not ticker_dir.exists():
            continue
        if date_filter:
            case_dir = ticker_dir / date_filter
            if (case_dir / "_estado.json").exists():
                out.append(case_dir)
            continue
        for case_dir in sorted(p for p in ticker_dir.iterdir() if p.is_dir()):
            if (case_dir / "_estado.json").exists():
                out.append(case_dir)
    return out


def _reconcile_failed_main_steps(case_dir: Path, state: dict, apply: bool) -> list[str]:
    """For FALLIDO pipelines, reconcile main steps that have _errors but are
    still PENDING/IN_PROGRESS — set them to FAILED explicitly."""
    changes: list[str] = []
    if state.get("estado_pipeline") != "FALLIDO":
        return changes

    pipeline = state.get("pipeline", {})
    errors = state.get("_errors", {})
    now = datetime.now(timezone.utc).isoformat()

    for step_name in pipeline:
        step_estado = pipeline[step_name].get("estado", "")
        has_error = isinstance(errors.get(step_name), dict) and errors[step_name].get("error")

        if step_estado in ("PENDING", "IN_PROGRESS") and has_error:
            changes.append(f"{step_name}: {step_estado} -> FAILED (error: {str(errors[step_name]['error'])[:80]})")
            if apply:
                pipeline[step_name]["estado"] = "FAILED"

    if apply and changes:
        save_state(case_dir, state)
    return changes


def _reconcile_case(case_dir: Path, apply: bool) -> list[str]:
    state = load_state(case_dir)
    changes: list[str] = []
    sub_steps = state.get("sub_steps", {})

    calc_art = _latest_valid("_tp_calculated_*.json", case_dir)
    if calc_art and sub_steps.get("TP_CALCULATOR", {}).get("status") == "PENDING":
        changes.append(f"TP_CALCULATOR: PENDING -> DONE ({calc_art.name})")
        if apply:
            mark_step_done(case_dir, "TP_CALCULATOR", model="python", artefacto=calc_art.name)

    tp_art = _latest_valid("TruthPack_v1_*.json", case_dir)
    if tp_art and sub_steps.get("TP_VALIDATOR", {}).get("status") == "PENDING":
        changes.append(f"TP_VALIDATOR: PENDING -> DONE ({tp_art.name})")
        if apply:
            mark_step_done(case_dir, "TP_VALIDATOR", model="python", artefacto=tp_art.name)

    state_after = load_state(case_dir)
    changes.extend(_reconcile_failed_main_steps(case_dir, state_after, apply))
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile _estado.json with existing artifacts.")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run).")
    parser.add_argument(
        "--tickers",
        default="ACLS,TZOO,ACVA",
        help="Comma-separated tickers to inspect (default: ACLS,TZOO,ACVA).",
    )
    parser.add_argument("--date", default="2026-02-15", help="Case date YYYY-MM-DD (default: 2026-02-15).")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    casos_dir = ROOT / "casos"
    case_dirs = _iter_case_dirs(casos_dir, tickers, args.date)

    print(f"[reconcile] mode={'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"[reconcile] tickers={tickers}, date={args.date}")
    print(f"[reconcile] cases={len(case_dirs)}")

    total_changes = 0
    touched_cases = 0

    for case_dir in case_dirs:
        changes = _reconcile_case(case_dir, apply=args.apply)
        if changes:
            touched_cases += 1
            total_changes += len(changes)
            print(f"\n[{case_dir}]")
            for ch in changes:
                print(f"  - {ch}")

    print(f"\n[reconcile] touched_cases={touched_cases}, changes={total_changes}")
    if not args.apply:
        print("[reconcile] Dry-run only. Re-run with --apply to persist changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
