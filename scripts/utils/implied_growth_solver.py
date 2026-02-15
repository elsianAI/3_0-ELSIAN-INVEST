#!/usr/bin/env python3
"""
implied_growth_solver.py — Solve for implied CAGR given EV, FCF, discount rate, and terminal multiple.

Extracted from implied_expectations_runner.py for reuse across the pipeline.

Usage as library:
    from scripts.utils.implied_growth_solver import solve_cagr
    g = solve_cagr(ev=5_000_000_000, fcf0=300_000_000, r=0.10, term_mult=15)

Usage as CLI:
    python3 scripts/utils/implied_growth_solver.py --ev 5000 --fcf0 300 --r 0.10 --term-mult 15
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional


def solve_cagr(
    ev: float,
    fcf0: float,
    r: float,
    term_mult: float,
    years: int = 5,
    tolerance: float = 0.0001,
    max_iterations: int = 100,
) -> Optional[float]:
    """Solve for implied FCF CAGR via binary search on a simple DCF model.

    Model:
        EV = Sum_{t=1}^{years} FCF0*(1+g)^t / (1+r)^t  +  FCF0*(1+g)^years * term_mult / (1+r)^years

    Args:
        ev: Enterprise value (must be > 0).
        fcf0: Base FCF (must be > 0).
        r: Discount rate (e.g. 0.10 for 10%).
        term_mult: Terminal multiple on FCF at year `years`.
        years: Projection horizon (default 5).
        tolerance: Relative tolerance for convergence.
        max_iterations: Max binary search iterations.

    Returns:
        Implied CAGR as a float (e.g. 0.12 for 12%), rounded to 4 decimals.
        Returns None if inputs are invalid (ev <= 0, fcf0 <= 0, r <= 0).
    """
    if ev <= 0 or fcf0 <= 0 or r <= 0 or term_mult <= 0 or years < 1:
        return None

    low = -0.50
    high = 2.00

    for _ in range(max_iterations):
        g = (low + high) / 2

        pv_fcf = 0.0
        for t in range(1, years + 1):
            fcf_t = fcf0 * ((1 + g) ** t)
            pv_fcf += fcf_t / ((1 + r) ** t)

        fcf_terminal = fcf0 * ((1 + g) ** years)
        pv_tv = (fcf_terminal * term_mult) / ((1 + r) ** years)

        implied_ev = pv_fcf + pv_tv

        if abs(implied_ev - ev) < ev * tolerance:
            return round(g, 4)

        if implied_ev < ev:
            low = g
        else:
            high = g

    return round((low + high) / 2, 4)


def build_grid(
    ev: float,
    fcf0: float,
    discount_rates: Optional[list] = None,
    term_multiples: Optional[list] = None,
    years: int = 5,
) -> list:
    """Build a grid of implied CAGR for combinations of discount rate and terminal multiple."""
    if discount_rates is None:
        discount_rates = [0.08, 0.10, 0.12]
    if term_multiples is None:
        term_multiples = [10, 12, 15, 18]

    grid = []
    for r in discount_rates:
        for tm in term_multiples:
            g = solve_cagr(ev, fcf0, r, tm, years=years)
            grid.append({
                "tasa_descuento": r,
                "multiple_terminal_fcf": tm,
                "cagr_fcf_5y_implicito": g,
                "nota": f"Requires {g * 100:.1f}% annual growth" if g is not None else "Could not solve",
            })
    return grid


def main() -> int:
    parser = argparse.ArgumentParser(description="Solve for implied FCF CAGR")
    parser.add_argument("--ev", type=float, required=True, help="Enterprise value")
    parser.add_argument("--fcf0", type=float, required=True, help="Base FCF")
    parser.add_argument("--r", type=float, default=0.10, help="Discount rate (default 0.10)")
    parser.add_argument("--term-mult", type=float, default=15, help="Terminal multiple (default 15)")
    parser.add_argument("--years", type=int, default=5, help="Projection years (default 5)")
    parser.add_argument("--grid", action="store_true", help="Output full grid instead of single result")
    args = parser.parse_args()

    if args.grid:
        grid = build_grid(args.ev, args.fcf0, years=args.years)
        print(json.dumps(grid, indent=2))
    else:
        g = solve_cagr(args.ev, args.fcf0, args.r, args.term_mult, years=args.years)
        if g is None:
            print("ERROR: Could not solve (check inputs)", file=sys.stderr)
            return 1
        print(json.dumps({"cagr_implicito": g, "pct": f"{g * 100:.2f}%"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
