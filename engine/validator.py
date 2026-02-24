"""Valida artefactos JSON contra schemas. 100% Python, 0 LLM.

Implements §3.11 of PLAN COMPLETO.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


# Mapeo filename pattern → schema file
SCHEMA_MAP = {
    "SourcesPack_v1": "artefactos/SourcesPack_v1.json",
    "TruthPack_v1": "artefactos/TruthPack_v1.json",
    "ImpliedExpectations_v1": "artefactos/ImpliedExpectations_v1.json",
    "CatalystDetection_v1": "artefactos/CatalystDetection_v1.json",
    "ForensicDetection_v1": "artefactos/ForensicDetection_v1.json",
    "AgentReport_v1": "artefactos/AgentReport_v1.json",
    "DecisionPacket_v2": "artefactos/DecisionPacket_v2.json",
    "DecisionPacket_v1": "artefactos/DecisionPacket_v1.json",
    "MonitoringUpdate_v1": "monitoring/MonitoringUpdate_v1.json",
    "OutcomeRecord_v1": "monitoring/OutcomeRecord_v1.json",
    "CalibrationReport_v1": "monitoring/CalibrationReport_v1.json",
    "ScannerReport_v1": "scanner/ScannerReport_v1.json",
    "BenchmarkComparisons_v1": "benchmark/BenchmarkComparisons_v1.json",
    "VotingRecord_v1": "evaluacion/VotingRecord_v1.json",
    "StepVote_v1": "evaluacion/StepVote_v1.json",
    "VoteEvent_v1": "evaluacion/VoteEvent_v1.json",
    "ModelQualityRollup_v1": "evaluacion/ModelQualityRollup_v1.json",
    "ModelQualityCase_v1": "evaluacion/ModelQualityCase_v1.json",
    "CandidateList_v2": "artefactos/CandidateList_v2.json",
    "PreFilterUniverse_v1": "artefactos/PreFilterUniverse_v1.json",
    "BullPayload_v1": "payloads/BullPayload_v1.json",
    "CatalystPayload_v1": "payloads/CatalystPayload_v1.json",
    "ForensicPayload_v1": "payloads/ForensicPayload_v1.json",
    "RedTeamPayload_v1": "payloads/RedTeamPayload_v1.json",
    "PatchBundle_v3": "remediation/PatchBundle_v3.json",
    "RemediationPlan_v1": "remediation/RemediationPlan_v1.json",
    "OrchestratorDirective_v1": "remediation/OrchestratorDirective_v1.json",
    "ArbitroRemediateKickoff_v1": "remediation/ArbitroRemediateKickoff_v1.json",
    "DecisionPacketRef_v1": "remediation/DecisionPacketRef_v1.json",
    "MetaReview_v1": "review/MetaReview_v1.json",
}


def validate_artifact(artifact: dict, schema_name: str, schemas_dir: Path) -> tuple[bool, list[str]]:
    """
    Carga schema de schemas_dir, valida artifact con jsonschema.
    Retorna (is_valid, list_of_errors).
    """
    if not HAS_JSONSCHEMA:
        return True, ["jsonschema not installed — validation skipped"]

    schema_rel = SCHEMA_MAP.get(schema_name)
    if schema_rel is None:
        return False, [f"Unknown schema: {schema_name}"]

    schema_path = schemas_dir / schema_rel
    if not schema_path.exists():
        return False, [f"Schema file not found: {schema_path}"]

    with open(schema_path) as f:
        schema = json.load(f)

    errors = []
    try:
        jsonschema.validate(instance=artifact, schema=schema)
    except jsonschema.ValidationError as e:
        errors.append(f"{e.json_path}: {e.message}")
    except jsonschema.SchemaError as e:
        errors.append(f"Schema error: {e.message}")

    return len(errors) == 0, errors


def validate_file(artifact_path: Path, schemas_dir: Path) -> tuple[bool, list[str]]:
    """
    Infiere schema_name del filename, carga y valida.
    """
    filename = artifact_path.stem  # e.g., SourcesPack_v1_CRCT_20260215_Codex

    # Try to match against known schemas
    schema_name = _infer_schema_name(filename)
    if schema_name is None:
        return False, [f"Cannot infer schema from filename: {filename}"]

    with open(artifact_path) as f:
        artifact = json.load(f)

    return validate_artifact(artifact, schema_name, schemas_dir)


def validate_partial_truthpack(partial: dict) -> tuple[bool, list[str]]:
    """Validación ligera para outputs intermedios de TP_EXTRACTOR."""
    errors = []

    if "version_esquema" not in partial:
        errors.append("Missing version_esquema")

    # Check for at least one data section
    has_data = any(
        partial.get(k) is not None
        for k in ("historico_anual", "historico_trimestral", "balance_sheet_ultimo")
    )
    if not has_data:
        errors.append("No data sections found (historico_anual, historico_trimestral, or balance_sheet_ultimo)")

    return len(errors) == 0, errors


def _infer_schema_name(filename: str) -> str | None:
    """Infer schema name from artifact filename."""
    for schema_name in SCHEMA_MAP:
        if filename.startswith(schema_name):
            return schema_name
    return None


# ── Inter-step validation (§3.11) ──────────────────────────

_CANONICAL_AUTOCHEQUEO_KEYS = (
    "sin_metricas_inventadas",
    "claims_criticos_con_evidencia",
    "probabilidades_explicitas",
)


def _autochequeos_passed(report: dict) -> bool:
    """Derive autochequeos pass/fail from canonical log location.

    Canonical: report["log"]["autochequeos"] must contain the 3 required
    boolean keys, all True.
    Legacy fallback: report["autochequeos"]["passed"] == True (transition).
    Fail-closed: returns False if keys missing or wrong type.
    """
    log_block = report.get("log", {})
    if "autochequeos" in log_block:
        # Canonical path exists — evaluate strictly, no fallback
        log_ac = log_block["autochequeos"]
        return isinstance(log_ac, dict) and all(
            isinstance(log_ac.get(k), bool) and log_ac[k] is True
            for k in _CANONICAL_AUTOCHEQUEO_KEYS
        )
    # Legacy fallback — only when canonical block is absent
    legacy = report.get("autochequeos", {})
    if isinstance(legacy.get("passed"), bool) and legacy["passed"] is True:
        return True
    return False


def _is_catalyst_detection_artifact(art_name: str) -> bool:
    return art_name in ("CatalystDetection_v1", "_catalyst_detection")


def _is_forensic_detection_artifact(art_name: str) -> bool:
    return art_name in ("ForensicDetection_v1", "_forensic_detection")


def _has_list_field(payload: dict, field_name: str) -> bool:
    value = payload.get(field_name)
    return isinstance(value, list)


def _has_non_empty_list_field(payload: dict, field_name: str) -> bool:
    value = payload.get(field_name)
    return isinstance(value, list) and len(value) > 0


def _has_dict_field(payload: dict, field_name: str) -> bool:
    value = payload.get(field_name)
    return isinstance(value, dict)


# Checks a step must pass on the PREVIOUS step's output before proceeding.
# Tupla: (check_name, check_fn, error_msg, severity)
# severity: "error" = bloquea pipeline, "warning" = log pero continúa
INTER_STEP_CHECKS = {
    "ARBITRO": [
        ("bull_autochequeos",
         lambda d, art_name="": ("BULL" in art_name and _autochequeos_passed(d)),
         "BULL autochequeos did not pass", "error"),
        ("red_team_autochequeos",
         lambda d, art_name="": (("REDTEAM" in art_name or "RED_TEAM" in art_name) and _autochequeos_passed(d)),
         "RED_TEAM autochequeos did not pass", "error"),
    ],
    "RED_TEAM": [
        # Verify BULL has claims
        ("bull_has_claims", lambda d: len(d.get("claims", d.get("tesis", {}).get("claims", []))) > 0,
         "BULL output has no claims to challenge", "error"),
    ],
    "IMPLIED": [
        # Verify TruthPack has TTM revenue and market_cap (warning-only)
        ("tp_has_ttm_revenue",
         lambda d: (d.get("ttm", {}).get("ingresos_usd") is not None),
         "TruthPack no tiene ttm.ingresos_usd — IMPLIED puede generar resultados incompletos",
         "warning"),
        ("tp_has_market_cap",
         lambda d: (d.get("mercado", {}).get("market_cap_usd") is not None),
         "TruthPack no tiene mercado.market_cap_usd — IMPLIED puede generar resultados incompletos",
         "warning"),
    ],
    "CATALYST_SCORING": [
        ("catalyst_detection_claims_list_structure",
         lambda d, art_name="": _is_catalyst_detection_artifact(art_name) and _has_list_field(d, "claims_list"),
         "CATALYST_DETECTION inválido: falta claims_list (array)", "error"),
        ("catalyst_detection_candidates_structure",
         lambda d, art_name="": _is_catalyst_detection_artifact(art_name) and _has_list_field(d, "catalyst_candidates"),
         "CATALYST_DETECTION inválido: falta catalyst_candidates (array)", "error"),
        ("catalyst_detection_claims_non_empty",
         lambda d, art_name="": _is_catalyst_detection_artifact(art_name) and _has_non_empty_list_field(d, "claims_list"),
         "CATALYST_DETECTION con claims_list vacío", "warning"),
        ("catalyst_detection_candidates_non_empty",
         lambda d, art_name="": _is_catalyst_detection_artifact(art_name) and _has_non_empty_list_field(d, "catalyst_candidates"),
         "CATALYST_DETECTION con catalyst_candidates vacío", "warning"),
    ],
    "FORENSIC_SCORING": [
        ("forensic_detection_red_flags_structure",
         lambda d, art_name="": _is_forensic_detection_artifact(art_name) and _has_list_field(d, "red_flags"),
         "FORENSIC_DETECTION inválido: falta red_flags (array)", "error"),
        ("forensic_detection_liquidez_structure",
         lambda d, art_name="": _is_forensic_detection_artifact(art_name) and _has_dict_field(d, "liquidez"),
         "FORENSIC_DETECTION inválido: falta liquidez (object)", "error"),
        ("forensic_detection_puentes_structure",
         lambda d, art_name="": _is_forensic_detection_artifact(art_name) and _has_dict_field(d, "puentes"),
         "FORENSIC_DETECTION inválido: falta puentes (object)", "error"),
        ("forensic_detection_red_flags_non_empty",
         lambda d, art_name="": _is_forensic_detection_artifact(art_name) and _has_non_empty_list_field(d, "red_flags"),
         "FORENSIC_DETECTION con red_flags vacío", "warning"),
    ],
}


def validate_inter_step(step_name: str, predecessor_artifacts: dict[str, dict]) -> tuple[bool, list[str], list[str]]:
    """
    Validate cross-step consistency before running a step.
    predecessor_artifacts: {artifact_name: loaded_json_dict}
    Returns (all_errors_passed, list_of_errors, list_of_warnings).
    """
    checks = INTER_STEP_CHECKS.get(step_name, [])
    if not checks:
        return True, [], []

    errors = []
    warnings = []
    for check_tuple in checks:
        # Soportar tuplas de 3 (legacy) y 4 (con severity)
        if len(check_tuple) == 4:
            check_name, check_fn, error_msg, severity = check_tuple
        else:
            check_name, check_fn, error_msg = check_tuple
            severity = "error"

        # Try each predecessor artifact against the check
        passed = False
        for art_name, art_data in predecessor_artifacts.items():
            try:
                # Check functions can optionally accept art_name for targeted matching
                try:
                    result = check_fn(art_data, art_name=art_name)
                except TypeError:
                    result = check_fn(art_data)
                if result:
                    passed = True
                    break
            except (KeyError, TypeError, AttributeError):
                continue

        if not passed and predecessor_artifacts:
            msg = f"[{check_name}] {error_msg}"
            if severity == "warning":
                warnings.append(msg)
            else:
                errors.append(msg)

    return len(errors) == 0, errors, warnings


def validate_prefetch(caso_dir: Path, ticker: str, config_raw: dict) -> tuple[bool, list[str]]:
    """
    Validate that required pre-fetched data exists before pipeline.
    Checks sources/ dir for SECFetcher outputs, market data, etc.
    config_raw: the raw engine_config dict with prefetch_validation section.
    """
    prefetch_cfg = config_raw.get("prefetch_validation", {})
    if not prefetch_cfg.get("enabled", False):
        return True, []

    required = prefetch_cfg.get("required_before_pipeline", [])
    errors = []

    for req in required:
        if req == "SourcesPack":
            # Check that at least one SourcesPack file exists
            sources_files = list(caso_dir.glob("SourcesPack_v1_*.json"))
            if not sources_files:
                errors.append(f"No SourcesPack file found in {caso_dir}")
        elif req == "MarketData":
            # Check for market data in sources
            market_files = list(caso_dir.glob("*market*")) + list(caso_dir.glob("*MarketData*"))
            if not market_files:
                errors.append(f"No market data found in {caso_dir}")

    return len(errors) == 0, errors
