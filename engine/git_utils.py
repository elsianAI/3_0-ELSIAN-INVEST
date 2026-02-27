"""Git automation conservadora para V6.2.

Política:
- 1 commit por comando CLI exitoso (pipeline, continue, step, rehacer).
- NO commits intermedios por sub-step dentro de pipeline.
- NO commits en FALLIDO.
- Push solo si hubo commit nuevo.
- Rama actual, sin auto-switch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any


def is_git_enabled(config_raw: dict) -> bool:
    """Check if git automation is enabled in engine_config.json."""
    git_cfg = config_raw.get("git", {})
    if not isinstance(git_cfg, dict):
        return False
    return bool(git_cfg.get("enabled", False))


def _get_current_branch(workspace: Path) -> str:
    """Get current git branch name. Returns '' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _is_git_repo(workspace: Path) -> bool:
    """Check if workspace is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        return False


def _has_staged_changes(workspace: Path) -> bool:
    """Check if there are any staged changes ready to commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=10,
        )
        # Exit code 1 means there ARE staged changes
        return result.returncode == 1
    except Exception:
        return False


def auto_commit_case(
    workspace: Path,
    case_dir: Path,
    ticker: str,
    operation: str,
    detail: str,
    git_config: dict,
) -> bool:
    """Stage case_dir + configured paths and commit.

    Args:
        workspace: Root workspace path (for git commands).
        case_dir: Path to the case directory to stage.
        ticker: Case ticker for commit message.
        operation: PIPELINE | CONTINUE | STEP | REHACER
        detail: Detail string (e.g. "COMPLETO via 2026-02-25" or "BULL DONE (codex)")
        git_config: The "git" block from engine_config.json.

    Returns:
        True if a commit was created, False otherwise.
    """
    if not git_config.get("enabled", False):
        return False

    if not _is_git_repo(workspace):
        print("[git] WARNING: Not a git repo — skipping commit", file=sys.stderr)
        return False

    # Warn if not on main/master
    branch = _get_current_branch(workspace)
    if branch and branch not in ("main", "master"):
        print(f"[git] INFO: On branch '{branch}' (not main)", file=sys.stderr)

    # Stage case_dir
    try:
        subprocess.run(
            ["git", "add", str(case_dir)],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=30,
        )
    except Exception as e:
        print(f"[git] WARNING: Failed to stage {case_dir}: {e}", file=sys.stderr)
        return False

    # Stage additional configured paths (e.g. CHANGELOG.md)
    extra_paths = git_config.get("stage_paths", [])
    if isinstance(extra_paths, list):
        for p in extra_paths:
            p_path = workspace / p
            if p_path.exists():
                try:
                    subprocess.run(
                        ["git", "add", str(p)],
                        capture_output=True,
                        text=True,
                        cwd=str(workspace),
                        timeout=10,
                    )
                except Exception:
                    pass  # Best-effort for extra paths

    # Check if there are actually staged changes
    if not _has_staged_changes(workspace):
        return False  # Nothing to commit

    # Build commit message
    message = f"[{operation}] {ticker}: {detail}"

    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=30,
        )
        if result.returncode == 0:
            print(f"[git] Committed: {message}", file=sys.stderr)
            return True
        else:
            print(f"[git] WARNING: Commit failed: {result.stderr.strip()}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[git] WARNING: Commit exception: {e}", file=sys.stderr)
        return False


def push_if_needed(workspace: Path, git_config: dict) -> tuple[bool, str]:
    """Push to remote if configured and if there was a new commit.

    Returns:
        (success, message) — success=True if push succeeded or was not needed.
    """
    if not git_config.get("enabled", False):
        return True, "git disabled"

    if not git_config.get("push_on_command_end", False):
        return True, "push disabled"

    if not _is_git_repo(workspace):
        return True, "not a git repo"

    remote = git_config.get("remote", "origin")

    # Check if there's an upstream to push to
    branch = _get_current_branch(workspace)
    if not branch:
        return False, "could not determine branch"

    try:
        result = subprocess.run(
            ["git", "push", remote, branch],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=60,
        )
        if result.returncode == 0:
            return True, f"pushed to {remote}/{branch}"
        else:
            msg = result.stderr.strip() or result.stdout.strip()
            print(f"[git] WARNING: Push failed: {msg}", file=sys.stderr)
            return False, f"push failed: {msg}"
    except Exception as e:
        print(f"[git] WARNING: Push exception: {e}", file=sys.stderr)
        return False, f"push exception: {e}"


# ── Legacy API (backward-compatible) ──────────────────────────────────────────
# These are kept for any code that still imports the old interface.


def stage_case(case_dir: Path, workspace: Path) -> None:
    """Legacy: git add case_dir + CHANGELOG.md. Prefer auto_commit_case()."""
    files_to_add = [str(case_dir), "CHANGELOG.md"]
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
    """Legacy: Format commit message. Prefer auto_commit_case()."""
    return f"[{operation}] {ticker}: {step} via {model}"


def commit(workspace: Path, message: str) -> bool:
    """Legacy: Execute git commit. Prefer auto_commit_case()."""
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
