"""Compila prompt de meta-review para GPT-5.2 Pro via proyecto ChatGPT.

Implements §4 of PLAN_META_REVIEW_GPT52PRO.md (v1.2).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .state import load_state, read_modify_write


# ── Constants ─────────────────────────────────────────────

MAX_PROMPT_BYTES_L1 = 120_000   # Nivel 1 truncation threshold
MAX_PROMPT_BYTES_L2 = 150_000   # Nivel 2 truncation threshold
MAX_PROMPT_BYTES_L3 = 200_000   # Nivel 3 (edge case)


# ── Public API ────────────────────────────────────────────

def compile_review_prompt(
    case_dir: Path,
    output_path: Path | None = None,
    timestamp: str | None = None,
) -> Path:
    """Compile a meta-review prompt for a completed case.

    Reads pipeline artifacts and generates a markdown prompt optimised for
    GPT-5.2 Pro within a ChatGPT Project context.

    Args:
        case_dir: Path to the case directory (e.g. casos/TZOO/2026-02-21).
        output_path: Explicit output path.  When ``None`` the prompt is saved
            to ``{case_dir}/_review_prompt_gpt52pro_{TS}.md``.
        timestamp: Explicit timestamp string (``YYYYMMDDTHHMMSS``).
            Generated automatically when ``None``.

    Returns:
        Path to the written prompt file.

    Raises:
        FileNotFoundError: When ``_estado.json`` is missing.
        RuntimeError: When the pipeline is not COMPLETO or the DecisionPacket
            cannot be found.
    """
    # 1. Load state and validate pipeline
    state = load_state(case_dir)
    if state.get("estado_pipeline") != "COMPLETO":
        raise RuntimeError(
            f"Pipeline no completado (estado={state.get('estado_pipeline')}). "
            f"Ejecuta: python3 -m engine continue {state.get('ticker', '?')}"
        )

    ticker = state.get("ticker", "?")
    fecha_caso = state.get("fecha_caso", "?")

    # 2. Generate timestamp
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    # 3. Load DecisionPacket
    dp, dp_path = _load_decision_packet(case_dir, ticker)
    if dp is None:
        raise RuntimeError(
            f"DecisionPacket no encontrado en {case_dir}. "
            "Verifica que el paso ARBITRO se completó correctamente."
        )
    dp_hash = _sha256_file(dp_path)

    # 4. Load agent reports (fusionados)
    bull_report = _load_agent_report(case_dir, "BULL", ticker, fecha_caso)
    red_team_report = _load_agent_report(case_dir, "REDTEAM", ticker, fecha_caso)
    catalyst_report = _load_agent_report(case_dir, "CATALYST", ticker, fecha_caso)
    forensic_report = _load_agent_report(case_dir, "FORENSIC", ticker, fecha_caso)

    # 5. Load ImpliedExpectations
    implied = _load_implied(case_dir, ticker, fecha_caso)

    # 6. Load quality votes summary
    votes_summary = _load_votes_summary(case_dir)

    # 7. Build prompt sections
    sections = []
    sections.append(_build_header(ticker, fecha_caso, state, dp, ts))
    sections.append(_build_quality_votes_section(votes_summary))
    sections.append(_build_implied_section(implied))
    sections.append(_build_agent_section("BULL", "Perspectiva BULL", bull_report, include_claims=True))
    sections.append(_build_agent_section("RED_TEAM", "Perspectiva RED_TEAM", red_team_report, include_claims=True))
    sections.append(_build_agent_section("CATALYST", "Perspectiva CATALYST", catalyst_report, include_claims=False))
    sections.append(_build_agent_section("FORENSIC", "Perspectiva FORENSIC", forensic_report, include_claims=False))
    sections.append(_build_dp_section(dp))
    sections.append(_build_alerts_section(dp, state))
    sections.append(_build_footer())

    # 8. Assemble and apply truncation if needed
    prompt = "\n".join(s for s in sections if s)
    prompt, truncation_level = _apply_truncation(prompt, sections, dp, bull_report, red_team_report, catalyst_report, forensic_report)

    # 9. Write output
    if output_path is None:
        output_path = case_dir / f"_review_prompt_gpt52pro_{ts}.md"
    output_path.write_text(prompt, encoding="utf-8")

    # 10. Update _estado.json with prompt metadata
    #     Always set estado = PROMPT_GENERADO: a new prompt invalidates any
    #     previous review (DONE/PARCIAL) because the DP may have changed.
    def _modifier(st: dict) -> None:
        mr = st.setdefault("meta_review", {})
        mr["prompt_timestamp"] = ts
        mr["dp_hash"] = dp_hash
        mr["dp_ref"] = dp_path.name
        mr["estado"] = "PROMPT_GENERADO"

    read_modify_write(case_dir, _modifier)

    return output_path


# ── Prompt section builders ───────────────────────────────

def _build_header(ticker: str, fecha: str, state: dict, dp: dict, ts: str) -> str:
    """Build the context header section."""
    # Extract models used
    meta = dp.get("_meta", {})
    fusion = meta.get("fusion", {})
    modelos = fusion.get("modelos_usados", [])
    modelos_str = ", ".join(str(m) for m in modelos) if modelos else "desconocido"

    resumen = dp.get("resumen_ejecutivo", {})
    decision = resumen.get("decision", state.get("decision", "?"))
    score = resumen.get("score_global", state.get("score", "?"))
    confianza = resumen.get("confianza_global_0_1", state.get("confianza", "?"))

    pipeline_ts = state.get("_meta", {}).get("ultima_actualizacion", "?")

    return f"""# Meta-Review: {ticker} — {fecha}

## Contexto del caso
- Ticker: {ticker}
- Fecha de análisis: {fecha}
- Pipeline completado: {pipeline_ts}
- Timestamp de compilación: {ts}
- Modelos utilizados: {modelos_str}
- Decisión ARBITRO: {decision} (score: {score}/100, confianza: {confianza})
"""


def _build_quality_votes_section(votes_summary: str | None) -> str:
    """Build quality votes section with anti-bias note."""
    if not votes_summary:
        return ""
    return f"""---

## Calidad del pipeline (quality votes)

> **Nota anti-sesgo:** Los scores de calidad son una señal de calidad formal del pipeline (validación de schema, completitud de campos, ratio de nulos). No son indicadores de verdad fundamental ni de calidad del razonamiento. Úsalos como contexto, no como juicio previo.

{votes_summary}
"""


def _build_implied_section(implied: dict | None) -> str:
    """Build implied expectations section."""
    if not implied:
        return ""
    # Extract the expectations grid
    grid = implied.get("expectativas_implicitas", implied.get("implied_grid", {}))
    if not grid:
        return ""

    lines = ["---\n", "## Expectativas implícitas del mercado\n"]
    if isinstance(grid, dict):
        lines.append("```json")
        lines.append(json.dumps(grid, indent=2, ensure_ascii=False))
        lines.append("```")
    elif isinstance(grid, list):
        lines.append("```json")
        lines.append(json.dumps(grid, indent=2, ensure_ascii=False))
        lines.append("```")
    return "\n".join(lines)


def _build_agent_section(
    role: str,
    title: str,
    report: dict | None,
    include_claims: bool = False,
) -> str:
    """Build an agent report section."""
    if report is None:
        return f"""---

## {title}

[ARTIFACT NO DISPONIBLE]
"""

    lines = [f"---\n", f"## {title}\n"]

    # Executive summary
    resumen = report.get("resumen_ejecutivo", report.get("executive_summary", ""))
    if isinstance(resumen, dict):
        resumen_text = resumen.get("texto", resumen.get("summary", json.dumps(resumen, ensure_ascii=False)))
    elif isinstance(resumen, str):
        resumen_text = resumen
    else:
        resumen_text = str(resumen)

    lines.append("### Resumen ejecutivo")
    lines.append(resumen_text)
    lines.append("")

    # Claims (only for BULL and RED_TEAM, filtered by priority)
    if include_claims:
        claims = _extract_filtered_claims(report)
        if claims:
            lines.append("### Claims principales (CRITICO + IMPORTANTE)")
            lines.append("```json")
            lines.append(json.dumps(claims, indent=2, ensure_ascii=False))
            lines.append("```")

    return "\n".join(lines)


def _build_dp_section(dp: dict) -> str:
    """Build the DecisionPacket section (full JSON)."""
    return f"""---

## DecisionPacket completo (ARBITRO)

```json
{json.dumps(dp, indent=2, ensure_ascii=False)}
```
"""


def _build_alerts_section(dp: dict, state: dict) -> str:
    """Build auto-generated contextual alerts section."""
    alerts = _generate_alerts(dp, state)
    if not alerts:
        return """---

## Solicitud de review

Revisa este caso aplicando los criterios definidos en las instrucciones del proyecto.

No se han detectado alertas específicas para este caso.

Recuerda finalizar tu análisis con el bloque JSON MetaReview_v1.
"""

    alerts_text = "\n".join(f"- {a}" for a in alerts)
    return f"""---

## Solicitud de review

Revisa este caso aplicando los criterios definidos en las instrucciones del proyecto.

**Áreas de especial atención para este caso:**

{alerts_text}

Recuerda finalizar tu análisis con el bloque JSON MetaReview_v1.
"""


def _build_footer() -> str:
    return ""


# ── Alert generation (§4.2.3) ────────────────────────────

def _generate_alerts(dp: dict, state: dict) -> list[str]:
    """Generate contextual alerts based on DecisionPacket analysis."""
    alerts = []

    resumen = dp.get("resumen_ejecutivo", {})
    decision = resumen.get("decision", "")
    score = resumen.get("score_global")
    confianza = resumen.get("confianza_global_0_1")

    # Gates analysis
    gates = dp.get("gates", dp.get("evaluacion_gates", {}))
    if isinstance(gates, dict):
        for gate_name, gate_data in gates.items():
            if isinstance(gate_data, dict):
                status = gate_data.get("estado", gate_data.get("status", ""))
                if status == "CONDITIONAL":
                    alerts.append(
                        f'El gate "{gate_name}" es CONDITIONAL — evalúa si la justificación '
                        "es suficiente para no bloquearlo"
                    )
    elif isinstance(gates, list):
        for gate_data in gates:
            if isinstance(gate_data, dict):
                gate_name = gate_data.get("nombre", gate_data.get("gate", "?"))
                status = gate_data.get("estado", gate_data.get("status", ""))
                if status == "CONDITIONAL":
                    alerts.append(
                        f'El gate "{gate_name}" es CONDITIONAL — evalúa si la justificación '
                        "es suficiente para no bloquearlo"
                    )

    # Low confidence
    if isinstance(confianza, (int, float)) and confianza < 0.5:
        alerts.append(
            f"La confianza global es baja ({confianza:.2f}) — investiga si es por "
            "falta de datos o por debilidad de la tesis"
        )

    # Asymmetry ratio
    prob = dp.get("probabilistica", resumen.get("probabilistica", {}))
    if isinstance(prob, dict):
        ratio = prob.get("ratio_asimetria")
        if isinstance(ratio, (int, float)) and ratio < 1.0:
            alerts.append(
                f"La asimetría es desfavorable ({ratio:.2f}) — el downside "
                "supera al upside base"
            )

        # Extreme probability
        p_exito = prob.get("probabilidad_exito")
        if isinstance(p_exito, (int, float)):
            if p_exito > 0.8:
                alerts.append(
                    f"Probabilidad de éxito extremadamente alta ({p_exito:.2f}) — "
                    "evalúa si hay suficiente evidencia para una convicción tan fuerte"
                )
            elif p_exito < 0.2:
                alerts.append(
                    f"Probabilidad de éxito extremadamente baja ({p_exito:.2f}) — "
                    "evalúa si hay suficiente evidencia para una convicción tan fuerte"
                )

    # Unresolved disagreements
    arbitracion = dp.get("arbitracion", dp.get("arbitration", {}))
    if isinstance(arbitracion, dict):
        desacuerdos = arbitracion.get("desacuerdos", arbitracion.get("disagreements", []))
        if isinstance(desacuerdos, list):
            no_resueltos = [d for d in desacuerdos
                           if isinstance(d, dict) and d.get("estado", d.get("status", "")) == "NO_RESUELTO"]
            if no_resueltos:
                alerts.append(
                    f"Hay {len(no_resueltos)} desacuerdo(s) no resueltos entre agentes "
                    "— evalúa si la resolución parcial es aceptable"
                )

    # Sizing at max
    sizing = resumen.get("tamaño_recomendado_pct_cartera")
    if isinstance(sizing, (int, float)) and sizing >= 10.0:
        alerts.append(
            "El sizing está al máximo permitido (10%) — evalúa si la convicción "
            "justifica la concentración"
        )

    # Critical assumptions without falsification tests
    ledger = dp.get("assumption_ledger", dp.get("supuestos", []))
    if isinstance(ledger, list):
        sin_falsacion = [a for a in ledger
                         if isinstance(a, dict)
                         and a.get("criticidad", a.get("priority", "")) == "CRITICO"
                         and not a.get("test_falsacion", a.get("falsification_test"))]
        if sin_falsacion:
            alerts.append(
                f"Hay {len(sin_falsacion)} supuesto(s) CRITICOS sin test de falsación definido"
            )

    # Incoherent score/decision combos
    if isinstance(score, (int, float)):
        if str(decision).upper() == "WATCHLIST" and score > 70:
            alerts.append(
                f"Score alto ({score}) pero decisión WATCHLIST — posible incoherencia"
            )
        if str(decision).upper() == "INVERTIR" and score < 50:
            alerts.append(
                f"Score bajo ({score}) pero decisión INVERTIR — posible incoherencia"
            )

    return alerts


# ── Artifact loaders ──────────────────────────────────────

def _load_decision_packet(case_dir: Path, ticker: str) -> tuple[dict | None, Path | None]:
    """Load the DecisionPacket with deterministic priority."""
    candidates: list[Path] = []

    # Priority 1: ticker-specific Engine file
    candidates.extend(sorted(case_dir.glob(f"DecisionPacket_v2_{ticker}_*_Engine.json"), reverse=True))

    # Priority 2: generic name
    generic = case_dir / "DecisionPacket_v2.json"
    if generic.exists():
        candidates.append(generic)

    # Priority 3: any DP
    for f in sorted(case_dir.glob("DecisionPacket*.json"), reverse=True):
        if f not in candidates:
            candidates.append(f)

    for f in candidates:
        try:
            with open(f) as fh:
                return json.load(fh), f
        except (json.JSONDecodeError, OSError):
            continue
    return None, None


def _load_agent_report(case_dir: Path, role: str, ticker: str, fecha: str) -> dict | None:
    """Load a fusioned AgentReport by role."""
    fecha_compact = fecha.replace("-", "")
    patterns = [
        f"AgentReport_v1_{role}_{ticker}_{fecha_compact}_Engine.json",
        f"AgentReport_v1_{role}_{ticker}_{fecha}_Engine.json",
    ]
    for pattern in patterns:
        path = case_dir / pattern
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

    # Glob fallback
    for f in sorted(case_dir.glob(f"AgentReport_v1_{role}*.json"), reverse=True):
        try:
            with open(f) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _load_implied(case_dir: Path, ticker: str, fecha: str) -> dict | None:
    """Load ImpliedExpectations artifact."""
    fecha_compact = fecha.replace("-", "")
    patterns = [
        f"ImpliedExpectations_v1_{ticker}_{fecha_compact}_Engine.json",
        f"ImpliedExpectations_v1_{ticker}_{fecha}_Engine.json",
    ]
    for pattern in patterns:
        path = case_dir / pattern
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
    for f in sorted(case_dir.glob("ImpliedExpectations_v1*.json"), reverse=True):
        try:
            with open(f) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _load_votes_summary(case_dir: Path) -> str | None:
    """Load quality votes and build a summary table.

    Votes are stored as individual StepVote_v1 files in {case_dir}/_votes/.
    Fusion votes (without ``_model_`` in the name) are the aggregated scores.
    Per-model votes contain ``_model_{name}`` and are used for the range column.
    """
    votes_dir = case_dir / "_votes"
    if not votes_dir.exists() or not votes_dir.is_dir():
        return None

    # Collect fusion votes (no _model_ in name) — one per step
    fusion_files = sorted(
        f for f in votes_dir.glob("StepVote_v1_*.json")
        if "_model_" not in f.name
    )
    if not fusion_files:
        return None

    # Collect per-model votes for range display
    model_files = sorted(
        f for f in votes_dir.glob("StepVote_v1_*_model_*.json")
    )
    # Group model scores by canonical step name (strip __model_xxx suffix)
    model_scores_by_step: dict[str, list[float]] = {}
    for mf in model_files:
        try:
            with open(mf) as f:
                data = json.load(f)
            raw_step = data.get("step_name", "?")
            # step_name in model votes is like "BULL__model_claude" — extract base step
            canonical = data.get("context", {}).get("canonical_step_name")
            if not canonical:
                canonical = raw_step.split("__model_")[0] if "__model_" in raw_step else raw_step
            score = data.get("score_raw_0_100")
            if isinstance(score, (int, float)):
                model_scores_by_step.setdefault(canonical, []).append(score)
        except (json.JSONDecodeError, OSError):
            continue

    rows = []
    for vf in fusion_files:
        try:
            with open(vf) as f:
                data = json.load(f)
            step = data.get("step_name", "?")
            fusion_score = data.get("score_raw_0_100")
            if fusion_score is None:
                continue
            fusion_str = f"{fusion_score:.1f}"

            # Model range
            m_scores = model_scores_by_step.get(step, [])
            if m_scores:
                range_str = f"{min(m_scores):.0f}–{max(m_scores):.0f}"
            else:
                range_str = "—"

            rows.append(f"| {step} | {fusion_str} | {range_str} |")
        except (json.JSONDecodeError, OSError):
            continue

    if not rows:
        return None
    header = "| Paso | Score fusión | Rango modelos |\n|------|-------------|---------------|\n"
    return header + "\n".join(rows)


# ── Claim extraction ──────────────────────────────────────

def _extract_filtered_claims(report: dict) -> list[dict]:
    """Extract CRITICO + IMPORTANTE claims from an agent report as JSON fragments."""
    # Navigate to claims in different possible structures
    claims = report.get("claims", [])
    if not claims:
        tesis = report.get("tesis", {})
        if isinstance(tesis, dict):
            claims = tesis.get("claims", [])
    if not claims:
        body = report.get("body", report.get("contenido", {}))
        if isinstance(body, dict):
            claims = body.get("claims", [])

    if not isinstance(claims, list):
        return []

    filtered = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        priority = claim.get("criticidad", claim.get("priority", claim.get("importancia", "")))
        if str(priority).upper() in ("CRITICO", "IMPORTANTE", "CRITICAL", "IMPORTANT"):
            # Extract relevant fields only
            slim = {
                "claim_id": claim.get("claim_id", claim.get("id")),
                "enunciado": claim.get("enunciado", claim.get("statement", claim.get("text"))),
                "criticidad": priority,
                "confianza": claim.get("confianza", claim.get("confidence")),
            }
            # Remove None values
            slim = {k: v for k, v in slim.items() if v is not None}
            filtered.append(slim)
    return filtered


# ── Truncation logic (§4.6) ──────────────────────────────

def _apply_truncation(
    prompt: str,
    sections: list[str],
    dp: dict,
    bull: dict | None,
    red_team: dict | None,
    catalyst: dict | None,
    forensic: dict | None,
) -> tuple[str, int]:
    """Apply truncation levels if prompt exceeds size thresholds.

    Returns (truncated_prompt, truncation_level).
    """
    size = len(prompt.encode("utf-8"))

    if size <= MAX_PROMPT_BYTES_L1:
        return prompt, 0

    # Level 1: Reduce IMPORTANT claims to enunciado only (drop evidence grids)
    if size <= MAX_PROMPT_BYTES_L2:
        # Already done by _extract_filtered_claims (only slim fields)
        note = "\n\n> [NOTA: Este prompt ha sido compactado (nivel 1). Algunos detalles de claims se han omitido por extensión.]\n"
        return prompt + note, 1

    # Level 2: Exclude CATALYST and FORENSIC summaries
    if size <= MAX_PROMPT_BYTES_L3:
        # Rebuild without catalyst/forensic sections
        rebuilt_sections = []
        for s in sections:
            if "Perspectiva CATALYST" in s or "Perspectiva FORENSIC" in s:
                continue
            rebuilt_sections.append(s)
        rebuilt = "\n".join(s for s in rebuilt_sections if s)
        note = "\n\n> [NOTA: Este prompt ha sido compactado (nivel 2). Los resúmenes de CATALYST y FORENSIC se han omitido por extensión.]\n"
        return rebuilt + note, 2

    # Level 3: Keep only executive summaries + DP
    rebuilt_sections = []
    for s in sections:
        if "Claims principales" in s:
            # Strip claims JSON blocks
            s = re.sub(r"### Claims principales.*?```\n", "", s, flags=re.DOTALL)
        if "Perspectiva CATALYST" in s or "Perspectiva FORENSIC" in s:
            continue
        rebuilt_sections.append(s)
    rebuilt = "\n".join(s for s in rebuilt_sections if s)
    note = "\n\n> [NOTA: Este prompt ha sido compactado (nivel 3). Claims individuales de agentes y secciones de CATALYST/FORENSIC se han omitido por extensión.]\n"
    return rebuilt + note, 3


# ── Utilities ─────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
