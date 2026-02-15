#!/usr/bin/env python3
"""Audit substantive quality of ELSIAN INVEST cases.

Complements validate_repo_contracts.py (form/schema) by checking analysis
depth, claim substance, decision coherence, and detecting simulated or
fabricated pipeline outputs.

Checks applied (Q1-Q8):
  Q1  simulated_execution   – "Simulated execution" in agent logs
  Q2  empty_claims           – Empty claims[] in AgentReports
  Q3  empty_predictions      – Empty predicciones_calibracion[]
  Q4  artefact_depth         – TruthPack/DecisionPacket min content
  Q5  decision_coherence     – Sizing vs decision consistency
  Q6  source_utilization     – SourcesPack vs _raw_filings/
  Q7  meta_quality           – _meta blocks present with modelo/timestamp
  Q8  pipeline_duration      – Suspiciously fast completion (<10 min)
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def detect_role(filename: str) -> Optional[str]:
    # Pattern 1: AgentReport_v1_ROLE_...  (standard)
    m = re.search(r"AgentReport_v\d+_(\w+?)_", filename)
    if m:
        return m.group(1).upper()
    # Pattern 2: AgentReport_ROLE_TICKER_... (no version, e.g. DCBO)
    # Pattern 3: AgentReport_ROLE_v1_... (role before version)
    m = re.search(r"AgentReport_((?:RED_TEAM|BULL|CATALYST|FORENSIC|REDTEAM))(?:_v\d+)?_", filename)
    if m:
        return m.group(1).replace("RED_TEAM", "REDTEAM").upper()
    return None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    check_id: str
    severity: str  # FAIL, WARN, INFO
    message: str
    file: Optional[str] = None


@dataclass
class CaseResult:
    ticker: str
    date: str
    case_dir_name: str
    caso_id: str
    estado_pipeline: str
    quality_status: str  # PASS, WARN, FAIL, QUARANTINE
    issues: List[Issue] = field(default_factory=list)
    agent_summary: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Q1 – Simulated execution
# ---------------------------------------------------------------------------

def _get_limitaciones(data: Dict[str, Any]) -> List[Any]:
    log = data.get("log")
    if isinstance(log, dict):
        lims = log.get("limitaciones")
        return lims if isinstance(lims, list) else []
    return []


def check_simulated(agent_files: Dict[str, Dict[str, Any]]) -> List[Issue]:
    issues: List[Issue] = []
    for role, data in agent_files.items():
        lims = _get_limitaciones(data)
        for lim in lims:
            if isinstance(lim, str) and "simulated" in lim.lower():
                issues.append(Issue(
                    "Q1", "FAIL",
                    f"AgentReport {role}: '{lim}' in log.limitaciones",
                    data.get("_filename"),
                ))
    return issues


# ---------------------------------------------------------------------------
# Q2 – Empty claims
# ---------------------------------------------------------------------------

def check_claims(agent_files: Dict[str, Dict[str, Any]]) -> List[Issue]:
    issues: List[Issue] = []
    for role, data in agent_files.items():
        claims = data.get("claims")
        if not isinstance(claims, list):
            claims = []
        n = len(claims)
        fname = data.get("_filename")
        if n == 0:
            issues.append(Issue("Q2", "FAIL", f"AgentReport {role}: 0 claims", fname))
        elif n < 2:
            issues.append(Issue("Q2", "WARN", f"AgentReport {role}: {n} claim(s) (min recommended: 2)", fname))
    return issues


# ---------------------------------------------------------------------------
# Q3 – Empty predictions
# ---------------------------------------------------------------------------

def check_predictions(agent_files: Dict[str, Dict[str, Any]]) -> List[Issue]:
    issues: List[Issue] = []
    for role, data in agent_files.items():
        preds = data.get("predicciones_calibracion")
        if not isinstance(preds, list) or len(preds) == 0:
            issues.append(Issue(
                "Q3", "WARN",
                f"AgentReport {role}: 0 predicciones_calibracion",
                data.get("_filename"),
            ))
    return issues


# ---------------------------------------------------------------------------
# Q4 – Artefact depth
# ---------------------------------------------------------------------------

def check_artefact_depth(case_dir: Path, estado: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    ticker = estado.get("ticker", "")
    fecha = estado.get("fecha_caso", "")

    # --- TruthPack ---
    tp_files = sorted(case_dir.glob(f"TruthPack_v*_{ticker}_{fecha}_*.json"))
    if tp_files:
        tp = load_json(tp_files[0])
        fname = tp_files[0].name
        if tp:
            hist = tp.get("historico_anual")
            if not isinstance(hist, list) or len(hist) < 2:
                issues.append(Issue("Q4", "WARN", f"TruthPack: historico_anual has {len(hist) if isinstance(hist, list) else 0} entries (min: 2)", fname))
            mercado = tp.get("mercado") or {}
            precio = mercado.get("precio")
            if isinstance(precio, dict):
                precio = precio.get("valor")
            if not precio:
                issues.append(Issue("Q4", "FAIL", "TruthPack: mercado.precio missing or zero", fname))

    # --- DecisionPacket ---
    dp_files = sorted(case_dir.glob(f"DecisionPacket_v*_{ticker}_{fecha}_*.json"))
    if dp_files:
        dp = load_json(dp_files[0])
        fname = dp_files[0].name
        if dp:
            escenarios = dp.get("escenarios")
            if not isinstance(escenarios, list) or len(escenarios) < 2:
                issues.append(Issue("Q4", "FAIL", f"DecisionPacket: {len(escenarios) if isinstance(escenarios, list) else 0} escenarios (min: 2)", fname))
            elif len(escenarios) >= 2:
                prob_sum = sum(float(e.get("probabilidad_0_1") or 0) for e in escenarios)
                if abs(prob_sum - 1.0) > 0.05:
                    issues.append(Issue("Q4", "WARN", f"DecisionPacket: escenarios probabilities sum to {prob_sum:.2f} (expected ~1.0)", fname))

    return issues


# ---------------------------------------------------------------------------
# Q5 – Decision coherence
# ---------------------------------------------------------------------------

def check_decision_coherence(case_dir: Path, estado: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    ticker = estado.get("ticker", "")
    fecha = estado.get("fecha_caso", "")
    score = estado.get("score")
    decision = estado.get("decision")

    if isinstance(score, (int, float)):
        if score < 0 or score > 100:
            issues.append(Issue("Q5", "FAIL", f"score={score} out of range [0,100]"))

    dp_files = sorted(case_dir.glob(f"DecisionPacket_v*_{ticker}_{fecha}_*.json"))
    if not dp_files:
        return issues

    dp = load_json(dp_files[0])
    if not dp:
        return issues
    fname = dp_files[0].name

    prob = dp.get("decision_probabilistica") or {}
    sizing = prob.get("sizing_kelly") or {}
    kelly_raw = sizing.get("kelly_crudo_pct")
    sizing_final = sizing.get("sizing_final_pct")

    if isinstance(kelly_raw, (int, float)):
        kelly_frac = kelly_raw / 100.0 if kelly_raw > 1 else kelly_raw
        if kelly_frac < 0 or kelly_frac > 1:
            issues.append(Issue("Q5", "FAIL", f"Kelly crudo {kelly_raw} implies fraction {kelly_frac:.2f} out of [0,1]", fname))

    resumen = dp.get("resumen_ejecutivo") or {}
    dp_decision = resumen.get("decision") or prob.get("decision_categorica")

    if dp_decision in ("INVERTIR", "BUY", "STRONG_BUY"):
        if isinstance(sizing_final, (int, float)) and sizing_final == 0:
            issues.append(Issue("Q5", "FAIL", f"Decision={dp_decision} but sizing_final=0%", fname))

    if dp_decision in ("DESCARTAR", "PASS"):
        if isinstance(sizing_final, (int, float)) and sizing_final > 0:
            issues.append(Issue("Q5", "WARN", f"Decision={dp_decision} but sizing_final={sizing_final}%", fname))

    return issues


# ---------------------------------------------------------------------------
# Q6 – Source utilization
# ---------------------------------------------------------------------------

def check_source_utilization(case_dir: Path, estado: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    ticker = estado.get("ticker", "")
    fecha = estado.get("fecha_caso", "")

    sp_files = sorted(case_dir.glob(f"SourcesPack_v*_{ticker}_{fecha}_*.json"))
    if not sp_files:
        return issues

    sp = load_json(sp_files[0])
    if not sp:
        return issues
    fname = sp_files[0].name

    fuentes = sp.get("fuentes") or []
    local_refs = sum(1 for f in fuentes if isinstance(f, dict) and f.get("local_path"))

    raw_dir = case_dir / "_raw_filings"
    if not raw_dir.is_dir():
        raw_dir = case_dir.parent / "_raw_filings"
    raw_count = len(list(raw_dir.glob("*"))) if raw_dir.is_dir() else 0

    if local_refs > 5 and raw_count == 0:
        issues.append(Issue("Q6", "WARN", f"SourcesPack references {local_refs} local files but _raw_filings/ is empty", fname))
    elif local_refs > 10 and raw_count < local_refs * 0.3:
        issues.append(Issue("Q6", "WARN", f"SourcesPack has {local_refs} local refs but only {raw_count} files in _raw_filings/", fname))

    return issues


# ---------------------------------------------------------------------------
# Q7 – Meta quality
# ---------------------------------------------------------------------------

_ARTEFACT_PATTERNS = [
    "AgentReport_v*_*.json",
    "DecisionPacket_v*_*.json",
    "TruthPack_v*_*.json",
    "ImpliedExpectations_v*_*.json",
    "SourcesPack_v*_*.json",
]


_ANALYSIS_PREFIXES = ("AgentReport_", "DecisionPacket_")


def check_meta_quality(case_dir: Path) -> List[Issue]:
    issues: List[Issue] = []
    for pattern in _ARTEFACT_PATTERNS:
        for path in sorted(case_dir.glob(pattern)):
            data = load_json(path)
            if not data:
                continue
            # Primary artifacts (AgentReport, DecisionPacket) get WARN; others get INFO
            is_primary = any(path.name.startswith(p) for p in _ANALYSIS_PREFIXES)
            severity = "WARN" if is_primary else "INFO"
            meta = data.get("_meta")
            if not isinstance(meta, dict):
                issues.append(Issue("Q7", severity, "Missing _meta block", path.name))
                continue
            if not meta.get("modelo") and not meta.get("compilado_por"):
                issues.append(Issue("Q7", severity, "_meta missing 'modelo'", path.name))
            ts = meta.get("timestamp") or meta.get("timestamp_compilacion") or meta.get("ultima_actualizacion")
            if not ts:
                issues.append(Issue("Q7", severity, "_meta missing timestamp", path.name))
    return issues


# ---------------------------------------------------------------------------
# Q8 – Pipeline duration
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: Any) -> Optional[datetime]:
    if not isinstance(ts_str, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def check_pipeline_duration(case_dir: Path) -> List[Issue]:
    issues: List[Issue] = []
    timestamps: List[datetime] = []
    for pattern in _ARTEFACT_PATTERNS:
        for path in sorted(case_dir.glob(pattern)):
            data = load_json(path)
            if not data:
                continue
            meta = data.get("_meta") or {}
            ts = _parse_ts(meta.get("timestamp") or meta.get("timestamp_compilacion"))
            if ts:
                timestamps.append(ts)

    if len(timestamps) >= 3:
        earliest = min(timestamps)
        latest = max(timestamps)
        duration_min = (latest - earliest).total_seconds() / 60.0
        if duration_min < 10.0:
            issues.append(Issue(
                "Q8", "INFO",
                f"Pipeline completed in {duration_min:.1f} min (all artefact timestamps span < 10 min)",
            ))
        # Also check if all timestamps are identical (strong fabrication signal)
        if duration_min == 0.0:
            issues.append(Issue(
                "Q8", "WARN",
                "All artefact timestamps are identical (0s span) — fabrication signal",
            ))

    return issues


# ---------------------------------------------------------------------------
# Case-level audit
# ---------------------------------------------------------------------------

def find_agent_files(case_dir: Path, ticker: str, fecha: str) -> Dict[str, Dict[str, Any]]:
    agents: Dict[str, Dict[str, Any]] = {}
    for path in sorted(case_dir.glob(f"AgentReport_v*_{ticker}_{fecha}_*.json")):
        role = detect_role(path.name)
        if not role:
            continue
        data = load_json(path)
        if data:
            data["_filename"] = path.name
            agents[role] = data
    # Fallback: broader glob for non-standard naming (includes versionless)
    if not agents:
        for path in sorted(case_dir.glob("AgentReport_*.json")):
            role = detect_role(path.name)
            if not role:
                continue
            data = load_json(path)
            if data:
                data["_filename"] = path.name
                agents[role] = data
    return agents


def audit_case(case_dir: Path) -> Optional[CaseResult]:
    estado = load_json(case_dir / "_estado.json")
    if not estado or estado.get("version_esquema") != "caso_estado_v1":
        return None

    ticker = estado.get("ticker", case_dir.parent.name)
    fecha = estado.get("fecha_caso", case_dir.name)
    caso_id = estado.get("caso_id", "")
    estado_pipeline = estado.get("estado_pipeline", "UNKNOWN")

    agent_files = find_agent_files(case_dir, ticker, fecha)

    all_issues: List[Issue] = []
    all_issues.extend(check_simulated(agent_files))
    all_issues.extend(check_claims(agent_files))
    all_issues.extend(check_predictions(agent_files))
    all_issues.extend(check_artefact_depth(case_dir, estado))
    all_issues.extend(check_decision_coherence(case_dir, estado))
    all_issues.extend(check_source_utilization(case_dir, estado))
    all_issues.extend(check_meta_quality(case_dir))
    all_issues.extend(check_pipeline_duration(case_dir))

    # Build agent summary
    agent_summary: Dict[str, Dict[str, Any]] = {}
    for role, data in agent_files.items():
        claims = data.get("claims") or []
        preds = data.get("predicciones_calibracion") or []
        lims = _get_limitaciones(data)
        simulated = any("simulated" in str(l).lower() for l in lims)
        agent_summary[role] = {
            "claims": len(claims),
            "predictions": len(preds),
            "simulated": simulated,
        }

    # Determine quality status
    if estado_pipeline == "QUARANTINE":
        quality_status = "QUARANTINE"
    elif any(i.severity == "FAIL" for i in all_issues):
        quality_status = "FAIL"
    elif any(i.severity == "WARN" for i in all_issues):
        quality_status = "WARN"
    else:
        quality_status = "PASS"

    return CaseResult(
        ticker=ticker,
        date=fecha,
        case_dir_name=case_dir.name,
        caso_id=caso_id,
        estado_pipeline=estado_pipeline,
        quality_status=quality_status,
        issues=all_issues,
        agent_summary=agent_summary,
    )


# ---------------------------------------------------------------------------
# Case scanning
# ---------------------------------------------------------------------------

def scan_cases(root: Path, ticker_filter: Optional[str], date_filter: Optional[str],
               scope: str) -> List[Path]:
    casos_dir = root / "casos"
    if not casos_dir.is_dir():
        return []

    candidates: List[Path] = []
    latest_by_ticker: Dict[str, Path] = {}

    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir() or ticker_dir.name.startswith("_"):
            continue
        if ticker_filter and ticker_dir.name.upper() != ticker_filter.upper():
            continue

        for date_dir in sorted(ticker_dir.iterdir()):
            if not date_dir.is_dir() or len(date_dir.name) < 10:
                continue
            try:
                date.fromisoformat(date_dir.name[:10])
            except ValueError:
                continue
            if date_filter and date_dir.name[:10] != date_filter:
                continue

            estado_path = date_dir / "_estado.json"
            if not estado_path.exists():
                continue

            if scope == "latest":
                latest_by_ticker[ticker_dir.name] = date_dir
            elif scope == "completo":
                estado = load_json(estado_path)
                if estado and estado.get("estado_pipeline") in ("COMPLETO", "QUARANTINE"):
                    candidates.append(date_dir)
            else:  # all
                candidates.append(date_dir)

    if scope == "latest":
        candidates = list(latest_by_ticker.values())

    return sorted(candidates, key=lambda p: (p.parent.name, p.name))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def build_report(results: List[CaseResult], root: str, scope: str) -> Dict[str, Any]:
    by_check: Dict[str, int] = {}
    for r in results:
        for issue in r.issues:
            key = f"{issue.check_id}_{issue.severity}"
            by_check[key] = by_check.get(key, 0) + 1

    status_counts = {"pass": 0, "warn": 0, "fail": 0, "quarantine": 0}
    for r in results:
        status_counts[r.quality_status.lower()] = status_counts.get(r.quality_status.lower(), 0) + 1

    cases_json = []
    for r in results:
        cases_json.append({
            "ticker": r.ticker,
            "date": r.date,
            "caso_id": r.caso_id,
            "estado_pipeline": r.estado_pipeline,
            "quality_status": r.quality_status,
            "issues": [
                {"check_id": i.check_id, "severity": i.severity, "message": i.message, "file": i.file}
                for i in r.issues
            ],
            "agent_summary": r.agent_summary,
        })

    return {
        "meta": {
            "version": "1.0",
            "generated_at_utc": utc_now_iso(),
            "root": root,
            "scope": scope,
            "total_scanned": len(results),
            "checks_applied": ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"],
        },
        "summary": {**status_counts, "by_check": by_check},
        "cases": cases_json,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    meta = report["meta"]
    s = report["summary"]
    lines = [
        f"# Case Quality Audit",
        f"",
        f"- Generated: {meta['generated_at_utc']}",
        f"- Scope: {meta['scope']}",
        f"- Cases scanned: {meta['total_scanned']}",
        f"- PASS: {s['pass']}  |  WARN: {s['warn']}  |  FAIL: {s['fail']}  |  QUARANTINE: {s['quarantine']}",
        f"",
    ]

    fail_cases = [c for c in report["cases"] if c["quality_status"] in ("FAIL", "QUARANTINE")]
    warn_cases = [c for c in report["cases"] if c["quality_status"] == "WARN"]

    if fail_cases:
        lines.append("## FAIL / QUARANTINE cases")
        lines.append("")
        for c in fail_cases:
            lines.append(f"### {c['ticker']} ({c['date']}) — {c['quality_status']}")
            for issue in c["issues"]:
                file_ref = f" [{issue['file']}]" if issue.get("file") else ""
                lines.append(f"- **{issue['severity']}** {issue['check_id']}: {issue['message']}{file_ref}")
            if c.get("agent_summary"):
                agents_str = ", ".join(
                    f"{role}: {info['claims']}c/{info['predictions']}p{'*' if info.get('simulated') else ''}"
                    for role, info in sorted(c["agent_summary"].items())
                )
                lines.append(f"- Agents: {agents_str}")
            lines.append("")

    if warn_cases:
        lines.append("## WARN cases")
        lines.append("")
        for c in warn_cases:
            issues_str = ", ".join(f"{i['check_id']}:{i['severity']}" for i in c["issues"])
            lines.append(f"- **{c['ticker']}** ({c['date']}): {issues_str}")
        lines.append("")

    pass_cases = [c for c in report["cases"] if c["quality_status"] == "PASS"]
    if pass_cases:
        lines.append(f"## PASS cases ({len(pass_cases)})")
        lines.append("")
        for c in pass_cases:
            lines.append(f"- {c['ticker']} ({c['date']})")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quarantine action
# ---------------------------------------------------------------------------

def quarantine_cases(results: List[CaseResult], root: Path) -> List[str]:
    quarantined: List[str] = []
    today_key = date.today().isoformat().replace("-", "_")

    for r in results:
        if r.quality_status != "FAIL":
            continue
        estado_path = root / "casos" / r.ticker / r.case_dir_name / "_estado.json"
        estado = load_json(estado_path)
        if not estado:
            continue

        fail_issues = [i for i in r.issues if i.severity == "FAIL"]
        motivo_parts = [f"{i.check_id}: {i.message}" for i in fail_issues[:5]]

        estado["estado_pipeline"] = "QUARANTINE"
        estado["next_step"] = "RE-HACER"
        estado[f"auditoria_{today_key}"] = {
            "veredicto": "QUALITY_FAIL",
            "motivo": " | ".join(motivo_parts),
            "accion": "Re-hacer pipeline completo con sub-agentes reales.",
        }
        if "_meta" not in estado:
            estado["_meta"] = {}
        estado["_meta"]["ultima_actualizacion"] = utc_now_iso()
        estado["_meta"]["actualizado_por"] = "script:case_quality_audit"

        estado_path.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        quarantined.append(f"{r.ticker}/{r.case_dir_name}")

    return quarantined


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit substantive quality of ELSIAN INVEST cases",
    )
    parser.add_argument("--root", default=".", help="Repository root (default: .)")
    parser.add_argument("--ticker", default=None, help="Filter by ticker (e.g. CRCT)")
    parser.add_argument("--date", default=None, help="Filter by date (YYYY-MM-DD)")
    parser.add_argument(
        "--scope", choices=["completo", "all", "latest"], default="completo",
        help="completo: COMPLETO+QUARANTINE cases. all: every case. latest: latest per ticker",
    )
    parser.add_argument(
        "--quarantine", action="store_true",
        help="Update _estado.json of FAIL cases to QUARANTINE",
    )
    parser.add_argument(
        "--output-json", default=None,
        help="Output JSON path (default: tmp/case_quality_audit_YYYY-MM-DD.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()

    case_dirs = scan_cases(root, args.ticker, args.date, args.scope)
    results: List[CaseResult] = []
    for case_dir in case_dirs:
        result = audit_case(case_dir)
        if result:
            results.append(result)

    report = build_report(results, str(root), args.scope)

    # Quarantine if requested
    quarantined: List[str] = []
    if args.quarantine:
        quarantined = quarantine_cases(results, root)
        report["quarantined_this_run"] = quarantined

    # Output JSON
    out_path = args.output_json
    if not out_path:
        tmp_dir = root / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(tmp_dir / f"case_quality_audit_{date.today().isoformat()}.json")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Print summary
    s = report["summary"]
    print(f"Cases scanned: {report['meta']['total_scanned']}")
    print(f"  PASS: {s['pass']}  WARN: {s['warn']}  FAIL: {s['fail']}  QUARANTINE: {s['quarantine']}")
    if quarantined:
        print(f"  Quarantined this run: {', '.join(quarantined)}")
    if s.get("by_check"):
        print(f"  Issues by check: {json.dumps(s['by_check'])}")
    print(f"Report: {out_path}")

    return 1 if s["fail"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
