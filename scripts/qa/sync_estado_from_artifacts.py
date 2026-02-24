#!/usr/bin/env python3
"""
Sincroniza _estado.json desde DecisionPacket y limpia _errors stale (one-shot).

Uso:
  python3 scripts/qa/sync_estado_from_artifacts.py
  python3 scripts/qa/sync_estado_from_artifacts.py --apply
  python3 scripts/qa/sync_estado_from_artifacts.py --tickers ACLS,ACVA --date 2026-02-15 --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE))

from engine.state import load_state, save_state  # noqa: E402

DEFAULT_TICKERS = ["ACLS", "ACVA", "INMD", "TZOO"]
DEFAULT_DATE = "2026-02-15"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync _estado.json fields from DecisionPacket artifacts")
    p.add_argument("--tickers", default=",".join(DEFAULT_TICKERS), help="Comma-separated tickers")
    p.add_argument("--date", default=DEFAULT_DATE, help="Case date (YYYY-MM-DD)")
    p.add_argument("--apply", action="store_true", help="Persist changes (default is dry-run)")
    p.add_argument("--backup-dir", default="tmp/_estado_backups", help="Backup dir for original _estado.json")
    return p.parse_args()


def parse_tickers(value: str) -> list[str]:
    return [t.strip().upper() for t in value.split(",") if t.strip()]


def select_decision_packet(case_dir: Path, ticker: str) -> Path | None:
    """Deterministic selection (no mtime)."""
    p1 = sorted(case_dir.glob(f"DecisionPacket_v2_{ticker}_*_Engine.json"))
    if p1:
        return p1[-1]

    p2 = case_dir / "DecisionPacket_v2.json"
    if p2.exists():
        return p2

    fallback = sorted(case_dir.glob("DecisionPacket*.json"))
    if fallback:
        return fallback[-1]

    return None


def _get_dual(data: dict, wrapper: dict, *keys):
    for k in keys:
        v = data.get(k)
        if v is not None:
            return v
    for k in keys:
        v = wrapper.get(k)
        if v is not None:
            return v
    return None


def _to_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def extract_fields(packet: dict) -> dict[str, Any]:
    """Mirror current engine.router._extract_decision_fields logic."""
    wrapper = packet.get("decision_packet", {}) if isinstance(packet.get("decision_packet"), dict) else {}

    decision = _get_dual(packet, wrapper, "decision", "Decision")
    score = _get_dual(packet, wrapper, "score", "Score")
    confianza = _get_dual(packet, wrapper, "confianza", "Confianza")
    probabilistica = _get_dual(packet, wrapper, "probabilistica")
    sizing = None
    modelo_principal = None

    resumen = _get_dual(packet, wrapper, "resumen_ejecutivo") or {}
    if isinstance(resumen, dict):
        if decision is None:
            decision = resumen.get("decision")
        if score is None:
            score = resumen.get("score_global", resumen.get("score"))
        if confianza is None:
            confianza = resumen.get("confianza_global_0_1", resumen.get("confianza", ""))
        sizing = resumen.get("tamaño_recomendado_pct_cartera")

    if score is None:
        scoring = _get_dual(packet, wrapper, "scoring_preliminar") or {}
        if isinstance(scoring, dict):
            score = scoring.get("total_0_100", scoring.get("total"))

    if probabilistica is None:
        dp = _get_dual(packet, wrapper, "decision_probabilistica") or {}
        if isinstance(dp, dict) and dp:
            probabilistica = dp

    meta = packet.get("_meta", {}) if isinstance(packet.get("_meta"), dict) else {}
    if not meta and isinstance(wrapper.get("_meta"), dict):
        meta = wrapper.get("_meta")
    modelos = (meta.get("fusion") or {}).get("modelos_usados")
    if isinstance(modelos, list) and modelos:
        joined = "+".join(str(m) for m in modelos if m)
        if joined:
            modelo_principal = joined

    norm_score = _to_float(score)
    norm_score = int(round(_clamp(norm_score, 0.0, 100.0))) if norm_score is not None else 0
    norm_confianza = _to_float(confianza)
    if norm_confianza is not None:
        norm_confianza = _clamp(norm_confianza, 0.0, 1.0)
    norm_sizing = _to_float(sizing)
    if norm_sizing is not None:
        norm_sizing = _clamp(norm_sizing, 0.0, 100.0)

    # ── Monitor fields from salida_para_siguiente_agente + control ──
    salida = _get_dual(packet, wrapper, "salida_para_siguiente_agente") or {}
    if not isinstance(salida, dict):
        salida = {}
    control = _get_dual(packet, wrapper, "control") or {}
    if not isinstance(control, dict):
        control = {}

    raw_next_step = control.get("next_step") or salida.get("next_step")
    next_step = str(raw_next_step).strip() if raw_next_step else None

    raw_fecha = salida.get("proxima_revision_sugerida")
    proxima_revision = None
    if isinstance(raw_fecha, str) and raw_fecha.strip():
        try:
            from datetime import date as _date
            parsed = datetime.strptime(raw_fecha.strip(), "%Y-%m-%d").date()
            proxima_revision = parsed.isoformat()
        except ValueError:
            pass

    raw_estado_caso = salida.get("estado_caso")
    estado_caso = str(raw_estado_caso).strip() if raw_estado_caso else None

    raw_monitor_input = salida.get("monitor_input_recomendado")
    monitor_input = str(raw_monitor_input).strip() if raw_monitor_input else None

    return {
        "decision": decision,
        "score": norm_score,
        "confianza": norm_confianza,
        "sizing": norm_sizing,
        "modelo_principal": modelo_principal,
        "probabilistica": probabilistica,
        "next_step": next_step,
        "proxima_revision": proxima_revision,
        "estado_caso": estado_caso,
        "monitor_input": monitor_input,
    }


def _clone(obj: Any) -> Any:
    return json.loads(json.dumps(obj, ensure_ascii=False))


def sync_case(
    *,
    ticker: str,
    date: str,
    apply: bool,
    backup_dir: Path,
) -> dict[str, Any]:
    case_dir = WORKSPACE / "casos" / ticker / date
    case_result: dict[str, Any] = {
        "ticker": ticker,
        "date": date,
        "case_dir": str(case_dir.relative_to(WORKSPACE)),
        "dry_run": not apply,
        "decision_packet": None,
        "field_changes": [],
        "stale_errors_removed": [],
        "changed": False,
        "applied": False,
        "backup_path": None,
        "error": None,
    }

    try:
        if not case_dir.exists():
            case_result["error"] = "case_dir_not_found"
            return case_result

        state = load_state(case_dir)
        original_state = _clone(state)

        packet_path = select_decision_packet(case_dir, ticker)
        if not packet_path:
            case_result["error"] = "decision_packet_not_found"
            return case_result

        case_result["decision_packet"] = str(packet_path.relative_to(WORKSPACE))
        packet = json.loads(packet_path.read_text())
        extracted = extract_fields(packet)
        case_result["extracted"] = extracted

        # Update decision fields only if a decision was extracted (same behavior as router)
        if extracted.get("decision") is not None:
            desired = {
                "decision": str(extracted["decision"]),
                "score": int(extracted["score"]) if extracted.get("score") is not None else 0,
                "confianza": extracted.get("confianza"),
                "sizing": extracted.get("sizing"),
                "modelo_principal": extracted.get("modelo_principal"),
                "next_step": extracted.get("next_step"),
                "proxima_revision": extracted.get("proxima_revision"),
                "estado_caso": extracted.get("estado_caso"),
                "monitor_input": extracted.get("monitor_input"),
            }
            # Fields that are optional and should be skipped if None
            optional_skip = ("sizing", "modelo_principal", "next_step",
                             "proxima_revision", "estado_caso", "monitor_input")
            for field, new_val in desired.items():
                if new_val is None and field in optional_skip:
                    continue
                old_val = state.get(field)
                if field == "score":
                    # Enforce schema type (integer) even if value-equivalent float exists.
                    should_update = (type(old_val) is not int) or (old_val != new_val)
                else:
                    should_update = old_val != new_val
                if should_update:
                    case_result["field_changes"].append(
                        {"field": field, "old": old_val, "new": new_val}
                    )
                    state[field] = new_val

            if extracted.get("probabilistica") is not None:
                new_prob = extracted["probabilistica"]
                old_prob = state.get("probabilistica")
                if old_prob != new_prob:
                    case_result["field_changes"].append(
                        {"field": "probabilistica", "old": old_prob, "new": new_prob}
                    )
                    state["probabilistica"] = new_prob

        # Cleanup stale _errors: remove only when pipeline[step].estado == DONE
        errors = state.get("_errors")
        pipeline = state.get("pipeline", {})
        if isinstance(errors, dict):
            for step in list(errors.keys()):
                if pipeline.get(step, {}).get("estado") == "DONE":
                    case_result["stale_errors_removed"].append(step)
                    del errors[step]

        case_result["changed"] = bool(case_result["field_changes"] or case_result["stale_errors_removed"])

        if apply and case_result["changed"]:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            bdir = backup_dir / ticker / date
            bdir.mkdir(parents=True, exist_ok=True)
            backup_path = bdir / f"_estado_{ts}.json"
            backup_path.write_text(json.dumps(original_state, indent=2, ensure_ascii=False))
            case_result["backup_path"] = str(backup_path.relative_to(WORKSPACE))

            save_state(case_dir, state)
            case_result["applied"] = True

    except Exception as exc:  # noqa: BLE001
        case_result["error"] = str(exc)

    return case_result


def main() -> int:
    args = parse_args()
    tickers = parse_tickers(args.tickers)
    apply = bool(args.apply)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    backup_dir = Path(args.backup_dir)
    if not backup_dir.is_absolute():
        backup_dir = WORKSPACE / backup_dir

    print("=" * 80)
    print("SYNC _estado.json FROM ARTIFACTS")
    print("=" * 80)
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"Date: {args.date}")
    print()

    results = []
    for ticker in tickers:
        r = sync_case(ticker=ticker, date=args.date, apply=apply, backup_dir=backup_dir)
        results.append(r)

        status = "ERROR" if r.get("error") else ("CHANGED" if r.get("changed") else "NO-CHANGE")
        print(f"[{ticker}] {status}")
        if r.get("decision_packet"):
            print(f"  decision_packet: {r['decision_packet']}")
        if r.get("field_changes"):
            for ch in r["field_changes"]:
                print(f"  field {ch['field']}: {ch['old']} -> {ch['new']}")
        if r.get("stale_errors_removed"):
            print(f"  stale _errors removed: {', '.join(r['stale_errors_removed'])}")
        if r.get("backup_path"):
            print(f"  backup: {r['backup_path']}")
        if r.get("error"):
            print(f"  error: {r['error']}")

    totals = {
        "cases": len(results),
        "changed": sum(1 for r in results if r.get("changed")),
        "applied": sum(1 for r in results if r.get("applied")),
        "errors": sum(1 for r in results if r.get("error")),
        "field_changes": sum(len(r.get("field_changes", [])) for r in results),
        "stale_errors_removed": sum(len(r.get("stale_errors_removed", [])) for r in results),
    }

    output = {
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": not apply,
        "tickers": tickers,
        "date": args.date,
        "invocation": {
            "tickers": tickers,
            "date": args.date,
            "dry_run": not apply,
            "apply": apply,
            "backup_dir": str(backup_dir),
        },
        "totals": totals,
        "cases": results,
    }

    output_dir = WORKSPACE / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / "_sync_estado_results.json"
    history_path = output_dir / f"_sync_estado_results_{run_id}.json"

    payload = json.dumps(output, indent=2, ensure_ascii=False)
    latest_path.write_text(payload)
    history_path.write_text(payload)

    # Optional rolling index for quick audit trails. Non-blocking on failure.
    history_index = output_dir / "_sync_estado_history.jsonl"
    try:
        history_entry = {
            "run_id": run_id,
            "generated_at_utc": output["generated_at_utc"],
            "dry_run": output["dry_run"],
            "totals": totals,
            "history_path": str(history_path.relative_to(WORKSPACE)),
        }
        with history_index.open("a", encoding="utf-8") as f:
            f.write(json.dumps(history_entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[sync] WARNING: could not append {history_index.relative_to(WORKSPACE)}: {exc}", file=sys.stderr)

    print("\n" + "=" * 80)
    print("RESUMEN")
    print("=" * 80)
    print(json.dumps(totals, indent=2, ensure_ascii=False))
    print(f"\nRun ID: {run_id}")
    print(f"Resultados (latest): {latest_path.relative_to(WORKSPACE)}")
    print(f"Resultados (history): {history_path.relative_to(WORKSPACE)}")
    print(f"Índice historial: {history_index.relative_to(WORKSPACE)}")

    return 1 if totals["errors"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
