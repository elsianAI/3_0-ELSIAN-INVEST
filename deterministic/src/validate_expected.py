"""Validate expected.json files for structural consistency.

Rules:
1. Every field must have a `source_filing` key.
2. If `restatement` is present, it must have all required sub-fields:
   applied, trigger, evidence_filing, evidence_text, original_source_filing, original_value.
3. In a restatement, `original_source_filing` must differ from the field's `source_filing`
   (if the restated value comes from the same filing, original came from a different one).
4. Returns a list of errors (empty = valid).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


_RESTATEMENT_REQUIRED_FIELDS = [
    "applied",
    "trigger",
    "evidence_filing",
    "evidence_text",
    "original_source_filing",
    "original_value",
]


def validate_expected(expected_path: str) -> List[str]:
    """Validate an expected.json file.

    Args:
        expected_path: Absolute path to the expected.json file.

    Returns:
        List of error messages. Empty list means the file is valid.
    """
    path = Path(expected_path)
    if not path.exists():
        return [f"File not found: {expected_path}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    errors: List[str] = []

    periods: Dict[str, Any] = data.get("periods", {})
    if not periods:
        errors.append("No periods found in expected.json")
        return errors

    for period_key, period_data in periods.items():
        fields = period_data.get("fields", {})
        for field_name, field_info in fields.items():
            loc = f"{period_key}/{field_name}"

            # Rule 1: source_filing is mandatory
            if "source_filing" not in field_info or not field_info["source_filing"]:
                errors.append(f"{loc}: missing 'source_filing'")

            # Rule 2: if restatement present, all sub-fields required
            restatement = field_info.get("restatement")
            if restatement is not None:
                for req_field in _RESTATEMENT_REQUIRED_FIELDS:
                    if req_field not in restatement:
                        errors.append(
                            f"{loc}: restatement missing '{req_field}'"
                        )

                # Rule 3: original_source_filing != source_filing
                orig_src = restatement.get("original_source_filing", "")
                src = field_info.get("source_filing", "")
                if orig_src and src and orig_src == src:
                    errors.append(
                        f"{loc}: restatement 'original_source_filing' "
                        f"should differ from 'source_filing' "
                        f"(both are '{src}')"
                    )

    return errors


def validate_all_cases(cases_dir: str) -> Dict[str, List[str]]:
    """Validate all expected.json files under cases_dir.

    Returns:
        Dict mapping ticker -> list of errors.
    """
    cases_path = Path(cases_dir)
    results: Dict[str, List[str]] = {}

    if not cases_path.exists():
        return results

    for case_subdir in sorted(cases_path.iterdir()):
        if not case_subdir.is_dir():
            continue
        expected_path = case_subdir / "expected.json"
        if not expected_path.exists():
            continue
        ticker = case_subdir.name
        errors = validate_expected(str(expected_path))
        if errors:
            results[ticker] = errors

    return results
