#!/bin/bash
# Script to fix blocked cases with null autochequeos
# DEPRECATED — moved to scripts/_deprecated/
# Original usage: bash scripts/fix_blocked_cases.sh

set -e

echo "========================================="
echo "Fixing blocked cases with null autochequeos"
echo "========================================="

DATE="2026-02-15"

# Function to regenerate steps for a case
fix_case() {
    local TICKER=$1
    echo ""
    echo "=== Processing $TICKER ==="
    
    echo "[1/3] Regenerating BULL..."
    python3 -m engine step $TICKER BULL --date $DATE
    
    echo "[2/3] Regenerating RED_TEAM..."
    python3 -m engine step $TICKER RED_TEAM --date $DATE
    
    echo "[3/3] Continuing pipeline..."
    python3 -m engine continue $TICKER --date $DATE
    
    echo "✓ $TICKER completed"
}

# Process each blocked case
fix_case "INMD"
fix_case "ACLS"
fix_case "TZOO"

echo ""
echo "========================================="
echo "All cases processed. Checking dashboard..."
echo "========================================="
python3 -m engine dashboard

echo ""
echo "Done! All cases should now be unblocked."
