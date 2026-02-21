"""Deterministic quality voting for LLM pipeline steps (v1).

Quality voting is report-only in v1: failures never block pipeline execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # POSIX file locking
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

from .config import EngineConfig
from .step_contracts import get_primary_schema
from .validator import SCHEMA_MAP, validate_artifact, validate_partial_truthpack


DEFAULT_QUALITY_VOTING = {
    "enabled": True,
    "include_operations": False,
    "mode": "deterministic_only",
    "policy": "report_only",
    "global_log_path": "_evaluacion/votes_log_v1.jsonl",
    "per_case_dirname": "_votes",
    "thresholds_enabled": False,
    "min_runs_for_stats": 20,
    "multi_subjects": {
        "enabled": False,
        "missing_policy": "partial_skipped",
    },
    "critical_fields": {},
}


def get_quality_voting_config(raw_config: dict) -> dict:
    """Return merged quality_voting config with deterministic defaults."""
    merged = copy.deepcopy(DEFAULT_QUALITY_VOTING)
    _deep_update(merged, raw_config.get("quality_voting", {}))
    return merged


def compute_quality_config_hash(quality_voting_config: dict) -> str:
    """Hash only the quality_voting subsection for traceability stability."""
    canonical = json.dumps(
        quality_voting_config,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def maybe_vote_step(
    config: EngineConfig,
    case_dir: Path,
    step_name: str,
    artifact_payload: dict | None = None,
    artifact_path: Path | None = None,
    model: str | None = None,
    backend: str | None = None,
    filing_records: list[dict] | None = None,
    lookup_step_name: str | None = None,
    vote_step_name: str | None = None,
    vote_group_id: str | None = None,
) -> dict | None:
    """Compute and persist deterministic vote for a step if voting is enabled.

    Returns a dict with generated paths when a vote is recorded, otherwise None.
    Raises on serialization/schema failures; caller is expected to degrade to warning.
    """
    qv_cfg = get_quality_voting_config(config.raw)
    canonical_step_name = lookup_step_name or step_name
    persisted_step_name = vote_step_name or step_name
    operation, step_def = _resolve_step_definition(config, canonical_step_name)

    if not _is_voteable(qv_cfg, operation, step_def):
        return None

    case_meta = _load_case_metadata(case_dir)
    config_hash = compute_quality_config_hash(qv_cfg)
    created_at = _utc_now_iso()

    if canonical_step_name == "TP_EXTRACTOR_FILING":
        if not filing_records:
            return None
        vote = _build_tp_extractor_vote(
            case_meta=case_meta,
            step_name=canonical_step_name,
            operation=operation or "PIPELINE",
            mode=qv_cfg.get("mode", "deterministic_only"),
            config_hash=config_hash,
            created_at=created_at,
            model=model,
            backend=backend,
            filing_records=filing_records,
        )
    else:
        if not isinstance(artifact_payload, dict):
            return None

        schema_name = _infer_schema_name(canonical_step_name, artifact_path)
        vote = _build_artifact_vote(
            config=config,
            case_meta=case_meta,
            step_name=canonical_step_name,
            operation=operation or "PIPELINE",
            mode=qv_cfg.get("mode", "deterministic_only"),
            config_hash=config_hash,
            created_at=created_at,
            model=model,
            backend=backend,
            artifact_payload=artifact_payload,
            artifact_path=artifact_path,
            schema_name=schema_name,
            critical_fields=qv_cfg.get("critical_fields", {}).get(schema_name or "", []),
        )

    # Persist vote under custom name (e.g., BULL__model_codex) while retaining
    # canonical step context for schema/DAG traceability.
    vote["step_name"] = persisted_step_name
    vote_context = vote.get("context")
    if not isinstance(vote_context, dict):
        vote_context = {}
        vote["context"] = vote_context
    vote_context["canonical_step_name"] = canonical_step_name
    vote_context["subject_kind"] = (
        "per_model" if "__model_" in persisted_step_name else "fusion"
    )
    if vote_group_id:
        vote_context["vote_group_id"] = vote_group_id

    schemas_dir = config.get_path("schemas")
    _ensure_valid_payload(vote, "StepVote_v1", schemas_dir)

    vote_path = _write_vote_file(config, case_dir, persisted_step_name, vote, qv_cfg)
    vote["_meta"]["artifact_file"] = _as_workspace_relative(vote_path, config.workspace)
    _atomic_write_json(vote_path, vote)

    event = _build_vote_event(vote, vote_path, config.workspace)
    _ensure_valid_payload(event, "VoteEvent_v1", schemas_dir)

    global_log_path = _resolve_global_log_path(config.workspace, qv_cfg)
    _append_jsonl_atomic(global_log_path, event)

    return {
        "vote_path": vote_path,
        "event_path": global_log_path,
        "score_raw_0_100": vote["score_raw_0_100"],
    }


def _build_artifact_vote(
    config: EngineConfig,
    case_meta: dict,
    step_name: str,
    operation: str,
    mode: str,
    config_hash: str,
    created_at: str,
    model: str | None,
    backend: str | None,
    artifact_payload: dict,
    artifact_path: Path | None,
    schema_name: str | None,
    critical_fields: list[str],
) -> dict:
    schemas_dir = config.get_path("schemas")

    rule_schema = _rule_schema_valid(artifact_payload, schema_name, schemas_dir)
    rule_critical = _rule_critical_fields(
        artifact_payload,
        critical_fields,
        step_name=step_name,
    )
    rule_nulls = _rule_null_ratio(artifact_payload)

    rules = [rule_schema, rule_critical, rule_nulls]
    score = _weighted_score(rules)

    return {
        "version_esquema": "StepVote_v1",
        "caso_id": case_meta["caso_id"],
        "ticker": case_meta["ticker"],
        "fecha_caso": case_meta["fecha_caso"],
        "step_name": step_name,
        "operation": operation,
        "mode": mode,
        "subject_type": "single_artifact",
        "schema_name": schema_name,
        "score_raw_0_100": round(score, 2),
        "rules": rules,
        "context": {
            "critical_fields_checked": len(critical_fields),
            "critical_fields": critical_fields,
        },
        "_meta": {
            "created_at_utc": created_at,
            "config_hash": config_hash,
            "model": model,
            "backend": backend,
            "artifact_file": _as_workspace_relative(artifact_path, config.workspace) if artifact_path else None,
        },
    }


def _build_tp_extractor_vote(
    case_meta: dict,
    step_name: str,
    operation: str,
    mode: str,
    config_hash: str,
    created_at: str,
    model: str | None,
    backend: str | None,
    filing_records: list[dict],
) -> dict:
    section_keys = ["historico_anual", "historico_trimestral", "balance_sheet_ultimo"]

    per_filing = []
    valid_scores = []

    for record in filing_records:
        payload = record.get("output")
        if not isinstance(payload, dict):
            continue

        valid = record.get("valid")
        errors = record.get("errors")
        if valid is None:
            valid, errors = validate_partial_truthpack(payload)

        score = _filing_sections_score(payload, section_keys)
        if valid:
            valid_scores.append(score)

        per_filing.append({
            "filing_index": record.get("index"),
            "valid": bool(valid),
            "score_raw_0_100": round(score, 2),
            "errors": errors or [],
        })

    aggregate = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0

    rule = {
        "name": "filing_sections_completeness",
        "weight": 1.0,
        "score_raw_0_100": round(aggregate, 2),
        "passed": len(valid_scores) > 0,
        "details": f"valid_filings={len(valid_scores)}/{len(per_filing)}",
    }

    return {
        "version_esquema": "StepVote_v1",
        "caso_id": case_meta["caso_id"],
        "ticker": case_meta["ticker"],
        "fecha_caso": case_meta["fecha_caso"],
        "step_name": step_name,
        "operation": operation,
        "mode": mode,
        "subject_type": "tp_extractor_filing_aggregate",
        "schema_name": None,
        "score_raw_0_100": round(aggregate, 2),
        "rules": [rule],
        "context": {
            "filings_total": len(per_filing),
            "filings_valid": len(valid_scores),
            "filings": per_filing,
            "sections_scored": section_keys,
        },
        "_meta": {
            "created_at_utc": created_at,
            "config_hash": config_hash,
            "model": model,
            "backend": backend,
            "artifact_file": None,
        },
    }


def _resolve_step_definition(config: EngineConfig, step_name: str) -> tuple[str | None, dict | None]:
    for operation, steps in config.pipeline_dag.items():
        for step_def in steps:
            if step_def.get("step") == step_name:
                return operation, step_def
    return None, None


def _is_voteable(qv_cfg: dict, operation: str | None, step_def: dict | None) -> bool:
    if not qv_cfg.get("enabled", False):
        return False
    if step_def is None:
        return False

    step_type = step_def.get("type", "llm")
    if step_type == "python":
        return False

    if qv_cfg.get("include_operations", False):
        return True

    return operation == "PIPELINE"


def _infer_schema_name(step_name: str, artifact_path: Path | None) -> str | None:
    schema = get_primary_schema(step_name)
    if schema:
        return schema

    if artifact_path:
        stem = artifact_path.stem
        # Longest prefix first for deterministic matching
        for schema_name in sorted(SCHEMA_MAP.keys(), key=len, reverse=True):
            if stem.startswith(schema_name):
                return schema_name
    return None


def _rule_schema_valid(payload: dict, schema_name: str | None, schemas_dir: Path) -> dict:
    if not schema_name:
        return {
            "name": "schema_valid",
            "weight": 1.0,
            "score_raw_0_100": 100.0,
            "passed": True,
            "details": "schema_not_mapped",
        }

    is_valid, errors = validate_artifact(payload, schema_name, schemas_dir)
    details = None if is_valid else "; ".join(errors[:3])
    return {
        "name": "schema_valid",
        "weight": 1.0,
        "score_raw_0_100": 100.0 if is_valid else 0.0,
        "passed": is_valid,
        "details": details,
    }


def _rule_critical_fields(
    payload: dict,
    critical_fields: list[str],
    step_name: str | None = None,
) -> dict:
    if not critical_fields:
        return {
            "name": "critical_fields_completeness",
            "weight": 1.0,
            "score_raw_0_100": 100.0,
            "passed": True,
            "details": "no_critical_fields_configured",
        }

    payload_candidates = [payload]
    # ARBITRO may return remediation wrapper:
    # {version_esquema: ArbitroRemediateKickoff_v1, decision_packet: {...DecisionPacket_v2...}}
    if step_name == "ARBITRO":
        nested = payload.get("decision_packet")
        if isinstance(nested, dict):
            payload_candidates.append(nested)

    present = 0
    missing = []
    for field_path in critical_fields:
        found = False
        for candidate in payload_candidates:
            exists, value = _dig(candidate, field_path)
            if exists and _is_non_empty(value):
                found = True
                break
        if found:
            present += 1
            continue
        missing.append(field_path)

    score = (present / len(critical_fields)) * 100.0
    return {
        "name": "critical_fields_completeness",
        "weight": 1.0,
        "score_raw_0_100": round(score, 2),
        "passed": len(missing) == 0,
        "details": None if not missing else f"missing={missing}",
    }


def _rule_null_ratio(payload: dict) -> dict:
    total, nulls = _count_leaf_values(payload)
    if total == 0:
        return {
            "name": "null_ratio",
            "weight": 1.0,
            "score_raw_0_100": 0.0,
            "passed": False,
            "details": "empty_payload",
        }

    ratio = nulls / total
    score = max(0.0, (1.0 - ratio) * 100.0)
    return {
        "name": "null_ratio",
        "weight": 1.0,
        "score_raw_0_100": round(score, 2),
        "passed": ratio <= 0.40,
        "details": f"nulls={nulls}/{total} ({ratio:.2%})",
    }


def _filing_sections_score(payload: dict, section_keys: list[str]) -> float:
    with_data = 0
    for key in section_keys:
        value = payload.get(key)
        if isinstance(value, list):
            if value:
                with_data += 1
        elif isinstance(value, dict):
            if value:
                with_data += 1
        elif value is not None:
            with_data += 1
    return (with_data / len(section_keys)) * 100.0


def _weighted_score(rules: list[dict]) -> float:
    total_weight = sum(float(rule.get("weight", 0.0)) for rule in rules)
    if total_weight <= 0:
        return 0.0
    weighted_sum = sum(float(rule.get("score_raw_0_100", 0.0)) * float(rule.get("weight", 0.0)) for rule in rules)
    return weighted_sum / total_weight


def _dig(data: dict, dotted_path: str) -> tuple[bool, object]:
    current = data
    for part in dotted_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def _is_non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _count_leaf_values(value: object) -> tuple[int, int]:
    if isinstance(value, dict):
        total = 0
        nulls = 0
        for child in value.values():
            child_total, child_nulls = _count_leaf_values(child)
            total += child_total
            nulls += child_nulls
        return total, nulls

    if isinstance(value, list):
        total = 0
        nulls = 0
        for child in value:
            child_total, child_nulls = _count_leaf_values(child)
            total += child_total
            nulls += child_nulls
        return total, nulls

    return (1, 1) if value is None else (1, 0)


def _load_case_metadata(case_dir: Path) -> dict:
    ticker = case_dir.parent.name
    fecha_caso = case_dir.name.split("_", 1)[0]
    caso_id = f"CASE_{fecha_caso.replace('-', '')}_{ticker}"

    state_path = case_dir / "_estado.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            ticker = state.get("ticker") or ticker
            fecha_caso = state.get("fecha_caso") or fecha_caso
            caso_id = state.get("caso_id") or caso_id
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "caso_id": str(caso_id),
        "ticker": str(ticker),
        "fecha_caso": str(fecha_caso),
    }


def _write_vote_file(config: EngineConfig, case_dir: Path, step_name: str, vote: dict, qv_cfg: dict) -> Path:
    votes_dir = case_dir / qv_cfg.get("per_case_dirname", "_votes")
    votes_dir.mkdir(parents=True, exist_ok=True)

    ts = vote.get("_meta", {}).get("created_at_utc", _utc_now_iso())
    safe_ts = ts.replace(":", "").replace("-", "").replace("+", "_")
    vote_filename = f"StepVote_v1_{step_name}_{safe_ts}.json"
    return votes_dir / vote_filename


def _build_vote_event(vote: dict, vote_path: Path, workspace: Path) -> dict:
    failed_rules = [r.get("name", "?") for r in vote.get("rules", []) if not r.get("passed", False)]
    context = vote.get("context")
    if not isinstance(context, dict):
        context = {}
    canonical_step_name = context.get("canonical_step_name")
    if not isinstance(canonical_step_name, str) or not canonical_step_name:
        step_name = str(vote.get("step_name", ""))
        canonical_step_name = step_name.split("__model_", 1)[0] if "__model_" in step_name else step_name
    subject_kind = context.get("subject_kind")
    if subject_kind not in ("fusion", "per_model"):
        subject_kind = "per_model" if "__model_" in str(vote.get("step_name", "")) else "fusion"
    vote_group_id = context.get("vote_group_id")
    if not isinstance(vote_group_id, str) or not vote_group_id:
        vote_group_id = None

    return {
        "version_esquema": "VoteEvent_v1",
        "event_id": str(uuid.uuid4()),
        "timestamp_utc": _utc_now_iso(),
        "caso_id": vote.get("caso_id"),
        "ticker": vote.get("ticker"),
        "fecha_caso": vote.get("fecha_caso"),
        "step_name": vote.get("step_name"),
        "operation": vote.get("operation"),
        "score_raw_0_100": vote.get("score_raw_0_100", 0.0),
        "vote_file": _as_workspace_relative(vote_path, workspace),
        "rules_failed": failed_rules,
        "config_hash": vote.get("_meta", {}).get("config_hash"),
        "model": vote.get("_meta", {}).get("model"),
        "backend": vote.get("_meta", {}).get("backend"),
        "canonical_step_name": canonical_step_name,
        "subject_kind": subject_kind,
        "vote_group_id": vote_group_id,
    }


def _resolve_global_log_path(workspace: Path, qv_cfg: dict) -> Path:
    rel_or_abs = qv_cfg.get("global_log_path", DEFAULT_QUALITY_VOTING["global_log_path"])
    path = Path(rel_or_abs)
    if path.is_absolute():
        return path
    return workspace / path


def _ensure_valid_payload(payload: dict, schema_name: str, schemas_dir: Path) -> None:
    is_valid, errors = validate_artifact(payload, schema_name, schemas_dir)
    if not is_valid:
        raise ValueError(f"{schema_name} validation failed: {'; '.join(errors[:3])}")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_vote_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        Path(tmp_path).replace(path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _append_jsonl_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

    with open(path, "a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _as_workspace_relative(path: Path | None, workspace: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _deep_update(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
