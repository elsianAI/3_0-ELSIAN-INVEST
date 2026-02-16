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
    if st in {"10-K", "10-Q", "20-F", "6-K", "8-K", "DEF14A", "SEC_EXHIBIT", "CREDIT_AGREEMENT"}:
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


def ensure_source_defaults(source: Dict[str, Any], today: str) -> Dict[str, Any]:
    out = dict(source)
    out["tipo"] = normalize_type(out.get("tipo"))
    out["categoria"] = out.get("categoria") or infer_category(out["tipo"])
    out["titulo"] = out.get("titulo") or f"{out['tipo']} source"
    out["url"] = out.get("url") if isinstance(out.get("url"), str) else ""
    out["publicador"] = out.get("publicador") or "UNKNOWN"
    out["fecha_publicacion"] = out.get("fecha_publicacion") or today
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
    quarterly = find_type(["10-Q", "6-K", "QUARTERLY_REPORT"])
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

    if not sec and not mkt and not tr:
        raise RuntimeError("No pre-fetch inputs found.")

    empresa = {
        "ticker": ticker.upper(),
        "nombre": first_non_empty((sec.get("empresa") or {}).get("nombre"), (mkt.get("empresa") or {}).get("nombre"), (tr.get("empresa") or {}).get("nombre"), ticker.upper()),
        "bolsa": first_non_empty((sec.get("empresa") or {}).get("bolsa"), (mkt.get("empresa") or {}).get("bolsa"), (tr.get("empresa") or {}).get("bolsa"), "UNKNOWN"),
        "pais": first_non_empty((sec.get("empresa") or {}).get("pais"), (mkt.get("empresa") or {}).get("pais"), (tr.get("empresa") or {}).get("pais"), "US"),
        "sector": first_non_empty((sec.get("empresa") or {}).get("sector"), (mkt.get("empresa") or {}).get("sector"), (tr.get("empresa") or {}).get("sector"), "UNKNOWN"),
        "industria": first_non_empty((sec.get("empresa") or {}).get("industria"), (mkt.get("empresa") or {}).get("industria"), (tr.get("empresa") or {}).get("industria"), "UNKNOWN"),
        "web_ir": first_non_empty((sec.get("empresa") or {}).get("web_ir"), (mkt.get("empresa") or {}).get("web_ir"), (tr.get("empresa") or {}).get("web_ir")),
    }

    merged: List[Dict[str, Any]] = []
    seen = set()
    duplicate_count = 0
    for pack in (sec, mkt, tr):
        fuentes = pack.get("fuentes")
        if not isinstance(fuentes, list):
            continue
        for source in fuentes:
            if not isinstance(source, dict):
                continue
            key = source_key(source)
            if key[0] and key[0] in seen:
                duplicate_count += 1
                print(f"WARNING: dedup skip (url): {source.get('source_id')} {source.get('tipo')}", file=sys.stderr)
                continue
            if key[1] and key[1] in seen:
                duplicate_count += 1
                print(f"WARNING: dedup skip (accession): {source.get('source_id')} {source.get('tipo')}", file=sys.stderr)
                continue
            if key[0]:
                seen.add(key[0])
            if key[1]:
                seen.add(key[1])
            merged.append(ensure_source_defaults(source, today))

    if not merged:
        raise RuntimeError("No sources found in pre-fetch inputs.")

    renamed_files = 0
    sec_count = 0
    market_count = 0
    transcript_count = 0
    presentation_count = 0
    final_sources: List[Dict[str, Any]] = []
    for idx, src in enumerate(merged, start=1):
        old_id = str(src.get("source_id") or "")
        new_id = f"SRC_{idx:03d}"
        src["source_id"] = new_id

        src_type = normalize_type(src.get("tipo"))
        if src_type == "MARKET_DATA":
            market_count += 1
        elif "TRANSCRIPT" in src_type:
            transcript_count += 1
        elif src_type in {"INVESTOR_PRESENTATION", "SLIDES"}:
            presentation_count += 1
        elif src_type in {"10-K", "10-Q", "20-F", "6-K", "8-K", "DEF14A", "SEC_EXHIBIT", "CREDIT_AGREEMENT"}:
            sec_count += 1

        local_path = src.get("local_path")
        if isinstance(local_path, str) and local_path.strip():
            renamed_files += rename_local_files(raw_dir, old_id, new_id)
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
            def _clean_md_is_useful_check(path: Path) -> bool:
                """Semantic quality gate for .clean.md files (duplicated to avoid cross-layer import)."""
                try:
                    text = path.read_text(errors="replace")
                except Exception:
                    return False
                if text.count("_Section not found in filing._") >= 4:
                    return False
                import re as _re
                numeric_rows = _re.findall(r"^\|.*\d[\d,\.]*.*\|$", text, _re.MULTILINE)
                if len(numeric_rows) < 5:
                    return False
                for section in ("INCOME STATEMENT", "BALANCE SHEET", "CASH FLOW"):
                    idx = text.find(f"## {section}")
                    if idx >= 0 and "_Section not found" not in text[idx:idx + 200]:
                        return True
                return False

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
                    gm = glob_matches[0]
                    if ext_candidate == ".clean.md" and not _clean_md_is_useful_check(gm):
                        continue
                    resolved_path = f"{raw_rel}/{gm.name}"
                    break

            if resolved_path:
                src["local_path"] = resolved_path
            else:
                # Fallback to best candidate file with the new id.
                matches = sorted(raw_dir.glob(f"{new_id}_*"))
                if matches:
                    src["local_path"] = f"{raw_rel}/{matches[0].name}"
                else:
                    # Keep existing local_path if file wasn't found
                    print(f"WARNING: no local file found for {new_id} ({src_type}), keeping: {local_path}", file=sys.stderr)
                    src["local_path"] = local_path

        final_sources.append(src)

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

