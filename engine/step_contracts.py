"""Shared step contracts: schema expectations and helpers.

Centralizes step->schema mappings used across router, dispatcher and
quality_voting to avoid drift.
"""

from __future__ import annotations

from typing import Final


STEP_ALLOWED_SCHEMAS: Final[dict[str, tuple[str, ...]]] = {
    "SOURCES_COMPILER": ("SourcesPack_v1",),
    "TP_VALIDATOR": ("TruthPack_v1",),
    "IMPLIED": ("ImpliedExpectations_v1",),
    "CATALYST_DETECTION": ("CatalystDetection_v1",),
    "CATALYST_SCORING": ("AgentReport_v1",),
    "FORENSIC_DETECTION": ("ForensicDetection_v1",),
    "FORENSIC_SCORING": ("AgentReport_v1",),
    "BULL": ("AgentReport_v1",),
    "RED_TEAM": ("AgentReport_v1",),
    "ARBITRO": ("DecisionPacket_v2", "ArbitroRemediateKickoff_v1"),
    "MONITOR": ("MonitoringUpdate_v1",),
    "SCANNER": ("ScannerReport_v1",),
}


def get_allowed_schemas(step_name: str) -> tuple[str, ...]:
    """Return all accepted output schemas for a step."""
    return STEP_ALLOWED_SCHEMAS.get(step_name, ())


def get_primary_schema(step_name: str) -> str | None:
    """Return canonical primary schema for a step."""
    schemas = get_allowed_schemas(step_name)
    return schemas[0] if schemas else None

