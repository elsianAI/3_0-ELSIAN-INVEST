"""Model quality statistics rollups (global + per-case).

Report-only analytics for deterministic quality voting.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl  # POSIX file locking
except ImportError:  # pragma: no cover
    fcntl = None

from .quality_voting import compute_quality_config_hash
from .validator import validate_artifact


def refresh_global_model_quality_stats(workspace: Path, qv_cfg: dict) -> dict:
    """Compute and persist global per-model quality rollup."""
    stats_cfg = _resolve_model_stats_cfg(qv_cfg)
    if not stats_cfg["enabled"]:
        return {"enabled": False, "reason": "model_stats disabled"}

    global_log_path = _resolve_path(workspace, qv_cfg.get("global_log_path", "_evaluacion/votes_log_v1.jsonl"))
    rollup_path = _resolve_path(workspace, stats_cfg["global_rollup_path"])
    history_path = _resolve_path(workspace, stats_cfg["global_history_jsonl_path"])
    schemas_dir = workspace / "_schemas"

    events_valid = []
    events_total = 0
    parse_errors = 0

    if global_log_path.exists():
        with open(global_log_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                events_total += 1
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                normalized = _normalize_vote_event(payload)
                if normalized is None:
                    continue
                events_valid.append(normalized)

    per_model_stats, fusion_comp = _compute_stats(events_valid, stats_cfg["min_samples_per_step_model"])
    generated_at = _utc_now_iso()
    run_id = _run_id()

    payload = {
        "version_esquema": "ModelQualityRollup_v1",
        "generated_at_utc": generated_at,
        "source_log_path": _as_workspace_relative(global_log_path, workspace),
        "coverage": {
            "events_total": events_total,
            "events_valid": len(events_valid),
            "parse_errors": parse_errors,
            "cases": len({e["caso_id"] for e in events_valid if e.get("caso_id")}),
            "canonical_steps": len({e["canonical_step_name"] for e in events_valid if e.get("canonical_step_name")}),
        },
        "min_samples_per_step_model": stats_cfg["min_samples_per_step_model"],
        "per_model_step_stats": per_model_stats,
        "fusion_comparison": fusion_comp,
        "_meta": {
            "config_hash": compute_quality_config_hash(qv_cfg),
        },
    }

    _ensure_valid_payload(payload, "ModelQualityRollup_v1", schemas_dir)
    _atomic_write_json(rollup_path, payload)

    snapshot_path = rollup_path.with_name(f"{rollup_path.stem}_{run_id}{rollup_path.suffix}")
    _atomic_write_json(snapshot_path, payload)

    history_event = {
        "version_esquema": "ModelQualityHistory_v1",
        "run_id": run_id,
        "generated_at_utc": generated_at,
        "rollup_file": _as_workspace_relative(snapshot_path, workspace),
        "coverage": payload["coverage"],
    }
    _append_jsonl_atomic(history_path, history_event)

    return {
        "enabled": True,
        "rollup_path": str(rollup_path),
        "snapshot_path": str(snapshot_path),
        "history_path": str(history_path),
        "coverage": payload["coverage"],
    }


def refresh_case_model_quality_stats(workspace: Path, case_dir: Path, qv_cfg: dict) -> dict | None:
    """Compute and persist per-case model quality summary."""
    stats_cfg = _resolve_model_stats_cfg(qv_cfg)
    if not stats_cfg["enabled"]:
        return None

    votes_dir = case_dir / qv_cfg.get("per_case_dirname", "_votes")
    if not votes_dir.exists():
        return None

    votes = []
    for vote_file in sorted(votes_dir.glob("StepVote_v1_*.json")):
        try:
            payload = json.loads(vote_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        normalized = _normalize_step_vote(payload)
        if normalized is None:
            continue
        votes.append(normalized)

    if not votes:
        return None

    per_model_stats, fusion_comp = _compute_stats(votes, stats_cfg["min_samples_per_step_model"])
    first = votes[0]
    schemas_dir = workspace / "_schemas"

    payload = {
        "version_esquema": "ModelQualityCase_v1",
        "generated_at_utc": _utc_now_iso(),
        "caso_id": first["caso_id"],
        "ticker": first["ticker"],
        "fecha_caso": first["fecha_caso"],
        "coverage": {
            "votes_total": len(votes),
            "canonical_steps": len({v["canonical_step_name"] for v in votes if v.get("canonical_step_name")}),
            "per_model_entries": len([v for v in votes if v.get("subject_kind") == "per_model"]),
        },
        "min_samples_per_step_model": stats_cfg["min_samples_per_step_model"],
        "per_model_step_stats": per_model_stats,
        "fusion_comparison": fusion_comp,
        "_meta": {
            "config_hash": compute_quality_config_hash(qv_cfg),
        },
    }

    _ensure_valid_payload(payload, "ModelQualityCase_v1", schemas_dir)
    out_path = votes_dir / stats_cfg["per_case_filename"]
    _atomic_write_json(out_path, payload)
    return {"case_path": str(out_path), "coverage": payload["coverage"]}


def _resolve_model_stats_cfg(qv_cfg: dict) -> dict:
    defaults = {
        "enabled": False,
        "global_rollup_path": "_evaluacion/model_quality_rollup_v1.json",
        "global_history_jsonl_path": "_evaluacion/model_quality_history_v1.jsonl",
        "per_case_filename": "model_quality_case_v1.json",
        "min_samples_per_step_model": int(qv_cfg.get("min_runs_for_stats", 20)),
    }
    user = qv_cfg.get("model_stats", {})
    if isinstance(user, dict):
        defaults.update(user)
    defaults["min_samples_per_step_model"] = max(1, int(defaults["min_samples_per_step_model"]))
    defaults["enabled"] = bool(defaults["enabled"])
    return defaults


def _compute_stats(events: list[dict], min_samples: int) -> tuple[list[dict], list[dict]]:
    per_model_map: dict[tuple[str, str], dict] = {}
    per_model_events: list[dict] = []
    fusion_by_group: dict[tuple[str, str, str], float] = {}
    latest_fusion_by_case_step: dict[tuple[str, str], tuple[str, float]] = {}

    for ev in events:
        score = float(ev["score_raw_0_100"])
        canonical = ev["canonical_step_name"]
        case_id = ev["caso_id"]
        timestamp = ev.get("timestamp_utc") or ""
        subject_kind = ev["subject_kind"]

        if subject_kind == "fusion":
            group_id = ev.get("vote_group_id")
            if isinstance(group_id, str) and group_id:
                fusion_by_group[(case_id, canonical, group_id)] = score
            key = (case_id, canonical)
            prev = latest_fusion_by_case_step.get(key)
            if prev is None or timestamp >= prev[0]:
                latest_fusion_by_case_step[key] = (timestamp, score)
            continue

        backend = ev.get("backend")
        if not backend:
            continue
        stat_key = (canonical, backend)
        stat = per_model_map.get(stat_key)
        if stat is None:
            stat = {
                "n": 0,
                "sum": 0.0,
                "hist": [0] * 101,
                "rules": Counter(),
                "last_seen_utc": None,
            }
            per_model_map[stat_key] = stat
        stat["n"] += 1
        stat["sum"] += score
        stat["hist"][_score_bin(score)] += 1
        for rule_name in ev.get("rules_failed", []):
            if isinstance(rule_name, str) and rule_name:
                stat["rules"][rule_name] += 1
        if not stat["last_seen_utc"] or timestamp > stat["last_seen_utc"]:
            stat["last_seen_utc"] = timestamp

        per_model_events.append(ev)

    per_model_stats = []
    for (canonical, backend), stat in sorted(per_model_map.items()):
        n = stat["n"]
        if n <= 0:
            continue
        per_model_stats.append({
            "canonical_step_name": canonical,
            "backend": backend,
            "n_votes": n,
            "mean": round(stat["sum"] / n, 2),
            "p25": round(_hist_percentile(stat["hist"], n, 0.25), 2),
            "median": round(_hist_percentile(stat["hist"], n, 0.50), 2),
            "p75": round(_hist_percentile(stat["hist"], n, 0.75), 2),
            "last_seen_utc": stat["last_seen_utc"],
            "sample_sufficiency": n >= min_samples,
            "rules_failed_top": [
                {"rule": name, "count": int(count)}
                for name, count in stat["rules"].most_common(5)
            ],
        })

    fusion_cmp_map: dict[tuple[str, str], dict] = {}
    for ev in per_model_events:
        case_id = ev["caso_id"]
        canonical = ev["canonical_step_name"]
        backend = ev["backend"]
        score = float(ev["score_raw_0_100"])
        group_id = ev.get("vote_group_id")

        fusion_score = None
        if isinstance(group_id, str) and group_id:
            fusion_score = fusion_by_group.get((case_id, canonical, group_id))
        if fusion_score is None:
            latest = latest_fusion_by_case_step.get((case_id, canonical))
            if latest is not None:
                fusion_score = latest[1]
        if fusion_score is None:
            continue

        cmp_key = (canonical, backend)
        cmp_stat = fusion_cmp_map.get(cmp_key)
        if cmp_stat is None:
            cmp_stat = {"n_pairs": 0, "delta_sum": 0.0, "wins": 0, "losses": 0, "ties": 0}
            fusion_cmp_map[cmp_key] = cmp_stat
        delta = score - float(fusion_score)
        cmp_stat["n_pairs"] += 1
        cmp_stat["delta_sum"] += delta
        if delta > 0:
            cmp_stat["wins"] += 1
        elif delta < 0:
            cmp_stat["losses"] += 1
        else:
            cmp_stat["ties"] += 1

    fusion_comparison = []
    for (canonical, backend), cmp_stat in sorted(fusion_cmp_map.items()):
        n_pairs = cmp_stat["n_pairs"]
        fusion_comparison.append({
            "canonical_step_name": canonical,
            "backend": backend,
            "n_pairs": n_pairs,
            "delta_vs_fusion_mean": round(cmp_stat["delta_sum"] / n_pairs, 2) if n_pairs else 0.0,
            "wins_vs_fusion_count": cmp_stat["wins"],
            "losses_vs_fusion_count": cmp_stat["losses"],
            "ties_vs_fusion_count": cmp_stat["ties"],
        })

    return per_model_stats, fusion_comparison


def _normalize_vote_event(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("version_esquema") != "VoteEvent_v1":
        return None
    score = payload.get("score_raw_0_100")
    if not isinstance(score, (int, float)):
        return None

    step_name = str(payload.get("step_name") or "")
    canonical = payload.get("canonical_step_name")
    if not isinstance(canonical, str) or not canonical:
        canonical = step_name.split("__model_", 1)[0] if "__model_" in step_name else step_name

    subject_kind = payload.get("subject_kind")
    if subject_kind not in ("fusion", "per_model"):
        subject_kind = "per_model" if "__model_" in step_name else "fusion"

    backend = payload.get("backend")
    if not isinstance(backend, str) or not backend:
        if subject_kind == "per_model" and "__model_" in step_name:
            backend = step_name.split("__model_", 1)[1]
        else:
            backend = None

    rules_failed = payload.get("rules_failed")
    if not isinstance(rules_failed, list):
        rules_failed = []
    else:
        rules_failed = [r for r in rules_failed if isinstance(r, str) and r]

    vote_group_id = payload.get("vote_group_id")
    if not isinstance(vote_group_id, str) or not vote_group_id:
        vote_group_id = None

    return {
        "caso_id": str(payload.get("caso_id") or ""),
        "ticker": str(payload.get("ticker") or ""),
        "fecha_caso": str(payload.get("fecha_caso") or ""),
        "step_name": step_name,
        "canonical_step_name": canonical,
        "subject_kind": subject_kind,
        "backend": backend,
        "score_raw_0_100": float(score),
        "rules_failed": rules_failed,
        "vote_group_id": vote_group_id,
        "timestamp_utc": str(payload.get("timestamp_utc") or ""),
    }


def _normalize_step_vote(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("version_esquema") != "StepVote_v1":
        return None
    score = payload.get("score_raw_0_100")
    if not isinstance(score, (int, float)):
        return None

    step_name = str(payload.get("step_name") or "")
    context = payload.get("context")
    if not isinstance(context, dict):
        context = {}
    canonical = context.get("canonical_step_name")
    if not isinstance(canonical, str) or not canonical:
        canonical = step_name.split("__model_", 1)[0] if "__model_" in step_name else step_name

    subject_kind = context.get("subject_kind")
    if subject_kind not in ("fusion", "per_model"):
        subject_kind = "per_model" if "__model_" in step_name else "fusion"

    meta = payload.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    backend = meta.get("backend")
    if not isinstance(backend, str) or not backend:
        if subject_kind == "per_model" and "__model_" in step_name:
            backend = step_name.split("__model_", 1)[1]
        else:
            backend = None

    rules = payload.get("rules")
    rules_failed = []
    if isinstance(rules, list):
        for item in rules:
            if isinstance(item, dict) and item.get("passed") is False:
                name = item.get("name")
                if isinstance(name, str) and name:
                    rules_failed.append(name)

    vote_group_id = context.get("vote_group_id")
    if not isinstance(vote_group_id, str) or not vote_group_id:
        vote_group_id = None

    return {
        "caso_id": str(payload.get("caso_id") or ""),
        "ticker": str(payload.get("ticker") or ""),
        "fecha_caso": str(payload.get("fecha_caso") or ""),
        "step_name": step_name,
        "canonical_step_name": canonical,
        "subject_kind": subject_kind,
        "backend": backend,
        "score_raw_0_100": float(score),
        "rules_failed": rules_failed,
        "vote_group_id": vote_group_id,
        "timestamp_utc": str(meta.get("created_at_utc") or ""),
    }


def _hist_percentile(hist: list[int], total: int, q: float) -> float:
    if total <= 0:
        return 0.0
    rank = max(1, int(math.ceil(q * total)))
    cumulative = 0
    for score, count in enumerate(hist):
        cumulative += count
        if cumulative >= rank:
            return float(score)
    return 100.0


def _score_bin(score: float) -> int:
    return max(0, min(100, int(round(score))))


def _ensure_valid_payload(payload: dict, schema_name: str, schemas_dir: Path) -> None:
    is_valid, errors = validate_artifact(payload, schema_name, schemas_dir)
    if not is_valid:
        raise ValueError(f"{schema_name} validation failed: {'; '.join(errors[:3])}")


def _resolve_path(workspace: Path, rel_or_abs: str) -> Path:
    path = Path(rel_or_abs)
    if path.is_absolute():
        return path
    return workspace / path


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_stats_", suffix=".json")
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


def _as_workspace_relative(path: Path, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
