#!/usr/bin/env python3
"""Backfill pipeline.<step>.artefacto in historical _estado.json files.

Usage:
  python3 scripts/qa/backfill_pipeline_artifacts.py --dry-run
  python3 scripts/qa/backfill_pipeline_artifacts.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.router import _find_artifact
from engine.state import read_modify_write


STEP_PATTERNS = {
    "SOURCES": "SourcesPack_v1",
    "TRUTH_PACK": "TruthPack_v1",
    "IMPLIED": "ImpliedExpectations_v1",
    "CATALYST": "AgentReport_v1_CATALYST",
    "FORENSIC": "AgentReport_v1_FORENSIC",
    "BULL": "AgentReport_v1_BULL",
    "RED_TEAM": "AgentReport_v1_REDTEAM",
    "ARBITRO": "DecisionPacket_v2",
}


def _iter_case_dirs(casos_dir: Path):
    if not casos_dir.exists():
        return
    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir() or case_dir.name.startswith("_"):
                continue
            if (case_dir / "_estado.json").exists():
                yield case_dir


def _load_state(case_dir: Path) -> dict:
    return json.loads((case_dir / "_estado.json").read_text())


def _backfill_case(case_dir: Path, apply: bool) -> tuple[int, int]:
    state = _load_state(case_dir)
    pipeline = state.get("pipeline", {})
    if not isinstance(pipeline, dict):
        return 0, 0

    updates: dict[str, str] = {}
    checked = 0
    for step, pattern in STEP_PATTERNS.items():
        step_data = pipeline.get(step, {})
        if not isinstance(step_data, dict):
            continue
        if step_data.get("estado") != "DONE":
            continue
        checked += 1
        art = step_data.get("artefacto")
        if isinstance(art, str) and art:
            continue

        found = _find_artifact(case_dir, pattern)
        if found:
            updates[step] = found.name

    if apply and updates:
        def _modifier(s: dict) -> None:
            p = s.get("pipeline", {})
            if not isinstance(p, dict):
                return
            for step, artifact in updates.items():
                if isinstance(p.get(step), dict):
                    p[step]["artefacto"] = artifact

        read_modify_write(case_dir, _modifier)

    return checked, len(updates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill pipeline step artifacts in historical cases.")
    parser.add_argument("--workspace", default=str(ROOT), help="Workspace root (contains casos/)")
    parser.add_argument("--apply", action="store_true", help="Persist changes to _estado.json")
    parser.add_argument("--dry-run", action="store_true", help="Only report changes (default)")
    args = parser.parse_args()

    apply = bool(args.apply)
    if not args.apply and not args.dry_run:
        apply = False  # default to dry-run

    workspace = Path(args.workspace).resolve()
    casos_dir = workspace / "casos"

    total_cases = 0
    total_checked = 0
    total_updates = 0

    for case_dir in _iter_case_dirs(casos_dir):
        total_cases += 1
        checked, updates = _backfill_case(case_dir, apply=apply)
        total_checked += checked
        total_updates += updates
        if updates:
            mode = "APPLY" if apply else "DRY-RUN"
            rel = case_dir.relative_to(workspace)
            print(f"[{mode}] {rel}: updates={updates}")

    print(
        f"[summary] cases={total_cases} checked_steps={total_checked} "
        f"pending_backfills={total_updates} mode={'apply' if apply else 'dry-run'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
