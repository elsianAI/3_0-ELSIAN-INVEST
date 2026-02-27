"""Scale inference and correction.

Implements DT-1 cascade: raw_notes -> header -> preflight -> uncertainty.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Scale multipliers to normalize to "millions" base
SCALE_MULTIPLIERS = {
    "raw": 1.0,
    "thousands": 0.001,
    "millions": 1.0,
    "billions": 1000.0,
}


def normalize_to_millions(
    value: float, scale: str
) -> Tuple[float, str]:
    """Normalize a value to millions scale.

    Returns (normalized_value, "millions").
    """
    multiplier = SCALE_MULTIPLIERS.get(scale, 1.0)
    return value * multiplier, "millions"


def infer_scale_cascade(
    raw_notes_scale: str,
    header_scale: str,
    preflight_scale: str,
    field_multiplier: Optional[float],
) -> Tuple[str, str]:
    """DT-1 scale inference cascade.

    Priority:
    1. raw_notes (explicit "in millions" in the filing text)
    2. header (from filing section header)
    3. preflight (from detect.py analysis)
    4. field_multiplier (from aliases config)
    5. "raw" with uncertainty

    Returns (scale, confidence).
    """
    # Level 1: raw notes (highest confidence)
    if raw_notes_scale and raw_notes_scale != "raw":
        return raw_notes_scale, "high"

    # Level 2: header indication
    if header_scale and header_scale != "raw":
        return header_scale, "high"

    # Level 3: preflight detection
    if preflight_scale and preflight_scale != "raw":
        return preflight_scale, "medium"

    # Level 4: field alias multiplier
    if field_multiplier is not None:
        if field_multiplier == 1000.0:
            return "billions", "low"
        elif field_multiplier == 1.0:
            return "millions", "low"
        elif field_multiplier == 0.001:
            return "thousands", "low"

    # Level 5: uncertainty
    return "raw", "low"


def apply_scale(value: float, scale: str) -> float:
    """Apply scale to get value in the stated unit."""
    return value  # Values are already in the stated scale


def validate_scale_sanity(
    value: float, field_name: str, scale: str
) -> bool:
    """Check if a value+scale combination is plausible.

    Used to catch obvious scale errors (e.g. revenue of $0.0001 millions).
    """
    if scale == "raw":
        return True

    abs_val = abs(value)

    # Revenue, assets, etc. in millions should typically be > 0.01
    large_fields = {
        "ingresos",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "cfo",
    }
    if field_name in large_fields and scale == "millions":
        if abs_val > 0 and abs_val < 0.01:
            return False

    # EPS should be small numbers (not thousands/millions)
    eps_fields = {"eps_basic", "eps_diluted", "dividends_per_share"}
    if field_name in eps_fields:
        if abs_val > 10000:
            return False

    return True
