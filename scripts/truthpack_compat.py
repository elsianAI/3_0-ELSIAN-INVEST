#!/usr/bin/env python3
"""Diagnostica y normaliza truth_pack.json legacy antes de importarlo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT))

from engine.truthpack_import import (  # noqa: E402
    diagnose_legacy_truthpack_payload,
    normalize_legacy_truthpack_payload,
)


def _load_payload(input_path: Path) -> dict:
    return json.loads(input_path.read_text(encoding="utf-8"))


def _print_human_diagnosis(diagnosis: dict) -> None:
    print(f"status: {diagnosis.get('status', 'unknown')}")

    issues = diagnosis.get("issues") or []
    if issues:
        print("issues:")
        for issue in issues:
            severity = str(issue.get("severity") or "warning").upper()
            code = str(issue.get("code") or "UNKNOWN")
            message = str(issue.get("message") or "")
            path = str(issue.get("path") or "")
            suffix = f" ({path})" if path else ""
            print(f"- [{severity}] {code}: {message}{suffix}")

    auto_fixable = diagnosis.get("auto_fixable") or []
    if auto_fixable:
        print("auto_fixable:")
        for item in auto_fixable:
            print(f"- {item}")

    required = diagnosis.get("required_upstream_data") or []
    if required:
        print("required_upstream_data:")
        for item in required:
            print(f"- {item}")


def _resolve_output_path(input_path: Path, explicit_output: Path | None, in_place: bool) -> Path:
    if in_place:
        return input_path
    if explicit_output is not None:
        return explicit_output
    return input_path.with_name(f"{input_path.stem}.normalized{input_path.suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose and normalize legacy truth packs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose_parser = subparsers.add_parser("diagnose", help="Diagnose a legacy truth pack")
    diagnose_parser.add_argument("--input", required=True, type=Path, help="Path to truth_pack.json")
    diagnose_parser.add_argument("--json", action="store_true", help="Emit diagnosis as JSON")

    normalize_parser = subparsers.add_parser("normalize", help="Normalize a legacy truth pack")
    normalize_parser.add_argument("--input", required=True, type=Path, help="Path to truth_pack.json")
    normalize_parser.add_argument("--output", type=Path, default=None, help="Output path for normalized truth pack")
    normalize_parser.add_argument("--in-place", action="store_true", help="Overwrite the input file")
    normalize_parser.add_argument("--json", action="store_true", help="Emit normalization metadata as JSON")

    args = parser.parse_args()
    payload = _load_payload(args.input)
    diagnosis = diagnose_legacy_truthpack_payload(payload)

    if args.command == "diagnose":
        if args.json:
            print(json.dumps(diagnosis, indent=2, ensure_ascii=False))
        else:
            _print_human_diagnosis(diagnosis)
        return 0 if diagnosis.get("status") != "blocked" else 2

    if diagnosis.get("status") == "blocked":
        if args.json:
            print(json.dumps(diagnosis, indent=2, ensure_ascii=False))
        else:
            _print_human_diagnosis(diagnosis)
        return 2

    normalized, meta = normalize_legacy_truthpack_payload(payload)
    output_path = _resolve_output_path(args.input, args.output, args.in_place)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps({"diagnosis": diagnosis, "normalization": meta, "output": str(output_path)}, indent=2, ensure_ascii=False))
    else:
        _print_human_diagnosis(diagnosis)
        print(f"output: {output_path}")
        print("applied_fixes:")
        for item in meta.get("applied_fixes", []):
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())