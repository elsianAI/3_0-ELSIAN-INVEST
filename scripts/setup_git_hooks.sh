#!/usr/bin/env bash
# ============================================================================
# Setup git hooks for ELSIAN-INVEST
# Configures core.hooksPath to use .githooks/ (versionado en el repo)
# ============================================================================

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo '.')"
HOOKS_DIR="${REPO_ROOT}/.githooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "ERROR: .githooks/ directory not found at ${HOOKS_DIR}"
    exit 1
fi

if [ ! -x "${HOOKS_DIR}/pre-commit" ]; then
    echo "ERROR: .githooks/pre-commit not found or not executable"
    exit 1
fi

git config core.hooksPath .githooks

echo "Git hooks configured:"
echo "  core.hooksPath = $(git config core.hooksPath)"
echo "  pre-commit hook: ${HOOKS_DIR}/pre-commit"
echo ""
echo "Done. Deterministic traceability enforcement is now active."
