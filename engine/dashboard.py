"""Equivalente a estado_resumen.py — genera dashboard sin LLM (0 tokens).

Implements §3.3 of PLAN COMPLETO.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass, field
from collections import Counter
from statistics import median

from .quality_voting import get_quality_voting_config


@dataclass
class DashboardData:
    """Datos procesados del dashboard."""
    total_cases: int = 0
    by_status: dict[str, list[dict]] = field(default_factory=dict)
    actionable: list[dict] = field(default_factory=list)
    monitors_overdue: list[dict] = field(default_factory=list)
    generated_at: str = ""


# Operations available from the interactive menu
OPERATIONS = {
    "1": {"label": "Pipeline completo (caso nuevo)", "command": "pipeline"},
    "2": {"label": "Continuar caso incompleto", "command": "continue"},
    "3": {"label": "Ejecutar step individual", "command": "step"},
    "4": {"label": "Rehacer step", "command": "rehacer"},
    "5": {"label": "Validar artefactos", "command": "validate"},
    "6": {"label": "Monitor", "command": "monitor"},
    "7": {"label": "Scanner", "command": "scanner"},
    "8": {"label": "Scout", "command": "scout"},
    "9": {"label": "Outcome", "command": "outcome"},
    "10": {"label": "Evaluar", "command": "evaluar"},
    "11": {"label": "Benchmark", "command": "benchmark"},
    "0": {"label": "Salir", "command": "exit"},
}


def build_dashboard(workspace: Path) -> DashboardData:
    """Construye DashboardData escaneando todos los casos."""
    casos_dir = workspace / "casos"
    data = DashboardData(generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"))

    if not casos_dir.exists():
        return data

    cases = []
    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            state_file = case_dir / "_estado.json"
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        state = json.load(f)
                    state["_case_dir"] = str(case_dir)
                    cases.append(state)
                except (json.JSONDecodeError, OSError):
                    cases.append({"caso_id": case_dir.name, "estado_pipeline": "ERROR_READ"})

    data.total_cases = len(cases)

    # Group by status
    for c in cases:
        status = c.get("estado_pipeline", "UNKNOWN")
        data.by_status.setdefault(status, []).append(c)

    # Monitors overdue
    today = date.today().isoformat()
    data.monitors_overdue = [
        c for c in cases
        if c.get("proxima_revision") and c["proxima_revision"] <= today
        and c.get("estado_pipeline") == "COMPLETO"
    ]

    # Actionable items
    data.actionable = get_actionable_items(workspace)

    return data


def render_dashboard(data: DashboardData) -> str:
    """Renderiza DashboardData como texto para terminal."""
    lines = []
    lines.append(f"═══ DASHBOARD 3_0-ELSIAN-INVEST ═══  ({data.generated_at})")
    lines.append(f"Total cases: {data.total_cases}")
    lines.append("")

    for status in ["COMPLETO", "EN_PROGRESO", "INCOMPLETO", "QUARANTINE",
                    "BLOCKED", "SUPERSEDED", "EXCLUIDO", "LEGACY"]:
        group = data.by_status.get(status, [])
        if group:
            tickers = [c.get("ticker", "?") for c in group]
            lines.append(f"  {status}: {len(group)} — {', '.join(tickers[:10])}")

    if data.monitors_overdue:
        lines.append("")
        lines.append(f"⚠ Monitors overdue: {len(data.monitors_overdue)}")
        for c in data.monitors_overdue[:5]:
            lines.append(f"    {c.get('ticker', '?')} — due {c.get('proxima_revision')}")

    incomplete = data.by_status.get("INCOMPLETO", [])
    if incomplete:
        lines.append("")
        lines.append(f"Incomplete pipelines ({len(incomplete)}):")
        for c in incomplete[:10]:
            pipeline = c.get("pipeline", {})
            pending = [s for s, v in pipeline.items() if v.get("estado") != "DONE"]
            next_s = pending[0] if pending else "?"
            lines.append(f"    {c.get('ticker', '?')} → next: {next_s}")

    if data.actionable:
        lines.append("")
        lines.append("Actionable items:")
        for item in data.actionable[:8]:
            t = item.get("type", "?")
            tk = item.get("ticker", "?")
            if t == "QUARANTINE":
                lines.append(f"  🔴 {tk}: {item.get('reason', '')}")
            elif t == "CONTINUE":
                lines.append(f"  🟡 {tk}: continue → {item.get('next_step', '?')}")
            elif t == "MONITOR_DUE":
                lines.append(f"  🔵 {tk}: monitor due {item.get('due_date', '?')}")

    return "\n".join(lines)


def generate_dashboard(
    workspace: Path,
    include_quality: bool = False,
    quality_config: dict | None = None,
) -> str:
    """Shortcut: build + render (+ optional quality voting summary)."""
    data = build_dashboard(workspace)
    base_output = render_dashboard(data)
    hygiene_output = _render_case_hygiene(workspace)
    if hygiene_output:
        base_output = f"{base_output}\n\n{hygiene_output}"
    if not include_quality:
        return base_output

    quality_output = _render_quality_dashboard(workspace, quality_config or {})
    if not quality_output:
        return base_output
    return f"{base_output}\n\n{quality_output}"


def _render_quality_dashboard(workspace: Path, quality_config: dict) -> str:
    """Render deterministic quality-voting metrics from global JSONL log."""
    qv_cfg = get_quality_voting_config({"quality_voting": quality_config})

    lines = []
    lines.append("═══ QUALITY VOTING (deterministic v1) ═══")

    if not qv_cfg.get("enabled", False):
        lines.append("Quality voting desactivado en configuración.")
        return "\n".join(lines)

    global_log_path = Path(qv_cfg.get("global_log_path", "_evaluacion/votes_log_v1.jsonl"))
    if not global_log_path.is_absolute():
        global_log_path = workspace / global_log_path

    if not global_log_path.exists():
        lines.append(f"Sin datos de voting todavía ({global_log_path}).")
        return "\n".join(lines)

    events = []
    parse_errors = 0
    with open(global_log_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue

            if payload.get("version_esquema") != "VoteEvent_v1":
                continue
            if not isinstance(payload.get("score_raw_0_100"), (int, float)):
                continue
            events.append(payload)

    if not events:
        lines.append(f"Sin eventos válidos en {global_log_path}.")
        if parse_errors:
            lines.append(f"  ⚠ parse_errors: {parse_errors}")
        return "\n".join(lines)

    unique_cases = {e.get("caso_id") for e in events if e.get("caso_id")}
    unique_steps = {e.get("step_name") for e in events if e.get("step_name")}
    lines.append(
        f"Cobertura: {len(events)} votos | {len(unique_cases)} casos | {len(unique_steps)} steps"
    )
    if parse_errors:
        lines.append(f"  ⚠ Líneas inválidas ignoradas: {parse_errors}")

    # Mean/median per step
    by_step = {}
    for event in events:
        step = event.get("step_name", "UNKNOWN")
        by_step.setdefault(step, []).append(float(event["score_raw_0_100"]))

    lines.append("")
    lines.append("Media / mediana por step:")
    for step_name in sorted(by_step):
        scores = by_step[step_name]
        avg = sum(scores) / len(scores)
        med = median(scores)
        lines.append(f"  {step_name}: mean={avg:.2f} | median={med:.2f} | n={len(scores)}")

    # Most failed rules
    failed_rules = Counter()
    for event in events:
        for rule_name in event.get("rules_failed", []):
            failed_rules[rule_name] += 1

    lines.append("")
    lines.append("Reglas más falladas:")
    if failed_rules:
        for name, count in failed_rules.most_common(5):
            lines.append(f"  {name}: {count}")
    else:
        lines.append("  Ninguna (todos los eventos sin reglas falladas).")

    min_runs = int(qv_cfg.get("min_runs_for_stats", 20))
    if len(unique_cases) < min_runs:
        lines.append("")
        lines.append(
            f"⚠ Muestra insuficiente para tendencias ({len(unique_cases)}/{min_runs} runs)."
        )

    lines.extend(_render_model_stats_sections(workspace, qv_cfg))
    return "\n".join(lines)


def _render_case_hygiene(workspace: Path) -> str:
    """Render lightweight hygiene signals for case directories."""
    casos_dir = workspace / "casos"
    if not casos_dir.exists():
        return ""

    totals = {
        "cases": 0,
        "deprecated_alias": 0,
        "tp_partials": 0,
        "orphans": 0,
    }
    noisy_cases: list[tuple[int, str, dict[str, int]]] = []

    artifact_prefixes = (
        "SourcesPack_v1_",
        "TruthPack_v1_",
        "ImpliedExpectations_v1_",
        "AgentReport_v1_",
        "DecisionPacket_v2_",
        "CatalystDetection_v1_",
        "ForensicDetection_v1_",
        "_catalyst_detection_",
        "_forensic_detection_",
    )

    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir() or case_dir.name.startswith("_"):
                continue
            state_path = case_dir / "_estado.json"
            if not state_path.exists():
                continue
            totals["cases"] += 1

            try:
                state = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            deprecated_count = len(list((case_dir / "_deprecated").glob("*.json*")))
            partial_count = len(list(case_dir.glob("_tmp_tp_filing_*.json")))

            referenced = set()
            pipeline = state.get("pipeline", {})
            if isinstance(pipeline, dict):
                for step_data in pipeline.values():
                    if isinstance(step_data, dict):
                        art = step_data.get("artefacto")
                        if isinstance(art, str) and art:
                            referenced.add(art)

            # Sub-step intermediate artifacts consumed within the pipeline
            # (e.g. CatalystDetection → CatalystScoring) are not tracked in
            # _estado.json but are legitimate pipeline outputs.
            sub_step_prefixes = ("CatalystDetection_v1_", "ForensicDetection_v1_")

            orphan_count = 0
            for candidate in case_dir.glob("*.json"):
                name = candidate.name
                if name.startswith("_"):
                    continue
                if name in referenced:
                    continue
                if name.startswith(sub_step_prefixes):
                    continue
                if name.startswith(artifact_prefixes):
                    orphan_count += 1

            totals["deprecated_alias"] += deprecated_count
            totals["tp_partials"] += partial_count
            totals["orphans"] += orphan_count

            issue_weight = deprecated_count + partial_count + orphan_count
            if issue_weight:
                noisy_cases.append(
                    (
                        issue_weight,
                        f"{ticker_dir.name}/{case_dir.name}",
                        {
                            "deprecated": deprecated_count,
                            "tp_partials": partial_count,
                            "orphans": orphan_count,
                        },
                    )
                )

    lines = []
    lines.append("Case Dir Hygiene:")
    lines.append(
        f"  cases={totals['cases']} | deprecated_alias={totals['deprecated_alias']} | "
        f"tp_partials={totals['tp_partials']} | orphan_artifacts={totals['orphans']}"
    )
    if noisy_cases:
        lines.append("  Top noisy cases:")
        for _, case_key, counts in sorted(noisy_cases, reverse=True)[:5]:
            lines.append(
                f"    {case_key}: deprecated={counts['deprecated']}, "
                f"tp_partials={counts['tp_partials']}, orphans={counts['orphans']}"
            )
    return "\n".join(lines)


def _render_model_stats_sections(workspace: Path, qv_cfg: dict) -> list[str]:
    """Render model-level stats from precomputed rollup if available."""
    lines: list[str] = []
    model_stats_cfg = qv_cfg.get("model_stats", {})
    if not isinstance(model_stats_cfg, dict) or not model_stats_cfg.get("enabled", False):
        return lines

    rollup_path = Path(model_stats_cfg.get("global_rollup_path", "_evaluacion/model_quality_rollup_v1.json"))
    if not rollup_path.is_absolute():
        rollup_path = workspace / rollup_path

    lines.append("")
    lines.append("Per-model by canonical step:")
    if not rollup_path.exists():
        lines.append(f"  Sin rollup todavía ({rollup_path}).")
        return lines

    try:
        rollup = json.loads(rollup_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        lines.append(f"  ⚠ No se pudo leer rollup: {exc}")
        return lines

    min_samples = int(rollup.get("min_samples_per_step_model", model_stats_cfg.get("min_samples_per_step_model", 20)))
    stats = rollup.get("per_model_step_stats", [])
    if not isinstance(stats, list) or not stats:
        lines.append("  Sin datos per-model.")
    else:
        for item in stats:
            if not isinstance(item, dict):
                continue
            step = item.get("canonical_step_name", "?")
            backend = item.get("backend", "?")
            mean = item.get("mean")
            med = item.get("median")
            n = item.get("n_votes", 0)
            mean_s = f"{float(mean):.2f}" if isinstance(mean, (int, float)) else "?"
            med_s = f"{float(med):.2f}" if isinstance(med, (int, float)) else "?"
            suff = "ok" if int(n) >= min_samples else "sample_low"
            lines.append(f"  {step} / {backend}: mean={mean_s} | p50={med_s} | n={n} | {suff}")

    lines.append("")
    lines.append("Delta vs fusion:")
    comps = rollup.get("fusion_comparison", [])
    if not isinstance(comps, list) or not comps:
        lines.append("  Sin comparaciones per-model vs fusion.")
    else:
        for item in comps:
            if not isinstance(item, dict):
                continue
            step = item.get("canonical_step_name", "?")
            backend = item.get("backend", "?")
            delta = item.get("delta_vs_fusion_mean")
            n_pairs = item.get("n_pairs", 0)
            wins = item.get("wins_vs_fusion_count", 0)
            losses = item.get("losses_vs_fusion_count", 0)
            ties = item.get("ties_vs_fusion_count", 0)
            delta_s = f"{float(delta):+.2f}" if isinstance(delta, (int, float)) else "?"
            lines.append(
                f"  {step} / {backend}: Δmean={delta_s} | pairs={n_pairs} | W/L/T={wins}/{losses}/{ties}"
            )

    return lines


def get_actionable_items(workspace: Path) -> list[dict]:
    """Retorna lista priorizada de acciones pendientes."""
    casos_dir = workspace / "casos"
    if not casos_dir.exists():
        return []

    items = []
    today = date.today().isoformat()

    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            state_file = case_dir / "_estado.json"
            if not state_file.exists():
                continue
            try:
                with open(state_file) as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            ticker = state.get("ticker", "?")
            status = state.get("estado_pipeline", "UNKNOWN")

            if status == "QUARANTINE":
                items.append({
                    "type": "QUARANTINE",
                    "ticker": ticker,
                    "priority": 1,
                    "reason": state.get("notas", "Quality audit failed"),
                })
            elif status == "INCOMPLETO":
                pipeline = state.get("pipeline", {})
                pending = [s for s, v in pipeline.items() if v.get("estado") != "DONE"]
                if pending:
                    items.append({
                        "type": "CONTINUE",
                        "ticker": ticker,
                        "priority": 2,
                        "next_step": pending[0],
                    })
            elif status == "COMPLETO" and state.get("proxima_revision"):
                if state["proxima_revision"] <= today:
                    items.append({
                        "type": "MONITOR_DUE",
                        "ticker": ticker,
                        "priority": 3,
                        "due_date": state["proxima_revision"],
                    })

    items.sort(key=lambda x: x.get("priority", 99))
    return items


def _extract_decision_info(state: dict) -> dict:
    """Extract decision fields from _estado.json, handling both formats.

    Falls back to reading the DecisionPacket directly if _estado.json
    has null decision fields (e.g., DecisionPacket_v2 not extracted).
    """
    info = {
        "ticker": state.get("ticker", "?"),
        "fecha": state.get("fecha_caso", "?"),
        "modelo": (
            state.get("modelo_principal")
            or state.get("pipeline", {}).get("ARBITRO", {}).get("model_profile")
            or state.get("pipeline", {}).get("ARBITRO", {}).get("model")
            or "?"
        ),
        "estado_pipeline": state.get("estado_pipeline", "?"),
        "proxima_revision": state.get("proxima_revision"),
        "monitoring_count": len(state.get("monitoring", [])),
        "case_dir": state.get("_case_dir"),
        "next_step": state.get("next_step"),
        "estado_caso": state.get("estado_caso"),
        "monitor_input": state.get("monitor_input"),
        "meta_review": state.get("meta_review"),
    }

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

    # New format: decision_final block
    df = state.get("decision_final")
    if isinstance(df, dict):
        info["decision"] = df.get("decision_categorica", "?")
        info["score"] = df.get("score_global")
        info["confianza"] = df.get("confianza_0_1")
        info["sizing"] = df.get("sizing_pct")
        info["quality_audit"] = df.get("quality_audit_status")
    else:
        # Old format: flat fields
        info["decision"] = state.get("decision")
        info["score"] = state.get("score")
        info["confianza"] = state.get("confianza")
        info["sizing"] = None
        info["quality_audit"] = None

    # Normalize numeric-like strings from legacy state format.
    info["score"] = _to_float(info.get("score"))
    info["confianza"] = _to_float(info.get("confianza"))
    info["sizing"] = _to_float(info.get("sizing"))

    # Fallback: complete missing fields from DecisionPacket.
    needs_dp = (
        not info.get("decision")
        or info.get("score") is None
        or info.get("confianza") is None
        or info.get("sizing") is None
        or not info.get("modelo")
        or info.get("modelo") == "?"
        or not info.get("proxima_revision")
        or not info.get("next_step")
    )
    if needs_dp:
        dp = _load_decision_packet(info.get("case_dir"))
        if dp:
            resumen = dp.get("resumen_ejecutivo", {})
            if not resumen and isinstance(dp.get("decision_packet"), dict):
                resumen = dp["decision_packet"].get("resumen_ejecutivo", {})
            if isinstance(resumen, dict):
                if not info.get("decision"):
                    info["decision"] = resumen.get("decision")
                if info["score"] is None:
                    info["score"] = _to_float(resumen.get("score_global", resumen.get("score")))
                if info["confianza"] is None:
                    info["confianza"] = _to_float(resumen.get("confianza_global_0_1", resumen.get("confianza")))
                if info["sizing"] is None:
                    info["sizing"] = _to_float(resumen.get("tamaño_recomendado_pct_cartera"))

            if info["score"] is None:
                scoring = dp.get("scoring_preliminar", {})
                if not scoring and isinstance(dp.get("decision_packet"), dict):
                    scoring = dp["decision_packet"].get("scoring_preliminar", {})
                if isinstance(scoring, dict):
                    info["score"] = _to_float(scoring.get("total_0_100", scoring.get("total")))

            if (not info.get("modelo")) or info.get("modelo") == "?":
                meta = dp.get("_meta", {})
                modelos = (meta.get("fusion") or {}).get("modelos_usados")
                if isinstance(modelos, list) and modelos:
                    info["modelo"] = "+".join(str(m) for m in modelos if m) or "?"

            # Fallback for monitor fields from DP
            salida = dp.get("salida_para_siguiente_agente", {})
            if not isinstance(salida, dict):
                salida = {}
            control = dp.get("control", {})
            if not isinstance(control, dict):
                control = {}

            if not info.get("proxima_revision") and salida.get("proxima_revision_sugerida"):
                info["proxima_revision"] = salida["proxima_revision_sugerida"]
            if not info.get("next_step"):
                info["next_step"] = control.get("next_step") or salida.get("next_step")
            if not info.get("estado_caso") and salida.get("estado_caso"):
                info["estado_caso"] = salida["estado_caso"]
            if not info.get("monitor_input") and salida.get("monitor_input_recomendado"):
                info["monitor_input"] = salida["monitor_input_recomendado"]

    return info


def _format_mr_tag(mr: dict | None) -> str:
    """Format the [MR:X] tag for meta-review display.

    Mapping (veredicto_meta.estado → tag):
      CONFIRMA      → [MR:CONFIRMA]
      CUESTIONA     → [MR:CUESTIONA]
      RECHAZA       → [MR:RECHAZA]
      NO_EVALUABLE  → [MR:NO_EVAL]
      PROMPT_GENERADO → [MR:PEND]
      (no review)   → ""
    """
    if not isinstance(mr, dict):
        return ""
    estado = mr.get("estado", "")
    if estado == "DONE":
        veredicto = mr.get("veredicto", "?")
        tag_map = {
            "CONFIRMA": "MR:CONFIRMA",
            "CUESTIONA": "MR:CUESTIONA",
            "RECHAZA": "MR:RECHAZA",
            "NO_EVALUABLE": "MR:NO_EVAL",
        }
        return f"[{tag_map.get(veredicto, f'MR:{veredicto}')}]"
    if estado == "PROMPT_GENERADO":
        return "[MR:PEND]"
    if estado == "PARCIAL":
        return "[MR:PARCIAL]"
    return ""


def _load_decision_packet(case_dir_str: str) -> dict | None:
    """Load DecisionPacket from a case directory (deterministic priority)."""
    if not case_dir_str:
        return None
    case_dir = Path(case_dir_str)
    if not case_dir.exists():
        return None

    ticker = case_dir.parent.name if case_dir.parent else ""
    candidates: list[Path] = []
    if ticker:
        candidates.extend(sorted(case_dir.glob(f"DecisionPacket_v2_{ticker}_*_Engine.json"), reverse=True))

    v2_default = case_dir / "DecisionPacket_v2.json"
    if v2_default.exists():
        candidates.append(v2_default)

    fallback = sorted(case_dir.glob("DecisionPacket*.json"), reverse=True)
    for f in fallback:
        if f not in candidates:
            candidates.append(f)

    for f in candidates:
        try:
            with open(f) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
    return None


def generate_decisions(workspace: Path, verbosity: int = 0, filter_ticker: str | None = None) -> str:
    """Generate decisions summary across all cases.

    Verbosity levels:
      0 (default): Compact table — ticker, date, decision, score, confidence, monitor
      1 (-v):      + sizing, model, agent confidences, quality audit
      2 (-vv):     + resumen ejecutivo, riesgos, lo_mas_importante from DecisionPacket
    """
    casos_dir = workspace / "casos"
    if not casos_dir.exists():
        return "No cases directory found."

    # Collect all cases with decisions
    cases = []
    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        if filter_ticker and ticker_dir.name.upper() != filter_ticker.upper():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir() or case_dir.name.startswith("_"):
                continue
            state_file = case_dir / "_estado.json"
            if not state_file.exists():
                continue
            try:
                with open(state_file) as f:
                    state = json.load(f)
                state["_case_dir"] = str(case_dir)
                info = _extract_decision_info(state)
                if info["decision"] and info["decision"] != "?":
                    cases.append(info)
            except (json.JSONDecodeError, OSError):
                pass

    if not cases:
        msg = f"No decisions found"
        if filter_ticker:
            msg += f" for {filter_ticker}"
        return msg + "."

    today = date.today().isoformat()
    lines = []
    lines.append(f"═══ DECISIONES ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ═══")
    lines.append(f"Total: {len(cases)} casos con decisión")
    lines.append("")

    # Sort: INVERTIR first, then WATCHLIST, then rest; within each group by score desc
    decision_order = {"INVERTIR": 0, "WATCHLIST": 1, "NO_INVERTIR": 2, "DESCARTAR": 3}
    cases.sort(key=lambda c: (
        decision_order.get(str(c.get("decision", "")).upper(), 9),
        -(c.get("score") or 0),
    ))

    # ── Level 0: compact table ──
    if verbosity == 0:
        lines.append(f"{'TICKER':<7} {'FECHA':<12} {'DECISION':<14} {'SCORE':>5} {'CONF':>5} {'MONITOR'}")
        lines.append("─" * 65)
        for c in cases:
            score_str = f"{c['score']:.1f}" if isinstance(c.get("score"), (int, float)) else "—"
            conf_str = f"{c['confianza']:.2f}" if isinstance(c.get("confianza"), (int, float)) else "—"
            # Monitor status
            mon = ""
            if c.get("proxima_revision"):
                if c["proxima_revision"] <= today:
                    mon = f"VENCIDO {c['proxima_revision']}"
                else:
                    estado_tag = f" ({c['estado_caso']})" if c.get("estado_caso") else ""
                    mon = f"→ {c['proxima_revision']}{estado_tag}"
            elif c.get("next_step"):
                mon = f"{c['next_step']}"
            elif c.get("monitoring_count", 0) > 0:
                mon = f"{c['monitoring_count']} updates"
            # Meta-review tag
            mr_tag = _format_mr_tag(c.get("meta_review"))
            if mr_tag:
                mon = f"{mon} {mr_tag}" if mon else mr_tag
            lines.append(
                f"{c['ticker']:<7} {c['fecha']:<12} {str(c['decision']):<14} "
                f"{score_str:>5} {conf_str:>5} {mon}"
            )
        return "\n".join(lines)

    # ── Level 1: detailed table ──
    if verbosity == 1:
        for c in cases:
            score_str = f"{c['score']:.1f}" if isinstance(c.get("score"), (int, float)) else "—"
            conf_str = f"{c['confianza']:.2f}" if isinstance(c.get("confianza"), (int, float)) else "—"
            sizing_str = f"{c['sizing']:.1f}%" if isinstance(c.get("sizing"), (int, float)) else "—"
            qa_str = c.get("quality_audit") or "—"

            lines.append(f"┌─ {c['ticker']} ({c['fecha']}) ─── {c['decision']} ───")
            lines.append(f"│  Score: {score_str}  Confianza: {conf_str}  Sizing: {sizing_str}  Modelo: {c.get('modelo', '?')}")
            lines.append(f"│  Quality audit: {qa_str}")

            # Monitor info
            mon_parts = []
            if c.get("monitoring_count", 0) > 0:
                mon_parts.append(f"{c['monitoring_count']} updates")
            if c.get("proxima_revision"):
                if c["proxima_revision"] <= today:
                    mon_parts.append(f"VENCIDO {c['proxima_revision']}")
                else:
                    mon_parts.append(f"next: {c['proxima_revision']}")
            if c.get("estado_caso"):
                mon_parts.append(f"estado: {c['estado_caso']}")
            if c.get("next_step"):
                mon_parts.append(f"step: {c['next_step']}")
            lines.append(f"│  Monitoring: {', '.join(mon_parts) if mon_parts else 'ninguno'}")
            if c.get("monitor_input"):
                text = c["monitor_input"] if len(c["monitor_input"]) <= 100 else c["monitor_input"][:97] + "..."
                lines.append(f"│  Monitor hint: {text}")

            # Meta-review info
            mr = c.get("meta_review")
            if isinstance(mr, dict) and mr.get("estado") == "DONE":
                mr_tag = _format_mr_tag(mr)
                mr_decision = mr.get("meta_decision", "—")
                mr_ts = (mr.get("timestamp") or "")[:10]
                modelo = "gpt-5.2-pro"
                lines.append(f"│  Meta-Review: {mr.get('veredicto', '?')} ({modelo}, {mr_ts})")
                lines.append(f"│  Meta-decisión: {mr_decision}")
            elif isinstance(mr, dict) and mr.get("estado") == "PROMPT_GENERADO":
                lines.append(f"│  Meta-Review: prompt generado, pendiente de respuesta")

            # Agent confidences from DecisionPacket
            dp = _load_decision_packet(c.get("case_dir"))
            if dp:
                agents = dp.get("input_refs", {}).get("agent_reports", [])
                if agents:
                    agent_strs = []
                    for a in agents:
                        role = a.get("agent_role", "?")
                        conf = a.get("confianza_0_1")
                        if isinstance(conf, (int, float)):
                            agent_strs.append(f"{role}={conf:.2f}")
                        else:
                            agent_strs.append(f"{role}=?")
                    lines.append(f"│  Agentes: {', '.join(agent_strs)}")

            lines.append(f"└{'─' * 60}")
        return "\n".join(lines)

    # ── Level 2: full detail with DecisionPacket content ──
    for c in cases:
        score_str = f"{c['score']:.1f}" if isinstance(c.get("score"), (int, float)) else "—"
        conf_str = f"{c['confianza']:.2f}" if isinstance(c.get("confianza"), (int, float)) else "—"
        sizing_str = f"{c['sizing']:.1f}%" if isinstance(c.get("sizing"), (int, float)) else "—"

        lines.append(f"╔══ {c['ticker']} ({c['fecha']}) ══ {c['decision']} ══════════════")
        lines.append(f"║  Score: {score_str}  Confianza: {conf_str}  Sizing: {sizing_str}  Modelo: {c.get('modelo', '?')}")

        dp = _load_decision_packet(c.get("case_dir"))
        if dp:
            empresa = dp.get("empresa", {})
            if empresa.get("nombre"):
                lines.append(f"║  Empresa: {empresa['nombre']} ({empresa.get('sector', '?')} / {empresa.get('industria', '?')})")

            # Agent confidences
            agents = dp.get("input_refs", {}).get("agent_reports", [])
            if agents:
                agent_strs = [
                    f"{a.get('agent_role', '?')}={a.get('confianza_0_1', '?')}"
                    for a in agents
                ]
                lines.append(f"║  Agentes: {', '.join(agent_strs)}")

            resumen = dp.get("resumen_ejecutivo", {})

            # Racional
            racional = resumen.get("racional_5_lineas", [])
            if racional:
                lines.append(f"║")
                lines.append(f"║  RACIONAL:")
                for i, r in enumerate(racional, 1):
                    # Wrap long lines
                    text = r if len(r) <= 120 else r[:117] + "..."
                    lines.append(f"║    {i}. {text}")

            # Riesgos
            riesgos = resumen.get("principales_riesgos", [])
            if riesgos:
                lines.append(f"║")
                lines.append(f"║  RIESGOS:")
                for r in riesgos[:5]:
                    text = r if len(r) <= 120 else r[:117] + "..."
                    lines.append(f"║    - {text}")

            # Lo mas importante
            lmi = resumen.get("lo_mas_importante_ahora", [])
            if lmi:
                lines.append(f"║")
                lines.append(f"║  NEXT STEPS:")
                for item in lmi[:5]:
                    text = item if len(item) <= 120 else item[:117] + "..."
                    lines.append(f"║    - {text}")

        # Monitor
        mon_parts = []
        if c.get("monitoring_count", 0) > 0:
            mon_parts.append(f"{c['monitoring_count']} updates")
        if c.get("proxima_revision"):
            if c["proxima_revision"] <= today:
                mon_parts.append(f"VENCIDO {c['proxima_revision']}")
            else:
                mon_parts.append(f"next: {c['proxima_revision']}")
        lines.append(f"║")
        lines.append(f"║  Monitoring: {', '.join(mon_parts) if mon_parts else 'ninguno'}")
        lines.append(f"╚{'═' * 60}")
        lines.append("")

    return "\n".join(lines)


def show_menu() -> str | None:
    """Muestra menú interactivo, retorna command seleccionado o None."""
    print("\n═══ OPERACIONES DISPONIBLES ═══")
    for key, op in OPERATIONS.items():
        print(f"  [{key}] {op['label']}")
    print()

    try:
        choice = input("Selecciona operación: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    op = OPERATIONS.get(choice)
    if op is None:
        print(f"Opción no válida: {choice}")
        return None
    return op["command"]
