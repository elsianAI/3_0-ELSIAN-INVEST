"""Ingesta de respuesta de meta-review de GPT-5.2 Pro.

Implements §6 of PLAN_META_REVIEW_GPT52PRO.md (v1.2).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .state import load_state, read_modify_write
from .validator import validate_artifact


# ── Public API ────────────────────────────────────────────

def ingest_review(
    case_dir: Path,
    response_path: Path | None = None,
    schemas_dir: Path | None = None,
) -> Path:
    """Ingest a GPT-5.2 Pro meta-review response.

    Parses the response file, extracts and validates the MetaReview_v1 JSON
    block, persists the artifact and the narrative, and updates _estado.json.

    Args:
        case_dir: Path to the case directory.
        response_path: Explicit response file.  When ``None``, auto-resolves
            from ``meta_review.prompt_timestamp`` in _estado.json.
        schemas_dir: Path to the schemas root.  Auto-resolved from workspace
            if ``None``.

    Returns:
        Path to the persisted MetaReview_v1 artifact.

    Raises:
        FileNotFoundError: When the response file cannot be found.
        RuntimeError: When required fields are missing and cannot be recovered.
    """
    state = load_state(case_dir)
    ticker = state.get("ticker", "?")
    fecha = state.get("fecha_caso", "?")
    mr_state = state.get("meta_review", {})
    prompt_ts = mr_state.get("prompt_timestamp")

    # 1. Resolve response file
    if response_path is None:
        response_path = _resolve_response_path(case_dir, prompt_ts)
    if not response_path.exists():
        expected = f"_review_response_raw_{prompt_ts}.md" if prompt_ts else "_review_response_raw_*.md"
        raise FileNotFoundError(
            f"No se encuentra la respuesta de review.\n"
            f"Copia la respuesta de GPT-5.2 Pro a: {case_dir / expected}"
        )

    raw_text = response_path.read_text(encoding="utf-8")

    # 2. Extract JSON block
    review_json, extraction_note = _extract_json_block(raw_text)

    if review_json is None:
        # Save narrative only as PARCIAL
        narrative_path = _save_narrative(case_dir, raw_text, prompt_ts)
        _update_state_partial(case_dir, prompt_ts, narrative_path.name)
        raise RuntimeError(
            f"No se encontró bloque JSON válido en la respuesta.\n"
            f"Narrativa guardada en: {narrative_path}\n"
            f"Estado marcado como PARCIAL.\n"
            f"{extraction_note or ''}"
        )

    # 3. Validate against schema
    if schemas_dir is None:
        schemas_dir = _resolve_schemas_dir(case_dir)
    is_valid, errors = validate_artifact(review_json, "MetaReview_v1", schemas_dir)

    # 4. Permissive mode: fill missing nullable fields with defaults, then re-validate strictly
    if not is_valid:
        review_json, recovered = _recover_missing_fields(review_json, errors)
        # Re-validate after recovery — must pass fully this time
        is_valid_2, errors_2 = validate_artifact(review_json, "MetaReview_v1", schemas_dir)
        if not is_valid_2:
            # Abort: schema validation fails even after recovery
            narrative_path = _save_narrative(case_dir, raw_text, prompt_ts)
            _update_state_partial(case_dir, prompt_ts, narrative_path.name)
            raise RuntimeError(
                f"Schema validation failed tras recuperación de campos opcionales.\n"
                f"Errores ({len(errors_2)}): {errors_2[:5]}\n"
                f"Campos recuperados: {recovered}\n"
                f"Narrativa guardada en: {narrative_path}\n"
                f"Corrige el JSON manualmente o pide a GPT-5.2 Pro que regenere la respuesta."
            )
        errors = errors_2  # empty or warnings only

    # 5. Inject _meta block
    review_json["_meta"] = {
        "motor": "ASISTIDO",
        "plataforma": "chatgpt",
        "modelo": "gpt-5.2-pro",
        "proyecto_chatgpt": "ELSIAN Meta-Review",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version_protocolo": "V3",
    }

    # 6. Ensure version_esquema
    if "version_esquema" not in review_json:
        review_json["version_esquema"] = "MetaReview_v1"

    # 7. Ensure caso_id
    if "caso_id" not in review_json or not review_json["caso_id"]:
        review_json["caso_id"] = state.get("caso_id", f"CASE_{fecha.replace('-', '')}_{ticker}")

    # 8. Ensure fecha_review
    if "fecha_review" not in review_json or not review_json["fecha_review"]:
        review_json["fecha_review"] = datetime.now(timezone.utc).isoformat()

    # 9. Ensure reviewer block
    if "reviewer" not in review_json or not isinstance(review_json.get("reviewer"), dict):
        review_json["reviewer"] = {
            "modelo": "gpt-5.2-pro",
            "plataforma": "chatgpt",
            "proyecto": "ELSIAN Meta-Review",
        }

    # 10. Handle DecisionPacket hash check
    dp_hash_prompt = mr_state.get("dp_hash")
    dp_ref = mr_state.get("dp_ref")
    dp_snapshot = review_json.get("decision_packet_snapshot", {})
    if dp_hash_prompt and dp_ref:
        current_dp = case_dir / dp_ref
        if current_dp.exists():
            current_hash = _sha256_file(current_dp)
            if current_hash != dp_hash_prompt:
                print(
                    f"⚠ WARNING: El DecisionPacket ha cambiado desde que se generó el prompt.\n"
                    f"  Hash del prompt: {dp_hash_prompt[:16]}...\n"
                    f"  Hash actual:     {current_hash[:16]}...\n"
                    f"  Regenera: python3 -m engine review {ticker}"
                )
        # Fill snapshot if not provided by GPT
        if not dp_snapshot.get("hash_sha256"):
            dp_snapshot["hash_sha256"] = dp_hash_prompt
        if not dp_snapshot.get("timestamp_compilacion") and prompt_ts:
            dp_snapshot["timestamp_compilacion"] = _ts_to_iso(prompt_ts)
        review_json["decision_packet_snapshot"] = dp_snapshot

    # 11. Set decision_packet_ref if missing
    if not review_json.get("decision_packet_ref") and dp_ref:
        review_json["decision_packet_ref"] = dp_ref

    # 12. Handle revision numbering / rotation
    artifact_name = f"MetaReview_v1_{ticker}_{fecha.replace('-', '')}.json"
    artifact_path = case_dir / artifact_name
    if artifact_path.exists():
        # Rotate existing and compute next revision monotonically
        _rotate_artifact(artifact_path)
        revision = _next_revision_num(case_dir, artifact_name)
    else:
        # First review: check if there are already rotated files (shouldn't happen, but safe)
        existing_max = _max_existing_revision(case_dir, artifact_name)
        revision = max(1, existing_max + 1)
    if "decision_packet_snapshot" in review_json:
        review_json["decision_packet_snapshot"]["revision_num"] = revision

    # 13. Save artifact
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(review_json, f, indent=2, ensure_ascii=False)

    # 14. Save narrative
    narrative_path = _save_narrative(case_dir, raw_text, prompt_ts)

    # 15. Update _estado.json
    veredicto = review_json.get("veredicto_meta", {}).get("estado", "?")
    meta_decision = review_json.get("meta_decision", {}).get("accion", "?")
    condiciones = review_json.get("meta_decision", {}).get("condiciones", [])
    problemas = review_json.get("coherencia_logica", {}).get("problemas_detectados", [])
    n_alta = sum(1 for p in problemas if isinstance(p, dict) and p.get("severidad") == "ALTA")

    def _modifier(st: dict) -> None:
        st["meta_review"] = {
            "estado": "DONE",
            "artefacto": artifact_name,
            "veredicto": veredicto,
            "meta_decision": meta_decision,
            "prompt_timestamp": prompt_ts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dp_hash": mr_state.get("dp_hash"),
            "dp_ref": mr_state.get("dp_ref"),
        }

    read_modify_write(case_dir, _modifier)

    # 16. Print summary
    print(f"✓ MetaReview ingestado: {artifact_name}")
    print(f"  Veredicto: {veredicto}")
    print(f"  Meta-decisión: {meta_decision}")
    if condiciones:
        print(f"  Condiciones: {condiciones}")
    print(f"  Problemas detectados: {len(problemas)} ({n_alta} ALTA severidad)")
    if not is_valid and errors:
        print(f"  ⚠ Warnings de validación: {len(errors)}")
        for e in errors[:3]:
            print(f"    - {e}")
    print(f"  _estado.json actualizado")

    return artifact_path


# ── JSON extraction ───────────────────────────────────────

def _extract_json_block(text: str) -> tuple[dict | None, str | None]:
    """Extract the MetaReview JSON block from a GPT-5.2 Pro response.

    Tries multiple extraction strategies with increasing permissiveness.
    """
    # Strategy 1: Standard ```json ... ``` block
    pattern = r"```json\s*\n(.*?)\n\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    for match in reversed(matches):  # Prefer the LAST json block
        try:
            parsed = json.loads(match)
            if isinstance(parsed, dict) and _looks_like_meta_review(parsed):
                return parsed, None
        except json.JSONDecodeError:
            continue

    # Strategy 2: ``` block without json label
    pattern2 = r"```\s*\n(.*?)\n\s*```"
    matches2 = re.findall(pattern2, text, re.DOTALL)
    for match in reversed(matches2):
        match = match.strip()
        if match.startswith("{"):
            try:
                parsed = json.loads(match)
                if isinstance(parsed, dict) and _looks_like_meta_review(parsed):
                    return parsed, "Extracted from unlabeled code block"
            except json.JSONDecodeError:
                continue

    # Strategy 3: Find the largest { ... } block that looks like MetaReview
    brace_blocks = _find_brace_blocks(text)
    for block in brace_blocks:
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict) and _looks_like_meta_review(parsed):
                return parsed, "Extracted from bare JSON block (no code fences)"
        except json.JSONDecodeError:
            continue

    return None, "No se encontró bloque JSON válido en la respuesta"


def _looks_like_meta_review(d: dict) -> bool:
    """Heuristic check: does this dict look like a MetaReview_v1?"""
    hints = ("veredicto_meta", "evaluacion_gates", "meta_decision", "coherencia_logica")
    return sum(1 for h in hints if h in d) >= 2


def _find_brace_blocks(text: str) -> list[str]:
    """Find top-level { ... } blocks in text, sorted by length descending."""
    blocks = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                blocks.append(text[start : i + 1])
                start = -1
    blocks.sort(key=len, reverse=True)
    return blocks


# ── Recovery / permissive mode ────────────────────────────

def _recover_missing_fields(review: dict, errors: list[str]) -> tuple[dict, list[str]]:
    """Attempt to fill missing optional fields with defaults."""
    recovered = []

    # Common defaults for nullable arrays/objects
    nullable_defaults = {
        "evaluacion_calidad_pipeline": None,
        "alertas_compilador_respondidas": None,
        "desacuerdos_agentes": None,
        "kill_criteria_evaluacion": None,
    }
    for field, default in nullable_defaults.items():
        if field not in review:
            review[field] = default
            recovered.append(field)

    # Ensure puntos_ciegos is at least empty array
    if "puntos_ciegos" not in review:
        review["puntos_ciegos"] = []
        recovered.append("puntos_ciegos")

    if "recomendaciones" not in review:
        review["recomendaciones"] = []
        recovered.append("recomendaciones")

    if "evaluacion_supuestos_criticos" not in review:
        review["evaluacion_supuestos_criticos"] = []
        recovered.append("evaluacion_supuestos_criticos")

    if "evaluacion_gates" not in review:
        review["evaluacion_gates"] = []
        recovered.append("evaluacion_gates")

    # Ensure coherencia_probabilistica_categorica
    if "coherencia_probabilistica_categorica" not in review:
        review["coherencia_probabilistica_categorica"] = {
            "alineadas": True,
            "incongruencias": None,
            "justificacion": "No evaluado",
        }
        recovered.append("coherencia_probabilistica_categorica")

    return review, recovered


def _check_critical_fields(review: dict) -> list[str]:
    """Check that critical required fields are present."""
    critical = ["veredicto_meta", "meta_decision"]
    missing = [f for f in critical if f not in review or not review[f]]
    return missing


# ── State updates ─────────────────────────────────────────

def _update_state_partial(case_dir: Path, prompt_ts: str | None, narrative_name: str) -> None:
    """Mark meta_review state as PARCIAL (narrative only, no JSON)."""
    def _modifier(st: dict) -> None:
        mr = st.setdefault("meta_review", {})
        mr["estado"] = "PARCIAL"
        mr["prompt_timestamp"] = prompt_ts
        mr["narrative"] = narrative_name
        mr["timestamp"] = datetime.now(timezone.utc).isoformat()

    read_modify_write(case_dir, _modifier)


# ── File helpers ──────────────────────────────────────────

def _resolve_response_path(case_dir: Path, prompt_ts: str | None) -> Path:
    """Resolve the response file path, matching timestamp or most recent."""
    if prompt_ts:
        exact = case_dir / f"_review_response_raw_{prompt_ts}.md"
        if exact.exists():
            return exact

    # Fallback: most recent response file
    candidates = sorted(case_dir.glob("_review_response_raw_*.md"), reverse=True)
    if candidates:
        return candidates[0]

    # Last resort: expected name
    if prompt_ts:
        return case_dir / f"_review_response_raw_{prompt_ts}.md"
    return case_dir / "_review_response_raw.md"


def _resolve_schemas_dir(case_dir: Path) -> Path:
    """Resolve _schemas directory from case_dir by walking up."""
    # case_dir = workspace/casos/TICKER/DATE
    workspace = case_dir.parent.parent.parent
    schemas = workspace / "_schemas"
    if schemas.exists():
        return schemas
    # Fallback: try relative to cwd
    cwd_schemas = Path.cwd() / "_schemas"
    if cwd_schemas.exists():
        return cwd_schemas
    return schemas  # Return expected path even if missing


def _save_narrative(case_dir: Path, raw_text: str, prompt_ts: str | None) -> Path:
    """Save the full narrative response."""
    ts_suffix = f"_{prompt_ts}" if prompt_ts else ""
    path = case_dir / f"_review_narrative_gpt52pro{ts_suffix}.md"
    path.write_text(raw_text, encoding="utf-8")
    return path


def _max_existing_revision(case_dir: Path, artifact_name: str) -> int:
    """Find the highest existing _revN number for an artifact base name."""
    stem = Path(artifact_name).stem
    suffix = Path(artifact_name).suffix
    max_rev = 0
    for f in case_dir.glob(f"{stem}_rev*{suffix}"):
        match = re.search(r"_rev(\d+)", f.stem)
        if match:
            max_rev = max(max_rev, int(match.group(1)))
    return max_rev


def _next_revision_num(case_dir: Path, artifact_name: str) -> int:
    """Compute the next monotonically increasing revision number."""
    return _max_existing_revision(case_dir, artifact_name) + 1


def _rotate_artifact(artifact_path: Path) -> None:
    """Rotate existing artifact to _revN suffix."""
    stem = artifact_path.stem
    suffix = artifact_path.suffix
    parent = artifact_path.parent

    # Find next revision number
    rev = 1
    while (parent / f"{stem}_rev{rev}{suffix}").exists():
        rev += 1
    artifact_path.rename(parent / f"{stem}_rev{rev}{suffix}")


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _ts_to_iso(ts: str) -> str:
    """Convert YYYYMMDDTHHMMSS to ISO 8601."""
    try:
        dt = datetime.strptime(ts, "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return ts
