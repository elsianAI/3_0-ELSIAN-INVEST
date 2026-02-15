#!/usr/bin/env python3
"""
benchmark_comparator.py — Metricas objetivas de comparacion inter-modelo.

Compara dos directorios de caso del mismo ticker y genera metricas cuantitativas.

Uso:
    python3 scripts/benchmark_comparator.py casos/CRCT/2026-02-12_Claude casos/CRCT/2026-02-12_Codex

Output: stdout JSON con metricas comparativas.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_artefact(case_dir: Path, prefix: str) -> Optional[Dict[str, Any]]:
    """Find and load the first JSON matching prefix (excluding model-suffixed ones).

    Model suffix is detected generically: any trailing _Word before .json where Word
    is CamelCase or lowercase alpha (e.g., _Claude, _Codex, _GPT5, _codex53).
    """
    candidates = sorted(case_dir.glob(f"{prefix}*.json"))
    # Prefer canonical (no model suffix) — generic pattern instead of hardcoded names
    preferred = [
        p for p in candidates
        if not re.search(r"_[A-Za-z][A-Za-z0-9]*\.", p.name)
        or p.stem == prefix  # exact match is always preferred
    ]
    for path in (preferred or candidates):
        data = load_json(path)
        if data:
            return data
    return None


def count_non_null(obj: Any, path: str = "") -> Tuple[int, int]:
    """Count (total_fields, non_null_fields) recursively."""
    if obj is None:
        return 1, 0
    if isinstance(obj, (str, int, float, bool)):
        return 1, 1
    if isinstance(obj, list):
        total, filled = 0, 0
        for item in obj:
            t, f = count_non_null(item)
            total += t
            filled += f
        return max(total, 1), filled
    if isinstance(obj, dict):
        total, filled = 0, 0
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            t, f = count_non_null(v, f"{path}.{k}")
            total += t
            filled += f
        return max(total, 1), filled
    return 1, 1


def completitud(data: Optional[Dict]) -> float:
    if not data:
        return 0.0
    total, filled = count_non_null(data)
    return round(filled / max(total, 1), 3)


def count_claims(agent_reports: List[Dict]) -> int:
    total = 0
    for report in agent_reports:
        claims = report.get("claims", [])
        if isinstance(claims, list):
            total += len(claims)
    return total


def count_claims_con_evidencia(agent_reports: List[Dict], sources_pack: Optional[Dict]) -> int:
    source_ids = set()
    if sources_pack:
        for f in sources_pack.get("fuentes", []):
            sid = f.get("source_id")
            if sid:
                source_ids.add(sid)

    count = 0
    for report in agent_reports:
        for claim in report.get("claims", []):
            evidencias = claim.get("evidencias", [])
            if isinstance(evidencias, list):
                for ev in evidencias:
                    sid = ev.get("source_id", "")
                    if sid in source_ids:
                        count += 1
                        break
    return count


def count_predicciones(agent_reports: List[Dict]) -> Tuple[int, int]:
    total = 0
    con_prob = 0
    for report in agent_reports:
        preds = report.get("predicciones_calibracion", [])
        if isinstance(preds, list):
            total += len(preds)
            for pred in preds:
                prob = pred.get("probabilidad_0_1")
                if prob is not None:
                    con_prob += 1
    return total, con_prob


def count_falsaciones_concretas(agent_reports: List[Dict]) -> int:
    count = 0
    for report in agent_reports:
        for claim in report.get("claims", []):
            falsacion = claim.get("falsacion", {})
            if isinstance(falsacion, dict):
                test = falsacion.get("test", "")
                if isinstance(test, str) and len(test) > 20:
                    # Heuristic: concrete if contains a number or date
                    if re.search(r"\d", test):
                        count += 1
    return count


def check_coherencia_decision(decision_packet: Optional[Dict]) -> Optional[bool]:
    if not decision_packet:
        return None
    decision = decision_packet.get("decision_probabilistica", {})
    if not isinstance(decision, dict):
        decision = {}
    veredicto = decision.get("veredicto_final", "")
    gates = decision_packet.get("gates", {})
    if not isinstance(gates, dict):
        return None

    if veredicto in ("INVERTIR", "WATCHLIST_ALTA"):
        # All gates should be PASS
        for gate_name, gate_val in gates.items():
            if isinstance(gate_val, dict):
                status = gate_val.get("status", "")
                if status == "FAIL":
                    return False
        return True
    return True


def get_score_from_estado(case_dir: Path) -> Optional[float]:
    """Primary score source: _estado.json.score (canonical)."""
    estado = load_json(case_dir / "_estado.json")
    if estado:
        score = estado.get("score")
        if isinstance(score, (int, float)):
            return float(score)
    return None


def get_score(decision_packet: Optional[Dict], case_dir: Optional[Path] = None) -> Optional[float]:
    """Score priority: (1) _estado.json.score, (2) scoring_preliminar.total_0_100, (3) legacy decision_probabilistica.score_0_100."""
    # Priority 1: _estado.json
    if case_dir is not None:
        estado_score = get_score_from_estado(case_dir)
        if estado_score is not None:
            return estado_score
    if not decision_packet:
        return None
    # Priority 2: scoring_preliminar.total_0_100
    scoring = decision_packet.get("scoring_preliminar", {})
    if isinstance(scoring, dict):
        total = scoring.get("total_0_100")
        if isinstance(total, (int, float)):
            return float(total)
    # Priority 3: legacy decision_probabilistica.score_0_100
    dp = decision_packet.get("decision_probabilistica", {})
    if isinstance(dp, dict):
        score = dp.get("score_0_100")
        if isinstance(score, (int, float)):
            return float(score)
    return None


def get_modelo(case_dir: Path) -> Optional[str]:
    estado = load_json(case_dir / "_estado.json")
    if estado:
        return estado.get("modelo_principal")
    return None


def get_timestamp(case_dir: Path) -> Optional[str]:
    estado = load_json(case_dir / "_estado.json")
    if estado and isinstance(estado.get("_meta"), dict):
        return estado["_meta"].get("ultima_actualizacion")
    return None


def compare(dir_a: Path, dir_b: Path) -> Dict[str, Any]:
    # Load artefacts
    tp_a = find_artefact(dir_a, "TruthPack_v1")
    tp_b = find_artefact(dir_b, "TruthPack_v1")
    ie_a = find_artefact(dir_a, "ImpliedExpectations_v1")
    ie_b = find_artefact(dir_b, "ImpliedExpectations_v1")
    sp_a = find_artefact(dir_a, "SourcesPack_v1")
    sp_b = find_artefact(dir_b, "SourcesPack_v1")
    dp_a = find_artefact(dir_a, "DecisionPacket_v2") or find_artefact(dir_a, "DecisionPacket_v1")
    dp_b = find_artefact(dir_b, "DecisionPacket_v2") or find_artefact(dir_b, "DecisionPacket_v1")

    agent_prefixes = ["AgentReport_v1_CATALYST", "AgentReport_v1_FORENSIC",
                      "AgentReport_v1_BULL", "AgentReport_v1_REDTEAM",
                      "AgentReport_v1_RED_TEAM"]
    ar_a = [find_artefact(dir_a, p) for p in agent_prefixes]
    ar_a = [r for r in ar_a if r]
    ar_b = [find_artefact(dir_b, p) for p in agent_prefixes]
    ar_b = [r for r in ar_b if r]

    pred_a_total, pred_a_prob = count_predicciones(ar_a)
    pred_b_total, pred_b_prob = count_predicciones(ar_b)

    score_a = get_score(dp_a, dir_a)
    score_b = get_score(dp_b, dir_b)

    return {
        "version_esquema": "BenchmarkComparison_v1",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "directorio_a": str(dir_a),
        "directorio_b": str(dir_b),
        "modelo_a": get_modelo(dir_a),
        "modelo_b": get_modelo(dir_b),
        "metricas": {
            "completitud_truth_pack": {
                "a": completitud(tp_a),
                "b": completitud(tp_b),
            },
            "completitud_implied": {
                "a": completitud(ie_a),
                "b": completitud(ie_b),
            },
            "claims_count": {
                "a": count_claims(ar_a),
                "b": count_claims(ar_b),
            },
            "claims_con_evidencia": {
                "a": count_claims_con_evidencia(ar_a, sp_a),
                "b": count_claims_con_evidencia(ar_b, sp_b),
            },
            "falsaciones_concretas": {
                "a": count_falsaciones_concretas(ar_a),
                "b": count_falsaciones_concretas(ar_b),
            },
            "predicciones_count": {
                "a": pred_a_total,
                "b": pred_b_total,
            },
            "predicciones_con_probabilidad": {
                "a": pred_a_prob,
                "b": pred_b_prob,
            },
            "coherencia_decision": {
                "a": check_coherencia_decision(dp_a),
                "b": check_coherencia_decision(dp_b),
            },
            "score": {
                "a": score_a,
                "b": score_b,
                "diff": abs(score_a - score_b) if score_a is not None and score_b is not None else None,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark comparator: metricas objetivas inter-modelo")
    parser.add_argument("dir_a", help="Primer directorio de caso (ej. casos/CRCT/2026-02-12_GPT5)")
    parser.add_argument("dir_b", help="Segundo directorio de caso (ej. casos/CRCT/2026-02-12_Codex)")
    parser.add_argument("-o", "--output", help="Guardar resultado en archivo JSON")
    args = parser.parse_args()

    dir_a = Path(args.dir_a)
    dir_b = Path(args.dir_b)

    if not dir_a.is_dir():
        print(f"ERROR: {dir_a} no es un directorio", file=sys.stderr)
        return 1
    if not dir_b.is_dir():
        print(f"ERROR: {dir_b} no es un directorio", file=sys.stderr)
        return 1

    # Guard: verify both directories are for the same ticker
    def _extract_ticker(case_dir: Path) -> Optional[str]:
        estado = load_json(case_dir / "_estado.json")
        if estado and isinstance(estado.get("ticker"), str):
            return estado["ticker"].upper()
        # Fallback: infer from parent directory (casos/{TICKER}/{DATE}_{MODEL}/)
        return case_dir.parent.name.upper() if case_dir.parent.name else None

    ticker_a = _extract_ticker(dir_a)
    ticker_b = _extract_ticker(dir_b)
    if ticker_a and ticker_b and ticker_a != ticker_b:
        print(f"ERROR: tickers distintos — dir_a={ticker_a}, dir_b={ticker_b}. "
              f"Benchmark solo compara el mismo ticker.", file=sys.stderr)
        return 1

    result = compare(dir_a, dir_b)
    output_str = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output_str + "\n", encoding="utf-8")
        print(f"Saved: {args.output}")
    else:
        print(output_str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
