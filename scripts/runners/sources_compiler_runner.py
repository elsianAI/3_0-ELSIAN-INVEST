#!/usr/bin/env python3
"""Compile partial Step-1 outputs into final SourcesPack_v1."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    from clean_md_pipeline import generate_clean_md as _generate_clean_md_unified
except Exception:
    from scripts.runners.clean_md_pipeline import generate_clean_md as _generate_clean_md_unified
try:
    from clean_md_quality import is_clean_md_useful as _is_clean_md_useful_common
except Exception:
    from scripts.runners.clean_md_quality import is_clean_md_useful as _is_clean_md_useful_common


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def normalize_type(value: Any) -> str:
    if not isinstance(value, str):
        return "OTHER"
    t = value.strip().upper()
    if not t:
        return "OTHER"
    return t


def infer_category(source_type: str) -> str:
    st = normalize_type(source_type)
    if st in {"10-K", "10-Q", "20-F", "6-K", "8-K", "DEF14A", "SEC_EXHIBIT", "CREDIT_AGREEMENT",
              "ANNUAL_REPORT", "INTERIM_REPORT", "REGULATORY_FILING"}:
        return "REGULATORIO"
    if "TRANSCRIPT" in st:
        return "TRANSCRIPCION"
    if st in {"INVESTOR_PRESENTATION", "IR_NEWS", "PRESS_RELEASE"}:
        return "IR"
    if st == "MARKET_DATA":
        return "MERCADO"
    return "OTRA"


def source_key(source: Dict[str, Any]) -> Tuple[str, str]:
    url = source.get("url")
    accession = source.get("accession_number")
    url_key = url.strip().lower() if isinstance(url, str) else ""
    acc_key = accession.strip().lower() if isinstance(accession, str) else ""
    return url_key, acc_key


def _normalized_content_hash(source: Dict[str, Any]) -> str:
    raw = source.get("content_hash")
    if not isinstance(raw, str):
        return ""
    h = raw.strip().lower()
    if len(h) < 16:
        return ""
    return h


def _source_selection_score(source: Dict[str, Any]) -> float:
    try:
        return float(source.get("selection_score") or 0.0)
    except Exception:
        return 0.0


def _prefer_source_for_hash(existing: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    ex_score = _source_selection_score(existing)
    cand_score = _source_selection_score(candidate)
    if cand_score > ex_score:
        return True
    if cand_score < ex_score:
        return False

    ex_estimated = bool(existing.get("fecha_publicacion_estimated"))
    cand_estimated = bool(candidate.get("fecha_publicacion_estimated"))
    if ex_estimated != cand_estimated:
        return not cand_estimated

    ex_id = str(existing.get("source_id") or "~")
    cand_id = str(candidate.get("source_id") or "~")
    return cand_id < ex_id


# ── Dedup quality helpers ─────────────────────────────────
_TIPO_PRIORITY: Dict[str, int] = {
    "10-K": 10, "20-F": 10, "ANNUAL_REPORT": 10,
    "10-Q": 9, "6-K": 9, "INTERIM_REPORT": 9,
    "REGULATORY_FILING": 8, "8-K": 7, "PRESS_RELEASE": 7,
    "IR_NEWS": 6, "INVESTOR_PRESENTATION": 5, "SLIDES": 5,
    "MARKET_DATA": 4, "OTHER": 1,
}


def _generate_clean_md_from_txt(stem: str, text: str) -> Optional[str]:
    """Generate a .clean.md from plain text by extracting financial sections.

    Uses keyword matching to locate income statement, balance sheet, and cash
    flow sections in the text extracted from a PDF filing.  Returns None if
    no financial sections are found.
    """
    if len(text) < 5000:
        return None

    _SECTION_PATTERNS = [
        ("INCOME STATEMENT", re.compile(
            r"(?i)(consolidated\s+)?(income|profit\s+(?:and|&)\s+loss)\s+statement")),
        ("BALANCE SHEET", re.compile(
            r"(?i)(consolidated\s+)?(balance\s+sheet|statement\s+of\s+financial\s+position)")),
        ("CASH FLOW", re.compile(
            r"(?i)(consolidated\s+)?(cash\s*flow|statement\s+of\s+cash)")),
        ("EQUITY", re.compile(
            r"(?i)(consolidated\s+)?statement\s+of\s+(changes?\s+in\s+)?(shareholders?['\u2019]?\s+)?equity")),
    ]

    sections = []
    for section_name, pattern in _SECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            # Grab context: 200 chars before + up to 30KB after the match
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 30_000)
            chunk = text[start:end]
            sections.append(f"## {section_name}\n\n```\n{chunk}\n```")

    if not sections:
        return None

    header = f"# FINANCIAL STATEMENTS \u2014 {stem}\n\n"
    return header + "\n\n---\n\n".join(sections)


def _clean_md_is_useful_check(path: Path) -> bool:
    """Semantic quality gate for .clean.md files.

    Checks that the file has real financial data (markdown tables with numeric
    rows and at least one valid section), not just stub placeholders.
    """
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return False
    return _clean_md_is_useful_check_text(text)


def _clean_md_is_useful_check_text(text: str) -> bool:
    """Semantic quality gate for .clean.md content (shared implementation)."""
    return _is_clean_md_useful_common(text)


def _txt_content_size(source: Dict[str, Any], repo_root: Path) -> int:
    """Size of the best text companion for a source's local_path.

    For PDFs: checks the .txt companion (same stem).
    For .txt: returns the file size itself.
    Returns 0 on any error or missing path.
    """
    lp = source.get("local_path", "")
    if not lp or not isinstance(lp, str):
        return 0
    p = repo_root / lp
    if p.suffix.lower() == ".txt":
        target = p
    else:
        target = p.with_suffix(".txt")
    try:
        if target.exists():
            content = target.read_text(errors="replace")
            # Placeholder text from sec_fetcher doesn't count
            if content.startswith("[PDF original"):
                return 0
            return len(content)
    except OSError:
        pass
    return 0


def canonical_type_token(source_type: str) -> str:
    token = normalize_type(source_type)
    token = token.replace("/", "-")
    token = token.replace(" ", "_")
    token = token.replace(":", "")
    return re.sub(r"[^A-Z0-9_\-]+", "", token) or "OTHER"


def rename_local_files(raw_dir: Path, old_id: str, new_id: str) -> int:
    renamed = 0
    for path in sorted(raw_dir.glob(f"{old_id}_*")):
        target = path.with_name(path.name.replace(old_id, new_id, 1))
        if target.exists():
            print(f"WARNING: rename skip (target exists): {target.name}", file=sys.stderr)
            continue
        path.rename(target)
        renamed += 1
    return renamed


def _candidate_rank(path: Path) -> Tuple[int, int, str]:
    """Rank candidate files by quality, size, then deterministic filename."""
    suffix = path.suffix.lower()
    name_lower = path.name.lower()
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    if name_lower.endswith(".clean.md"):
        if _clean_md_is_useful_check(path):
            return (400, size, path.name)
        return (50, size, path.name)
    if suffix == ".txt":
        try:
            head = path.read_text(errors="replace")[:120]
        except OSError:
            head = ""
        if head.startswith("[PDF original") or size < 200:
            return (50, size, path.name)
        if size > 5000:
            return (300, size, path.name)
        return (150, size, path.name)
    if suffix in (".htm", ".html"):
        return (150, size, path.name)
    if suffix == ".pdf":
        return (10, size, path.name)
    return (5, size, path.name)


def _choose_best_candidate(matches: List[Path]) -> Path:
    """Choose best file deterministically: quality > size > filename."""
    ordered = sorted(matches, key=_candidate_rank, reverse=True)
    return ordered[0]


def _candidate_debug(matches: List[Path]) -> str:
    """Human-readable candidate ranks for diagnostic logs."""
    parts: List[str] = []
    for p in sorted(matches, key=lambda m: m.name):
        prio, size, _ = _candidate_rank(p)
        parts.append(f"{p.name}:{prio}/{size}")
    return ", ".join(parts)


def _promotion_reason_for_annual_doc(src: Dict[str, Any]) -> Optional[str]:
    src_type = normalize_type(src.get("tipo"))
    if src_type not in {"INVESTOR_PRESENTATION", "SLIDES"}:
        return None
    title = str(src.get("titulo") or "")
    url = str(src.get("url") or "")
    notes = str(src.get("notas") or "")
    local_path = str(src.get("local_path") or "")
    combined = re.sub(r"[-_/]+", " ", f" {title} {url} {notes} {local_path} ".lower())
    hints = (
        " urd ",
        "universal registration document",
        "document d'enregistrement universel",
        "annual report",
        "integrated report",
    )
    for hint in hints:
        if hint in combined:
            return hint.strip()
    return None


def ensure_source_defaults(source: Dict[str, Any], today: str) -> Dict[str, Any]:
    out = dict(source)
    out["tipo"] = normalize_type(out.get("tipo"))
    out["categoria"] = out.get("categoria") or infer_category(out["tipo"])
    out["titulo"] = out.get("titulo") or f"{out['tipo']} source"
    out["url"] = out.get("url") if isinstance(out.get("url"), str) else ""
    out["publicador"] = out.get("publicador") or "UNKNOWN"
    fecha_pub = out.get("fecha_publicacion")
    out["fecha_publicacion"] = str(fecha_pub) if fecha_pub not in (None, "") else None
    if "fecha_publicacion_estimated" in out:
        out["fecha_publicacion_estimated"] = bool(out.get("fecha_publicacion_estimated"))
    else:
        out["fecha_publicacion_estimated"] = out["fecha_publicacion"] is None
    out["fecha_recuperacion"] = out.get("fecha_recuperacion") or today
    out["idioma"] = out.get("idioma") or "en"
    out["fiabilidad"] = out.get("fiabilidad") or "B"
    out["relevancia"] = out.get("relevancia") or "MEDIA"
    out["notas"] = out.get("notas") or "Compilado desde fetchers Step 1."
    if "extractos" not in out or not isinstance(out["extractos"], list):
        out["extractos"] = []
    return out


def build_cobertura(fuentes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    def find_type(types: Iterable[str]) -> Optional[str]:
        target = {t.upper() for t in types}
        for src in fuentes:
            st = normalize_type(src.get("tipo"))
            if st in target:
                return src.get("source_id")
        return None

    annual = find_type(["10-K", "20-F", "40-F", "ANNUAL_REPORT"])
    quarterly = find_type(["10-Q", "6-K", "QUARTERLY_REPORT", "INTERIM_REPORT"])
    earnings = find_type(["8-K", "PRESS_RELEASE", "IR_NEWS"])
    transcript = find_type(["TRANSCRIPT", "EARNINGS_TRANSCRIPT", "CALL_TRANSCRIPT"])
    presentation = find_type(["INVESTOR_PRESENTATION", "SLIDES"])
    proxy = find_type(["DEF14A", "PROXY"])
    debt = find_type(["CREDIT_AGREEMENT", "NOTE_DEBT", "SEC_EXHIBIT"])
    market = find_type(["MARKET_DATA"])

    return {
        "informe_anual": {"encontrado": annual is not None, "source_id": annual, "tipo": "10-K"},
        "informe_trimestral": {"encontrado": quarterly is not None, "source_id": quarterly, "tipo": "10-Q"},
        "earnings_release_mas_reciente": {"encontrado": earnings is not None, "source_id": earnings, "tipo": "8-K"},
        "transcripcion_resultados_mas_reciente": {
            "encontrado": transcript is not None,
            "source_id": transcript,
            "tipo": "TRANSCRIPT",
        },
        "presentacion_inversores_mas_reciente": {
            "encontrado": presentation is not None,
            "source_id": presentation,
            "tipo": "INVESTOR_PRESENTATION",
        },
        "proxy_o_gobierno_corporativo": {"encontrado": proxy is not None, "source_id": proxy, "tipo": "DEF14A"},
        "documento_deuda_o_credit_agreement": {
            "encontrado": debt is not None,
            "source_id": debt,
            "tipo": "CREDIT_AGREEMENT",
        },
        "fuente_precio_y_acciones": {"encontrado": market is not None, "source_id": market, "tipo": "MARKET_DATA"},
    }


def dedupe_faltantes(*arrays: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for arr in arrays:
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("item") or item.get("tipo") or "").strip().lower(),
                str(item.get("como_conseguirlo") or item.get("como_obtenerlo") or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "item": item.get("item") or item.get("tipo") or "dato_faltante",
                    "por_que_importa": item.get("por_que_importa") or item.get("razon") or "Dato relevante para validar tesis.",
                    "como_conseguirlo": item.get("como_conseguirlo")
                    or item.get("como_obtenerlo")
                    or "Revisar filing/IR correspondiente.",
                }
            )
    return out


def build_peticion_truth_pack() -> Dict[str, Any]:
    return {
        "prioridades_extraccion": [
            "ingresos",
            "ebit",
            "net_income",
            "cfo",
            "capex",
            "fcf",
            "caja",
            "deuda_total",
            "acciones_diluidas",
        ],
        "preguntas_clave": [
            "¿Hay tabla de vencimientos 24-36 meses?",
            "¿Qué items distorsionan EBITDA→FCF?",
            "¿Hay SBC o dilución neta relevante?",
        ],
    }


def build_universo_contexto() -> Dict[str, Any]:
    return {
        "mercados_objetivo": ["USA"],
        "liquidez_min_usd_dia": 2_000_000,
        "capitalizacion_min_usd": 300_000_000,
        "capitalizacion_max_usd": 20_000_000_000,
        "exclusiones_no_especulativo": {
            "pre_revenue": True,
            "biotech_clinico": True,
            "tesis_binaria": True,
        },
    }


def compile_sources(ticker: str, case_dir: Path) -> Path:
    today = today_iso()
    dir_name = case_dir.name                           # "2026-02-12_GPT5"
    case_date = dir_name[:10]                           # "2026-02-12"
    modelo_suffix = dir_name[11:] if len(dir_name) > 10 else ""
    case_id = f"CASE_{case_date.replace('-', '')}_{ticker.upper()}"
    if modelo_suffix:
        case_id += f"_{modelo_suffix}"
    # Use ticker-level _raw_filings/ (shared between analyses)
    ticker_dir = case_dir.parent
    raw_dir = ticker_dir / "_raw_filings"
    raw_dir.mkdir(parents=True, exist_ok=True)

    sec = load_json(case_dir / "_sec_fetcher_output.json") or {}
    mkt = load_json(case_dir / "_market_data_output.json") or {}
    tr = load_json(case_dir / "_transcript_finder_output.json") or {}
    mkt_has_sources = isinstance(mkt.get("fuentes"), list) and len(mkt.get("fuentes") or []) > 0
    mkt_empresa = (mkt.get("empresa") or {}) if mkt_has_sources else {}

    if not sec and not mkt and not tr:
        raise RuntimeError("No pre-fetch inputs found.")

    empresa = {
        "ticker": ticker.upper(),
        "nombre": first_non_empty((sec.get("empresa") or {}).get("nombre"), mkt_empresa.get("nombre"), (tr.get("empresa") or {}).get("nombre"), ticker.upper()),
        "bolsa": first_non_empty((sec.get("empresa") or {}).get("bolsa"), mkt_empresa.get("bolsa"), (tr.get("empresa") or {}).get("bolsa"), "UNKNOWN"),
        "pais": first_non_empty((sec.get("empresa") or {}).get("pais"), mkt_empresa.get("pais"), (tr.get("empresa") or {}).get("pais"), "US"),
        "sector": first_non_empty((sec.get("empresa") or {}).get("sector"), mkt_empresa.get("sector"), (tr.get("empresa") or {}).get("sector"), "UNKNOWN"),
        "industria": first_non_empty((sec.get("empresa") or {}).get("industria"), mkt_empresa.get("industria"), (tr.get("empresa") or {}).get("industria"), "UNKNOWN"),
        "web_ir": first_non_empty((sec.get("empresa") or {}).get("web_ir"), mkt_empresa.get("web_ir"), (tr.get("empresa") or {}).get("web_ir")),
    }

    merged: List[Dict[str, Any]] = []
    merged_origin_ids: List[List[str]] = []  # parallel list: all source_ids per merged entry
    seen: Dict[str, int] = {}          # url/accession key → index in merged
    duplicate_count = 0
    for pack in (sec, mkt, tr):
        fuentes = pack.get("fuentes")
        if not isinstance(fuentes, list):
            continue
        for source in fuentes:
            if not isinstance(source, dict):
                continue
            source_type = normalize_type(source.get("tipo"))
            if source_type == "EARNINGS_TRANSCRIPT":
                issuer_match = str(source.get("issuer_match") or "").upper()
                if issuer_match == "MISMATCH":
                    print(
                        f"[sources_compiler] WARNING: dropping transcript "
                        f"{source.get('source_id')} due issuer_match=MISMATCH",
                        file=sys.stderr,
                    )
                    continue
            key = source_key(source)
            # ── URL dedup with quality-aware merge ──
            if key[0] and key[0] in seen:
                existing_idx = seen[key[0]]
                existing = merged[existing_idx]
                new_size = _txt_content_size(source, REPO_ROOT)
                old_size = _txt_content_size(existing, REPO_ROOT)
                upgrading_id = str(source.get("source_id") or "")
                new_local = source.get("local_path")
                old_local = existing.get("local_path")
                should_upgrade = (
                    new_size > old_size * 2
                    and isinstance(new_local, str)
                    and bool(new_local.strip())
                    and new_local != old_local
                )
                if should_upgrade:
                    # New source has substantially better text -> upgrade path.
                    existing["local_path"] = new_local
                    old_prio = _TIPO_PRIORITY.get(normalize_type(existing.get("tipo")), 0)
                    new_prio = _TIPO_PRIORITY.get(normalize_type(source.get("tipo")), 0)
                    if new_prio > old_prio:
                        existing["tipo"] = source["tipo"]
                    # Track upgrading source only when upgrade really happened.
                    if upgrading_id and upgrading_id not in merged_origin_ids[existing_idx]:
                        merged_origin_ids[existing_idx].append(upgrading_id)
                    print(
                        f"[sources_compiler] Dedup merge: upgraded {existing.get('source_id')} "
                        f"local_path ({old_size}B→{new_size}B txt) from {upgrading_id}",
                        file=sys.stderr,
                    )
                else:
                    print(f"WARNING: dedup skip (url): {source.get('source_id')} {source.get('tipo')}", file=sys.stderr)
                duplicate_count += 1
                continue
            if key[1] and key[1] in seen:
                duplicate_count += 1
                print(f"WARNING: dedup skip (accession): {source.get('source_id')} {source.get('tipo')}", file=sys.stderr)
                continue
            idx = len(merged)
            if key[0]:
                seen[key[0]] = idx
            if key[1]:
                seen[key[1]] = idx
            merged.append(ensure_source_defaults(source, today))
            first_id = str(source.get("source_id") or "")
            merged_origin_ids.append([first_id] if first_id else [])

    # Optional dedupe by content hash to avoid processing duplicated documents.
    if merged:
        dedup_sources: List[Dict[str, Any]] = []
        dedup_origin_ids: List[List[str]] = []
        hash_index: Dict[str, int] = {}
        hash_duplicate_count = 0

        for src, origin_ids in zip(merged, merged_origin_ids):
            chash = _normalized_content_hash(src)
            if not chash:
                dedup_sources.append(src)
                dedup_origin_ids.append(list(origin_ids))
                continue

            existing_idx = hash_index.get(chash)
            if existing_idx is None:
                hash_index[chash] = len(dedup_sources)
                dedup_sources.append(src)
                dedup_origin_ids.append(list(origin_ids))
                continue

            hash_duplicate_count += 1
            existing = dedup_sources[existing_idx]
            if _prefer_source_for_hash(existing, src):
                print(
                    "[sources_compiler] Dedup content_hash: replacing "
                    f"{existing.get('source_id')} with {src.get('source_id')}",
                    file=sys.stderr,
                )
                merged_ids = dedup_origin_ids[existing_idx]
                for oid in list(origin_ids) + [str(existing.get("source_id") or "")]:
                    if oid and oid not in merged_ids:
                        merged_ids.append(oid)
                dedup_sources[existing_idx] = src
            else:
                print(
                    "[sources_compiler] Dedup content_hash: dropping "
                    f"{src.get('source_id')} (kept {existing.get('source_id')})",
                    file=sys.stderr,
                )
                merged_ids = dedup_origin_ids[existing_idx]
                for oid in origin_ids:
                    if oid and oid not in merged_ids:
                        merged_ids.append(oid)

        if hash_duplicate_count:
            duplicate_count += hash_duplicate_count
        merged = dedup_sources
        merged_origin_ids = dedup_origin_ids

    no_sources = len(merged) == 0
    if no_sources:
        print(
            "[sources_compiler] WARNING: No sources found in pre-fetch inputs; generating empty SourcesPack.",
            file=sys.stderr,
        )

    renamed_files = 0
    sec_count = 0
    market_count = 0
    transcript_count = 0
    presentation_count = 0
    promotion_notes: List[str] = []
    final_sources: List[Dict[str, Any]] = []
    for idx, src in enumerate(merged, start=1):
        old_id = str(src.get("source_id") or "")
        new_id = f"SRC_{idx:03d}"
        src["source_id"] = new_id

        src_type = normalize_type(src.get("tipo"))
        promotion_reason = _promotion_reason_for_annual_doc(src)
        if promotion_reason:
            src["tipo"] = "ANNUAL_REPORT"
            src_type = "ANNUAL_REPORT"
            promotion_notes.append(
                f"[sources_compiler] promotion_reason: {new_id} INVESTOR_PRESENTATION -> ANNUAL_REPORT ({promotion_reason})"
            )
        if src_type == "MARKET_DATA":
            market_count += 1
        elif "TRANSCRIPT" in src_type:
            transcript_count += 1
        elif src_type in {"INVESTOR_PRESENTATION", "SLIDES"}:
            presentation_count += 1
        elif src_type in {"10-K", "10-Q", "20-F", "6-K", "8-K", "DEF14A", "SEC_EXHIBIT", "CREDIT_AGREEMENT",
                         "ANNUAL_REPORT", "INTERIM_REPORT", "REGULATORY_FILING"}:
            sec_count += 1

        local_path = src.get("local_path")
        if isinstance(local_path, str) and local_path.strip():
            # Rename files for ALL origin IDs (not just old_id).
            # When dedup upgrades local_path from SRC_SEC_002 to SRC_PR_002's
            # file, both IDs must be renamed so the resolution phase can find
            # all candidate files under the new_id prefix.
            all_origin_ids = list(dict.fromkeys(merged_origin_ids[idx - 1] + ([old_id] if old_id else [])))  # 0-based
            for origin_id in all_origin_ids:
                if origin_id:
                    renamed_files += rename_local_files(raw_dir, origin_id, new_id)

            # Compute repo-root-relative prefix for local_path
            try:
                raw_rel = str(raw_dir.relative_to(REPO_ROOT))
            except ValueError:
                raw_rel = "_raw_filings"
            # Force canonical path for downstream readers.
            # Priority: .clean.md > .txt > .htm (best quality first)
            token = canonical_type_token(src_type)
            # Try multiple candidate names — the actual filename may include
            # a period suffix (e.g., SRC_001_20-F_FY2025.txt) that the
            # canonical_name template omits.
            resolved_path = None
            for ext_candidate in (".clean.md", ".txt", ".htm", ".html"):
                exact = f"{new_id}_{token}{ext_candidate}"
                candidate_path = raw_dir / exact
                if candidate_path.exists():
                    # Skip .clean.md that fails semantic quality gate
                    if ext_candidate == ".clean.md" and not _clean_md_is_useful_check(candidate_path):
                        continue
                    resolved_path = f"{raw_rel}/{exact}"
                    break
                # Glob fallback for period-suffix variants
                pattern = f"{new_id}_{token}*{ext_candidate}"
                glob_matches = sorted(raw_dir.glob(pattern))
                if glob_matches:
                    gm = _choose_best_candidate(glob_matches)
                    print(
                        f"[sources_compiler] Token resolve {new_id} ({ext_candidate}) "
                        f"picked {gm.name} from {len(glob_matches)} candidates: {_candidate_debug(glob_matches)}",
                        file=sys.stderr,
                    )
                    if ext_candidate == ".clean.md" and not _clean_md_is_useful_check(gm):
                        continue
                    resolved_path = f"{raw_rel}/{gm.name}"
                    break

            if resolved_path:
                src["local_path"] = resolved_path
            else:
                # Fallback: choose best candidate by quality scoring, not
                # first alphabetical match (which often picks .pdf over .txt).
                matches = sorted(raw_dir.glob(f"{new_id}_*"))
                if matches:
                    best = _choose_best_candidate(matches)
                    src["local_path"] = f"{raw_rel}/{best.name}"
                    print(
                        f"[sources_compiler] Fallback file selection for {new_id}: "
                        f"{best.name} (from {len(matches)} candidates: {_candidate_debug(matches)})",
                        file=sys.stderr,
                    )
                else:
                    # Keep existing local_path if file wasn't found
                    print(f"WARNING: no local file found for {new_id} ({src_type}), keeping: {local_path}", file=sys.stderr)
                    src["local_path"] = local_path

        final_sources.append(src)

    # ── Fix D: self-heal .clean.md with unified pipeline (HTML/PDF/TXT) ──
    _clean_md_generated = 0

    def _pick_primary_source(txt_path: Path, current_path: Path) -> Optional[Path]:
        candidates: List[Path] = []
        for ext in (".htm", ".html", ".pdf"):
            candidates.append(txt_path.with_suffix(ext))
        current_ext = current_path.suffix.lower()
        if current_ext in {".htm", ".html", ".pdf"}:
            candidates.append(current_path)
        if txt_path.exists():
            candidates.append(txt_path)
        seen: set[str] = set()
        for cand in candidates:
            key = str(cand)
            if key in seen:
                continue
            seen.add(key)
            if cand.exists():
                return cand
        return None

    def _try_regen_clean(primary_path: Path, clean_path: Path, src_ref: Dict[str, Any]) -> bool:
        nonlocal _clean_md_generated
        txt_companion = primary_path if primary_path.suffix.lower() == ".txt" else primary_path.with_suffix(".txt")
        txt_content = ""
        if txt_companion.exists():
            txt_content = txt_companion.read_text(errors="replace")
        clean_text, clean_meta = _generate_clean_md_unified(
            source_path=primary_path,
            txt_content=txt_content,
            filing_type=str(src_ref.get("tipo", src_ref.get("form_type", "UNKNOWN"))),
            source_id=str(src_ref.get("source_id", "UNKNOWN")),
        )
        if not clean_text:
            reason = str(clean_meta.get("reason") or "LOW_QUALITY")
            print(
                f"[sources_compiler] clean.md regeneration rejected {clean_path.name}: {reason}",
                file=sys.stderr,
            )
            return False
        try:
            clean_path.write_text(clean_text, encoding="utf-8")
        except Exception as exc:
            print(
                f"[sources_compiler] WARNING: cannot write regenerated clean.md ({clean_path.name}): {exc}",
                file=sys.stderr,
            )
            return False
        _clean_md_generated += 1
        try:
            new_rel = str(clean_path.relative_to(REPO_ROOT))
        except ValueError:
            pass
        else:
            src_ref["local_path"] = new_rel
        mode = str(clean_meta.get("mode") or "unknown")
        print(f"[sources_compiler] Regenerated .clean.md ({mode}): {clean_path.name}", file=sys.stderr)
        return True

    for src in final_sources:
        lp = src.get("local_path", "")
        if not lp:
            continue
        p = REPO_ROOT / lp
        if p.name.endswith(".clean.md"):
            txt_p = p.with_name(p.name[:-9] + ".txt")
        elif p.suffix.lower() == ".txt":
            txt_p = p
        else:
            txt_p = p.with_suffix(".txt")
        clean_p = txt_p.with_suffix(".clean.md")
        primary_path = _pick_primary_source(txt_p, p)

        # Existing clean.md: keep if useful; otherwise remove and self-heal.
        if clean_p.exists():
            if _clean_md_is_useful_check(clean_p):
                continue
            try:
                clean_p.unlink()
                print(f"[sources_compiler] Removed low-quality .clean.md: {clean_p.name}", file=sys.stderr)
            except OSError as exc:
                print(
                    f"[sources_compiler] WARNING: cannot remove low-quality .clean.md ({clean_p.name}): {exc}",
                    file=sys.stderr,
                )
                continue

        # Primary regeneration first (HTML/PDF preferred over TXT).
        if not clean_p.exists() and primary_path is not None:
            if _try_regen_clean(primary_path, clean_p, src):
                continue

        # Last-resort TXT regeneration only when primary path failed or missing.
        if clean_p.exists():
            continue
        if txt_p.exists() and txt_p.stat().st_size >= 5000:
            if _try_regen_clean(txt_p, clean_p, src):
                continue

    if _clean_md_generated:
        print(f"[sources_compiler] Total .clean.md generated: {_clean_md_generated}", file=sys.stderr)

    cobertura = build_cobertura(final_sources)
    faltantes = dedupe_faltantes(sec.get("faltantes"), mkt.get("faltantes"), tr.get("faltantes"))
    log_limitaciones = []
    log_observaciones = []
    for pack in (sec, mkt, tr):
        log = pack.get("log")
        if isinstance(log, dict):
            if isinstance(log.get("limitaciones"), list):
                log_limitaciones.extend(x for x in log["limitaciones"] if isinstance(x, str))
            if isinstance(log.get("observaciones"), list):
                log_observaciones.extend(x for x in log["observaciones"] if isinstance(x, str))
    if promotion_notes:
        log_limitaciones.extend(promotion_notes)
    if no_sources:
        log_limitaciones.append(
            "No sources available in PREFETCH outputs; generated empty SourcesPack and continued."
        )
        faltantes.append({
            "item": "sources_empty",
            "por_que_importa": "All 3 fetchers returned 0 sources — pipeline will fail at TRUTH_PACK (TP_EXTRACTOR_FILING).",
            "como_conseguirlo": "Provide --exchange, --country, and/or --web-ir hints for non-US companies, or verify ticker exists in SEC EDGAR.",
        })

    compiled = {
        "version_esquema": "SourcesPack_v1",
        "caso_id": case_id,
        "fecha_corte": case_date,
        "empresa": empresa,
        "universo_contexto": build_universo_contexto(),
        "cobertura_documental": cobertura,
        "fuentes": final_sources,
        "faltantes": faltantes,
        "peticion_para_truth_pack": build_peticion_truth_pack(),
        "log": {
            "limitaciones": log_limitaciones[:20],
            "observaciones": log_observaciones[:20],
        },
        "cache_stats": {
            "archivos_descargados": len(list(raw_dir.glob("*"))),
            "archivos_fallidos": 0,
            "directorio": str(raw_dir.relative_to(REPO_ROOT)) if raw_dir.is_relative_to(REPO_ROOT) else "_raw_filings/",
            "archivos_renombrados": renamed_files,
        },
        "_meta": {
            "compilado_por": "SOURCES_COMPILER_V2",
            "timestamp_compilacion": utc_now_iso(),
            "fuentes_consolidadas": {
                "sec_filings": sec_count,
                "market_data": market_count,
                "transcripts": transcript_count,
                "presentations": presentation_count,
                "total": len(final_sources),
            },
            "duplicados_eliminados": duplicate_count,
            "version_esquema": "SourcesPack_v1",
        },
    }

    suffix = f"_{modelo_suffix}" if modelo_suffix else ""
    out_path = case_dir / f"SourcesPack_v1_{ticker.upper()}_{case_date}{suffix}.json"
    out_path.write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile Step-1 partial outputs into SourcesPack_v1")
    parser.add_argument("ticker", help="Ticker symbol, e.g., SIG")
    parser.add_argument("case_dir", help="Case directory, e.g., casos/SIG/2026-02-09")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_path = compile_sources(args.ticker, Path(args.case_dir))
    print(json.dumps({"ok": True, "output": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
