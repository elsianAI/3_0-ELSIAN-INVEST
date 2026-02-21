#!/bin/bash
# Complete fix for blocked cases
# Uses native autochequeos validation and continues blocked pipelines

set -e

echo "==========================================="
echo "Fix Completo para Casos Bloqueados"
echo "==========================================="
echo ""

# Step 1: Autochequeos validation now handled natively by engine/validator.py
# (fix_autochequeos.py is deprecated — canonical log.autochequeos used directly)
echo "[1/4] Autochequeos: validated natively (no patch needed)"
echo ""

# Step 2: Continue each case
DATE="2026-02-15"

echo "[2/4] Continuando INMD..."
python3 -m engine continue INMD --date $DATE
echo "✓ INMD completado"
echo ""

echo "[3/4] Continuando ACLS..."
python3 -m engine continue ACLS --date $DATE
echo "✓ ACLS completado"
echo ""

echo "[4/4] Continuando TZOO..."
python3 -m engine continue TZOO --date $DATE
echo "✓ TZOO completado"
echo ""

echo "==========================================="
echo "Dashboard Final"
echo "==========================================="
python3 -m engine dashboard

echo ""
echo "✅ Todos los casos desbloqueados y completados!"
