#!/usr/bin/env python3
"""Golden-snapshot regression checker for V6.2.

Compares current TruthPack outputs against saved golden snapshots to detect
regressions.  Designed for use as a CI gate or manual verification step.

Usage:
    python3 scripts/regression_check.py --generate          # Create/update golden snapshots
    python3 scripts/regression_check.py                     # Check all cases
    python3 scripts/regression_check.py --check             # Same as above (explicit)
    python3 scripts/regression_check.py --cases TEP,GCT     # Check subset
    python3 scripts/regression_check.py --verbose           # Detailed diff
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

WORKSPACE = Path(__file__).resolve().parent.parent
GOLDEN_DIR = WORKSPACE / "_golden"
CASOS_DIR = WORKSPACE / "casos"

# 5 baseline cases (ticker, date)
GOLDEN_CASES = [
    ("TEP", "2026-02-25"),
    ("GCT", "2026-02-23"),
    ("KAR", "2026-02-22"),
    ("0327", "2026-02-23"),
    ("EVER", "2026-02-23"),
]

# Core filing-derived fields to snapshot (exact match required)
CORE_ANNUAL_FIELDS = [
    "ingresos_usd",
    "ebit_usd",
    "net_income_usd",
    "cfo_usd",
    "capex_usd",
]

CORE_BALANCE_FIELDS = [
    "activos_totales_usd",
    "pasivos_totales_usd",
    "patrimonio_usd",
    "caja_usd",
    "deuda_total_usd",
]

# Market-derived fields (±5% tolerance)
MARKET_FIELDS = [
    "market_cap_usd",
    "precio",
]

# Quality metrics (only drops are regressions)
QUALITY_METRICS = [
    "confidence_score",
    "completeness_pct",
]

MARKET_TOLERANCE = 0.05  # 5%


# ── Snapshot extraction ───────────────────────────────────────────────────────


def _extract_snapshot(tp: dict) -> dict:
    """Extract a minimal snapshot payload from a TruthPack."""
    snapshot: dict[str, Any] = {
        "ticker": tp.get("ticker", ""),
        "version_esquema": tp.get("version_esquema", ""),
    }

    # ── Core annual fields (first 3 periods) ──
    annual = tp.get("historico_anual", [])
    snapshot["historico_anual_count"] = len(annual)
    snapshot["annual_periods"] = []
    for entry in annual[:3]:
        period_snap = {
            "periodo": entry.get("periodo"),
            "fecha_fin": entry.get("fecha_fin"),
        }
        for field in CORE_ANNUAL_FIELDS:
            period_snap[field] = entry.get(field)
        snapshot["annual_periods"].append(period_snap)

    # ── Core quarterly count ──
    quarterly = tp.get("historico_trimestral", [])
    snapshot["historico_trimestral_count"] = len(quarterly)

    # ── Balance sheet ──
    bs = tp.get("balance_sheet_ultimo", {})
    snapshot["balance_sheet"] = {}
    for field in CORE_BALANCE_FIELDS:
        snapshot["balance_sheet"][field] = bs.get(field)

    # ── Market data ──
    mercado = tp.get("mercado", {})
    snapshot["market"] = {
        "market_cap_usd": mercado.get("market_cap_usd"),
    }
    precio = mercado.get("precio", {})
    if isinstance(precio, dict):
        snapshot["market"]["precio"] = precio.get("valor")
    else:
        snapshot["market"]["precio"] = precio

    # ── Quality metrics ──
    dq = tp.get("data_quality", {})
    snapshot["quality"] = {
        "overall_status": dq.get("overall_status"),
        "confidence_score": dq.get("confidence_score"),
    }
    # Extract completeness_pct from gates
    for gate in dq.get("gates", []):
        if gate.get("name") == "DATA_COMPLETENESS":
            snapshot["quality"]["completeness_pct"] = gate.get("completeness_pct")
            break

    return snapshot


def _find_truthpack(case_dir: Path) -> Path | None:
    """Find TruthPack JSON in a case directory."""
    candidates = list(case_dir.glob("TruthPack_v1_*.json"))
    if not candidates:
        return None
    # Prefer most recently modified
    return max(candidates, key=lambda p: p.stat().st_mtime)


# ── Generate golden snapshots ─────────────────────────────────────────────────


def generate_goldens(cases: list[tuple[str, str]], verbose: bool = False) -> int:
    """Generate golden snapshots for the specified cases. Returns count created."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    for ticker, date_str in cases:
        case_dir = CASOS_DIR / ticker / date_str
        tp_path = _find_truthpack(case_dir)
        if tp_path is None:
            print(f"  WARNING: No TruthPack found for {ticker}/{date_str} — skipping",
                  file=sys.stderr)
            continue

        tp = json.loads(tp_path.read_text(encoding="utf-8"))
        snapshot = _extract_snapshot(tp)
        snapshot["_golden_meta"] = {
            "ticker": ticker,
            "date": date_str,
            "truthpack_path": str(tp_path.relative_to(WORKSPACE)),
            "source": "regression_check.py --generate",
        }

        golden_path = GOLDEN_DIR / f"golden_{ticker}_{date_str}.json"
        golden_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        count += 1
        if verbose:
            print(f"  ✓ Generated: {golden_path.name}")
            print(f"    annual_periods={snapshot['historico_anual_count']}, "
                  f"quarterly={snapshot['historico_trimestral_count']}, "
                  f"confidence={snapshot['quality'].get('confidence_score')}")
        else:
            print(f"  ✓ {golden_path.name}")

    return count


# ── Check against golden ──────────────────────────────────────────────────────


def _compare_exact(label: str, golden_val: Any, current_val: Any) -> str | None:
    """Compare filing-derived values. Returns error string or None."""
    if golden_val is None:
        return None  # Can't regress from null
    if current_val is None:
        return f"  REGRESSION {label}: was {golden_val}, now None"
    if golden_val != current_val:
        return f"  REGRESSION {label}: was {golden_val}, now {current_val}"
    return None


def _compare_market(label: str, golden_val: Any, current_val: Any) -> str | None:
    """Compare market-derived values with ±5% tolerance."""
    if golden_val is None:
        return None
    if current_val is None:
        return f"  REGRESSION {label}: was {golden_val}, now None"
    if not isinstance(golden_val, (int, float)) or not isinstance(current_val, (int, float)):
        if golden_val != current_val:
            return f"  REGRESSION {label}: was {golden_val}, now {current_val}"
        return None
    if golden_val == 0:
        if current_val != 0:
            return f"  REGRESSION {label}: was 0, now {current_val}"
        return None
    diff_pct = abs(current_val - golden_val) / abs(golden_val)
    if diff_pct > MARKET_TOLERANCE:
        return f"  REGRESSION {label}: was {golden_val}, now {current_val} (diff {diff_pct:.1%})"
    return None


def _compare_quality(label: str, golden_val: Any, current_val: Any) -> str | None:
    """Compare quality metrics — only drops are regressions."""
    if golden_val is None:
        return None
    if current_val is None:
        return f"  REGRESSION {label}: was {golden_val}, now None"
    if isinstance(golden_val, (int, float)) and isinstance(current_val, (int, float)):
        if current_val < golden_val:
            return f"  REGRESSION {label}: was {golden_val}, now {current_val} (drop)"
    return None


def _compare_count(label: str, golden_val: int, current_val: int) -> str | None:
    """Compare counts — only drops are regressions."""
    if golden_val is None:
        return None
    if current_val is None:
        return f"  REGRESSION {label}: was {golden_val}, now None"
    if current_val < golden_val:
        return f"  REGRESSION {label}: was {golden_val}, now {current_val} (drop)"
    return None


def _period_key(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """Build a stable annual-period key from snapshot entries."""
    if not isinstance(entry, dict):
        return (None, None)
    fecha_fin = entry.get("fecha_fin")
    periodo = entry.get("periodo")
    if isinstance(fecha_fin, str) and not fecha_fin.strip():
        fecha_fin = None
    if isinstance(periodo, str) and not periodo.strip():
        periodo = None
    return (fecha_fin if isinstance(fecha_fin, str) else None,
            periodo if isinstance(periodo, str) else None)


def check_case(
    ticker: str,
    date_str: str,
    verbose: bool = False,
) -> tuple[bool, list[str]]:
    """Check one case against its golden. Returns (passed, issues)."""
    golden_path = GOLDEN_DIR / f"golden_{ticker}_{date_str}.json"
    if not golden_path.exists():
        return True, [f"WARNING: Golden not found for {ticker}/{date_str} — skipping"]

    case_dir = CASOS_DIR / ticker / date_str
    tp_path = _find_truthpack(case_dir)
    if tp_path is None:
        return True, [f"WARNING: TruthPack not found for {ticker}/{date_str} — skipping"]

    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    tp = json.loads(tp_path.read_text(encoding="utf-8"))
    current = _extract_snapshot(tp)

    issues: list[str] = []

    # ── Compare annual periods (exact, aligned by period key not list position) ──
    g_annual = [e for e in golden.get("annual_periods", []) if isinstance(e, dict)]
    c_annual = [e for e in current.get("annual_periods", []) if isinstance(e, dict)]

    golden_by_key: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    current_by_key: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    golden_unkeyed: list[tuple[int, dict[str, Any]]] = []
    current_unkeyed: list[tuple[int, dict[str, Any]]] = []

    for i, entry in enumerate(g_annual):
        key = _period_key(entry)
        if key == (None, None):
            golden_unkeyed.append((i, entry))
        else:
            golden_by_key[key] = entry

    for i, entry in enumerate(c_annual):
        key = _period_key(entry)
        if key == (None, None):
            current_unkeyed.append((i, entry))
        else:
            current_by_key[key] = entry

    for key, gp in golden_by_key.items():
        cp = current_by_key.get(key)
        if cp is None:
            issues.append(
                "  REGRESSION annual[periodo="
                f"{key[1]},fecha_fin={key[0]}]: missing in current snapshot"
            )
            continue
        for field in CORE_ANNUAL_FIELDS:
            err = _compare_exact(
                f"annual[periodo={key[1]},fecha_fin={key[0]}].{field}",
                gp.get(field),
                cp.get(field),
            )
            if err:
                issues.append(err)

    # Fallback for legacy/unkeyed entries: compare by position.
    for i, (g_idx, gp) in enumerate(golden_unkeyed):
        if i >= len(current_unkeyed):
            issues.append(
                f"  REGRESSION annual[{g_idx}]: missing unkeyed period in current snapshot"
            )
            continue
        _, cp = current_unkeyed[i]
        for field in CORE_ANNUAL_FIELDS:
            err = _compare_exact(
                f"annual_unkeyed[{g_idx}].{field}",
                gp.get(field),
                cp.get(field),
            )
            if err:
                issues.append(err)

    # ── Compare counts (only drops) ──
    for count_field in ("historico_anual_count", "historico_trimestral_count"):
        err = _compare_count(
            count_field,
            golden.get(count_field),
            current.get(count_field),
        )
        if err:
            issues.append(err)

    # ── Compare balance sheet (exact) ──
    gbs = golden.get("balance_sheet", {})
    cbs = current.get("balance_sheet", {})
    for field in CORE_BALANCE_FIELDS:
        err = _compare_exact(f"balance.{field}", gbs.get(field), cbs.get(field))
        if err:
            issues.append(err)

    # ── Compare market (±5%) ──
    gm = golden.get("market", {})
    cm = current.get("market", {})
    for field in ("market_cap_usd", "precio"):
        err = _compare_market(f"market.{field}", gm.get(field), cm.get(field))
        if err:
            issues.append(err)

    # ── Compare quality (only drops) ──
    gq = golden.get("quality", {})
    cq = current.get("quality", {})
    for field in ("confidence_score", "completeness_pct"):
        err = _compare_quality(f"quality.{field}", gq.get(field), cq.get(field))
        if err:
            issues.append(err)

    passed = not any("REGRESSION" in i for i in issues)

    if verbose:
        print(f"  Annual: {current['historico_anual_count']} "
              f"(golden: {golden.get('historico_anual_count', '?')})")
        print(f"  Quarterly: {current['historico_trimestral_count']} "
              f"(golden: {golden.get('historico_trimestral_count', '?')})")
        print(f"  Confidence: {cq.get('confidence_score')} "
              f"(golden: {gq.get('confidence_score', '?')})")
        if golden_by_key:
            keys = sorted(golden_by_key.keys(), key=lambda k: (k[0] or "", k[1] or ""))
            key_desc = ", ".join(f"{k[1]}@{k[0]}" for k in keys)
            print(f"  Annual keys: {key_desc}")
        if golden_unkeyed:
            print(f"  Annual unkeyed compared by position: {len(golden_unkeyed)}")

    return passed, issues


def run_checks(
    cases: list[tuple[str, str]],
    verbose: bool = False,
) -> int:
    """Run regression checks. Returns 0 if no regressions, 1 otherwise."""
    total_passed = 0
    total_failed = 0
    total_skipped = 0

    for ticker, date_str in cases:
        print(f"\n── {ticker}/{date_str} ──")
        passed, issues = check_case(ticker, date_str, verbose=verbose)

        if issues:
            for issue in issues:
                print(issue)

        warnings_only = all("WARNING" in i for i in issues) if issues else True
        if not issues or (warnings_only and passed):
            if warnings_only and issues:
                total_skipped += 1
                print(f"  SKIP (warnings only)")
            else:
                total_passed += 1
                print(f"  PASS ✓")
        elif passed:
            total_passed += 1
            print(f"  PASS ✓ (with warnings)")
        else:
            total_failed += 1
            print(f"  FAIL ✗")

    print(f"\n═══ Summary: {total_passed} PASS, {total_failed} FAIL, {total_skipped} SKIP ═══")
    return 1 if total_failed > 0 else 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Golden-snapshot regression checker for V6.2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/regression_check.py --generate
  python3 scripts/regression_check.py --check
  python3 scripts/regression_check.py --cases TEP,GCT --verbose
        """,
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate/update golden snapshots from current TruthPacks",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Check current TruthPacks against golden snapshots (default)",
    )
    parser.add_argument(
        "--cases",
        type=str,
        default=None,
        help="Comma-separated list of tickers to check (default: all 5)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed diff per field",
    )

    args = parser.parse_args()

    # Filter cases if --cases provided
    if args.cases:
        requested = {t.strip().upper() for t in args.cases.split(",")}
        cases = [(t, d) for t, d in GOLDEN_CASES if t.upper() in requested]
        if not cases:
            print(f"ERROR: No matching cases for: {args.cases}", file=sys.stderr)
            print(f"Available: {', '.join(t for t, _ in GOLDEN_CASES)}", file=sys.stderr)
            sys.exit(1)
    else:
        cases = GOLDEN_CASES

    if args.generate:
        print(f"[regression_check] Generating golden snapshots for {len(cases)} cases...")
        count = generate_goldens(cases, verbose=args.verbose)
        print(f"[regression_check] Generated {count}/{len(cases)} golden snapshots")
        sys.exit(0)
    else:
        print(f"[regression_check] Checking {len(cases)} cases against golden snapshots...")
        exit_code = run_checks(cases, verbose=args.verbose)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
