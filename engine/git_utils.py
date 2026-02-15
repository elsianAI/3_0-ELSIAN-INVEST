"""Prepara commits (staging + mensaje). NO hace push."""

import subprocess
from pathlib import Path


def stage_case(case_dir: Path, workspace: Path) -> None:
    """git add {case_dir}/ + CHANGELOG.md + ESTADO_REPO.json"""
    files_to_add = [
        str(case_dir),
        "CHANGELOG.md",
        "ESTADO_REPO.json",
    ]

    for f in files_to_add:
        try:
            subprocess.run(
                ["git", "add", f],
                capture_output=True,
                text=True,
                cwd=str(workspace),
            )
        except Exception:
            pass


def prepare_commit_message(
    ticker: str,
    operation: str,
    step: str,
    model: str,
) -> str:
    """
    Genera mensaje de commit en formato canónico:
    [{operation}] {ticker}: {step} via {model}
    """
    return f"[{operation}] {ticker}: {step} via {model}"


def commit(workspace: Path, message: str) -> bool:
    """Ejecuta git commit -m '{message}' en workspace. Returns success."""
    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            cwd=str(workspace),
        )
        return result.returncode == 0
    except Exception:
        return False
