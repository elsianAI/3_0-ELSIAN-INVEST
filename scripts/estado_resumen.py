#!/usr/bin/env python3
"""
estado_resumen.py - Resumen compacto del estado del repositorio ELSIAN INVEST.

Propósito: Reemplazar la carga completa de ESTADO_REPO.json + MasterCandidateList.json
en el boot del agente. Produce un resumen de ~15-20 líneas con las 6 métricas clave.

Métricas extraídas:
  1. Casos por estado_pipeline (COMPLETO, INCOMPLETO, SUPERSEDED, otros)
  2. Monitors vencidos (proxima_revision < hoy)
  3. Último SCOUT (fecha + versión)
  4. Último SCANNER (fecha + hallazgos pendientes FILTRADOS por anti-duplicado)
  5. Urgencias pendientes (con filtro anti-duplicado aplicado)
  6. Candidatos con estado pendiente_evaluacion (conteo)
  7. Trabajo huérfano en filesystem (dirs en casos/ sin _estado.json válido)
  8. Inventario de fuentes/filings (parseo de pre-fetch JSONs y SourcesPacks)

Regla anti-duplicado (ENTRY_POINT.md):
  Un hallazgo URGENT con accion_recomendada=MONITOR se considera RESUELTO si ya
  existe MonitoringUpdate del mismo ticker con fecha_corte >= fecha_scan.

Degradación paranoica: .get() + isinstance() en cada campo.
Funciona con ESTADO_REPO.json = {} sin error (devuelve 0 / N/D).

Uso:
  python3 scripts/estado_resumen.py
  python3 scripts/estado_resumen.py --json   # Salida JSON compacta

Versión: 1.5.1 (2026-02-13) — Fix: casos incompletos registrados en ACCIÓN REQUERIDA; orphans PIPELINE_INICIAL/PARCIAL en "Lanzar pipeline".
Versión: 1.5 (2026-02-13) — Dashboard compacto orientado a acciones. Elimina redundancia entre secciones.
Versión: 1.4 (2026-02-13) — Inventario de fuentes/filings en boot (parseo de pre-fetch JSONs y SourcesPacks).
Versión: 1.3 (2026-02-13) — Migración a _estado.json por caso. Lee estado desde casos/{T}/{D}_{M}/_estado.json.
Versión: 1.2 (2026-02-13) — Añadido escaneo de filesystem para trabajo huérfano.
Versión: 1.1 (2026-02-12) — Añadido filtro anti-duplicado en urgencias.
"""

import json
import re
import sys
import os
from datetime import datetime, date


def load_json(path):
    """Carga un archivo JSON con degradación paranoica."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return {}


def get_repo_root():
    """Detecta la raíz del repo relativa al script."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(script_dir)


def count_cases_by_estado(casos):
    """Cuenta casos por estado_pipeline."""
    conteo = {}
    if not isinstance(casos, list):
        return conteo
    for caso in casos:
        if not isinstance(caso, dict):
            continue
        estado = caso.get("estado_pipeline")
        if not isinstance(estado, str):
            estado = "DESCONOCIDO"
        conteo[estado] = conteo.get(estado, 0) + 1
    return conteo


def get_tickers_by_estado(casos, estado_target):
    """Devuelve lista de tickers para un estado_pipeline dado."""
    tickers = []
    if not isinstance(casos, list):
        return tickers
    for caso in casos:
        if not isinstance(caso, dict):
            continue
        if caso.get("estado_pipeline") == estado_target:
            ticker = caso.get("ticker", "?")
            tickers.append(ticker if isinstance(ticker, str) else "?")
    return tickers


def get_incompletos_detalle(casos):
    """Devuelve detalle de casos incompletos: ticker + next_step."""
    detalles = []
    if not isinstance(casos, list):
        return detalles
    for caso in casos:
        if not isinstance(caso, dict):
            continue
        if caso.get("estado_pipeline") == "INCOMPLETO":
            ticker = caso.get("ticker", "?")
            if not isinstance(ticker, str):
                ticker = "?"
            next_step = caso.get("next_step", "?")
            if not isinstance(next_step, str):
                next_step = "?"
            detalles.append(f"{ticker} (next: {next_step})")
    return detalles


def get_quarantine_detalle(casos):
    """Devuelve detalle de casos en cuarentena: ticker, fecha, auditoría."""
    detalles = []
    if not isinstance(casos, list):
        return detalles
    for caso in casos:
        if not isinstance(caso, dict):
            continue
        if caso.get("estado_pipeline") != "QUARANTINE":
            continue
        ticker = caso.get("ticker", "?")
        if not isinstance(ticker, str):
            ticker = "?"
        fecha = caso.get("fecha_caso", "?")
        if not isinstance(fecha, str):
            fecha = "?"
        next_step = caso.get("next_step", "?")
        if not isinstance(next_step, str):
            next_step = "?"
        score = caso.get("score")
        if not isinstance(score, (int, float)):
            score = None
        decision = caso.get("decision")
        if not isinstance(decision, str):
            decision = None
        # Buscar último bloque auditoria_YYYY_MM_DD
        veredicto, motivo, accion_audit = "?", "?", "?"
        for key in sorted(caso):
            if isinstance(key, str) and key.startswith("auditoria_"):
                bloque = caso.get(key)
                if isinstance(bloque, dict):
                    veredicto = bloque.get("veredicto", "?")
                    if not isinstance(veredicto, str):
                        veredicto = "?"
                    motivo = bloque.get("motivo", "?")
                    if not isinstance(motivo, str):
                        motivo = "?"
                    accion_audit = bloque.get("accion", "?")
                    if not isinstance(accion_audit, str):
                        accion_audit = "?"
        detalles.append({
            "ticker": ticker,
            "fecha": fecha,
            "next_step": next_step,
            "score": score,
            "decision": decision,
            "veredicto": veredicto,
            "motivo": motivo,
            "accion": accion_audit,
        })
    return detalles


def get_monitors_vencidos(casos, hoy):
    """Devuelve lista de tickers con proxima_revision < hoy."""
    vencidos = []
    if not isinstance(casos, list):
        return vencidos
    for caso in casos:
        if not isinstance(caso, dict):
            continue
        if caso.get("estado_pipeline") != "COMPLETO":
            continue
        prox = caso.get("proxima_revision")
        if not isinstance(prox, str):
            continue
        try:
            fecha_rev = date.fromisoformat(prox)
            if fecha_rev < hoy:
                ticker = caso.get("ticker", "?")
                if not isinstance(ticker, str):
                    ticker = "?"
                vencidos.append(f"{ticker} (vence {prox})")
        except (ValueError, TypeError):
            continue
    return vencidos


def get_scout_info(scout):
    """Extrae info del último SCOUT."""
    if not isinstance(scout, dict):
        return {"fecha": "N/D", "version": "N/D"}
    fecha = scout.get("ultima_ejecucion")
    if not isinstance(fecha, str):
        fecha = "N/D"
    version = scout.get("version")
    if not isinstance(version, str):
        version = "N/D"
    return {"fecha": fecha, "version": version}


def get_scanner_info(scanner):
    """Extrae info del último SCANNER."""
    if not isinstance(scanner, dict):
        return {"fecha": "N/D", "hallazgos_pendientes": 0, "ultimo_reporte": None}
    fecha = scanner.get("ultima_ejecucion")
    if not isinstance(fecha, str):
        fecha = "N/D"
    hallazgos = scanner.get("hallazgos_pendientes")
    if not isinstance(hallazgos, int):
        hallazgos = 0
    reporte = scanner.get("ultimo_reporte")
    if not isinstance(reporte, str):
        reporte = None
    return {"fecha": fecha, "hallazgos_pendientes": hallazgos, "ultimo_reporte": reporte}


def get_max_fecha_corte_monitoring(casos, repo_root):
    """Construye mapas {caso_id: max(fecha_corte)} y {ticker: max(fecha_corte)}.

    Cruza MonitoringUpdates de cada caso para extraer fecha_corte.
    Devuelve (por_caso_id, por_ticker) para anti-duplicado preciso por caso
    con fallback por ticker si el hallazgo no tiene caso_id_existente.
    """
    por_caso = {}
    por_ticker = {}
    if not isinstance(casos, list):
        return por_caso, por_ticker
    for caso in casos:
        if not isinstance(caso, dict):
            continue
        caso_id = caso.get("caso_id")
        ticker = caso.get("ticker")
        directorio = caso.get("directorio")
        if not isinstance(directorio, str):
            continue
        monitoring = caso.get("monitoring", [])
        if not isinstance(monitoring, list):
            continue
        for mon_file in monitoring:
            if not isinstance(mon_file, str):
                continue
            mon_path = os.path.join(repo_root, directorio, mon_file)
            mon_data = load_json(mon_path)
            fc = mon_data.get("fecha_corte")
            if not isinstance(fc, str):
                continue
            try:
                fc_date = date.fromisoformat(fc)
                # Mapa por caso_id (preciso)
                if isinstance(caso_id, str):
                    if caso_id not in por_caso or fc_date > por_caso[caso_id]:
                        por_caso[caso_id] = fc_date
                # Mapa por ticker (fallback)
                if isinstance(ticker, str):
                    if ticker not in por_ticker or fc_date > por_ticker[ticker]:
                        por_ticker[ticker] = fc_date
            except (ValueError, TypeError):
                continue
    return por_caso, por_ticker


def filtrar_urgencias_anti_duplicado(repo_root, scanner_info, casos):
    """Aplica regla anti-duplicado de ENTRY_POINT.md sobre hallazgos URGENT.

    Regla: Un hallazgo URGENT con accion_recomendada=MONITOR se considera
    RESUELTO si ya existe MonitoringUpdate del mismo caso/ticker con
    fecha_corte >= fecha_scan del ScannerReport.

    Cruza por caso_id_existente (preciso). Fallback por ticker si el
    hallazgo no tiene caso_id_existente.

    Returns dict con:
      - urgencias_raw: int (total URGENT sin filtrar)
      - urgencias_pendientes: int (URGENT tras filtro)
      - urgencias_resueltas: list[str] (tickers resueltos)
      - urgencias_pendientes_detalle: list[dict] (ticker + tipo_evento)
    """
    resultado = {
        "urgencias_raw": 0,
        "urgencias_pendientes": 0,
        "urgencias_resueltas": [],
        "urgencias_pendientes_detalle": [],
    }

    # Cargar ScannerReport
    reporte_path = scanner_info.get("ultimo_reporte")
    if not reporte_path:
        resultado["urgencias_raw"] = scanner_info.get("hallazgos_pendientes", 0)
        resultado["urgencias_pendientes"] = resultado["urgencias_raw"]
        return resultado

    scanner_data = load_json(os.path.join(repo_root, reporte_path))
    fecha_scan_str = scanner_data.get("fecha_scan")
    hallazgos = scanner_data.get("hallazgos", [])
    if not isinstance(hallazgos, list):
        resultado["urgencias_raw"] = scanner_info.get("hallazgos_pendientes", 0)
        resultado["urgencias_pendientes"] = resultado["urgencias_raw"]
        return resultado

    # Parsear fecha_scan
    try:
        fecha_scan = date.fromisoformat(fecha_scan_str) if isinstance(fecha_scan_str, str) else None
    except (ValueError, TypeError):
        fecha_scan = None

    # Obtener max fecha_corte por caso_id y por ticker (fallback)
    fc_por_caso, fc_por_ticker = get_max_fecha_corte_monitoring(casos, repo_root)

    # Filtrar hallazgos URGENT
    urgentes = [h for h in hallazgos if isinstance(h, dict) and h.get("clasificacion") == "URGENT"]
    resultado["urgencias_raw"] = len(urgentes)

    for h in urgentes:
        ticker = h.get("ticker", "?")
        accion = h.get("accion_recomendada")
        tipo = h.get("tipo_evento", "?")
        caso_id = h.get("caso_id_existente")
        descripcion = h.get("descripcion", "")
        if not isinstance(descripcion, str):
            descripcion = ""

        # Regla anti-duplicado: solo aplica si accion=MONITOR y tenemos fecha_scan
        resuelto = False
        if accion == "MONITOR" and fecha_scan:
            # Primero: cruce preciso por caso_id_existente
            if isinstance(caso_id, str) and caso_id in fc_por_caso:
                if fc_por_caso[caso_id] >= fecha_scan:
                    resuelto = True
            # Fallback: cruce por ticker (si no hay caso_id_existente)
            elif not isinstance(caso_id, str) and isinstance(ticker, str):
                fc = fc_por_ticker.get(ticker)
                if fc and fc >= fecha_scan:
                    resuelto = True

        if resuelto:
            resultado["urgencias_resueltas"].append(ticker)
        else:
            resultado["urgencias_pendientes"] += 1
            resultado["urgencias_pendientes_detalle"].append({
                "ticker": ticker,
                "tipo_evento": tipo,
                "accion": accion if isinstance(accion, str) else "?",
                "descripcion": descripcion,
            })

    return resultado


def count_candidatos_pendientes(mcl_data):
    """Cuenta candidatos con estado == 'pendiente_evaluacion' directamente desde el array."""
    candidatos = mcl_data.get("candidatos")
    if not isinstance(candidatos, list):
        return 0
    count = 0
    for c in candidatos:
        if not isinstance(c, dict):
            continue
        if c.get("estado") == "pendiente_evaluacion":
            count += 1
    return count


def get_candidatos_por_tier(mcl_data):
    """Desglosa candidatos por tier (A, B, C), excluyendo pipeline_completo.

    Solo muestra candidatos pendientes de acción (pendiente_evaluacion,
    en_pipeline, en_watchlist). Los pipeline_completo ya están en la
    sección de casos y no necesitan atención como candidatos.

    Returns dict con:
      - total: int (todos los candidatos en MCL)
      - completados: int (pipeline_completo, excluidos del desglose)
      - pendientes_evaluacion: int
      - en_pipeline: int
      - por_tier: {tier: [{"ticker", "score", "estado"}]}
    """
    resultado = {
        "total": 0, "completados": 0, "pendientes_evaluacion": 0,
        "en_pipeline": 0, "por_tier": {},
    }
    candidatos = mcl_data.get("candidatos")
    if not isinstance(candidatos, list):
        return resultado

    resultado["total"] = len(candidatos)

    for c in candidatos:
        if not isinstance(c, dict):
            continue
        tier = c.get("tier")
        if not isinstance(tier, str):
            tier = "?"
        ticker = c.get("ticker", "?")
        if not isinstance(ticker, str):
            ticker = "?"
        score = c.get("score_interes")
        if not isinstance(score, (int, float)):
            score = None
        estado = c.get("estado", "?")
        if not isinstance(estado, str):
            estado = "?"

        if estado == "pipeline_completo":
            resultado["completados"] += 1
            continue  # No incluir en desglose por tier

        if estado == "pendiente_evaluacion":
            resultado["pendientes_evaluacion"] += 1
        elif estado == "en_pipeline":
            resultado["en_pipeline"] += 1

        if tier not in resultado["por_tier"]:
            resultado["por_tier"][tier] = []
        resultado["por_tier"][tier].append({
            "ticker": ticker,
            "score": score,
            "estado": estado,
        })

    return resultado


def scan_casos_directory(repo_root):
    """Escanea casos/ y devuelve {ticker: [date_dirs]} encontrados en disco.

    Excluye directorios que empiezan con _ (ej. _TEMPLATE).
    Solo incluye subdirectorios con formato de fecha ISO (YYYY-MM-DD).
    Degradación paranoica: nunca crashea.
    """
    resultado = {}
    casos_dir = os.path.join(repo_root, "casos")
    try:
        entries = os.listdir(casos_dir)
    except (OSError, PermissionError):
        return resultado

    for ticker_dir in entries:
        if not isinstance(ticker_dir, str) or ticker_dir.startswith("_"):
            continue
        ticker_path = os.path.join(casos_dir, ticker_dir)
        if not os.path.isdir(ticker_path):
            continue

        date_dirs = []
        try:
            sub_entries = os.listdir(ticker_path)
        except (OSError, PermissionError):
            continue
        for sub in sub_entries:
            if not isinstance(sub, str) or len(sub) < 10:
                continue
            try:
                date.fromisoformat(sub[:10])
                sub_path = os.path.join(ticker_path, sub)
                if os.path.isdir(sub_path):
                    date_dirs.append(sub)
            except (ValueError, TypeError):
                continue

        if date_dirs:
            resultado[ticker_dir] = sorted(date_dirs)

    return resultado


def load_all_case_states(repo_root):
    """Agrega _estado.json de todos los directorios de caso.

    Escanea casos/{T}/{D}_{M}/_estado.json usando scan_casos_directory().
    Retorna (casos_list, dirs_sin_estado) donde:
    - casos_list: lista de dicts (formato idéntico al antiguo casos[])
    - dirs_sin_estado: lista de (ticker, date_dir) sin _estado.json válido
    Degradación paranoica: nunca crashea.
    """
    disk = scan_casos_directory(repo_root)
    casos = []
    sin_estado = []
    for ticker, date_dirs in sorted(disk.items()):
        for dd in date_dirs:
            estado_path = os.path.join(repo_root, "casos", ticker, dd, "_estado.json")
            data = load_json(estado_path)
            if isinstance(data, dict) and data.get("version_esquema") == "caso_estado_v1":
                casos.append(data)
            else:
                sin_estado.append((ticker, dd))
    return casos, sin_estado


def classify_directory_work(dir_path):
    """Clasifica el trabajo existente en un directorio de caso.

    Solo usa os.path.exists y os.listdir — NO lee contenido de archivos.
    Retorna dict con clasificación y acción sugerida.
    """
    resultado = {
        "prefetch_outputs": [],
        "has_raw_filings": False,
        "raw_filings_count": 0,
        "pipeline_artifacts": [],
        "has_decision_packet": False,
        "classification": "DESCONOCIDO",
        "suggested_action": "",
    }

    try:
        entries = os.listdir(dir_path)
    except (OSError, PermissionError):
        return resultado

    entries_set = set(entries)

    # 1. Detectar outputs de pre-fetch (sub-agentes)
    prefetch_files = [
        "_sec_fetcher_output.json",
        "_market_data_output.json",
        "_transcript_finder_output.json",
    ]
    for pf in prefetch_files:
        if pf in entries_set:
            resultado["prefetch_outputs"].append(pf)

    # 2. Detectar _raw_filings
    raw_path = os.path.join(dir_path, "_raw_filings")
    if os.path.isdir(raw_path):
        resultado["has_raw_filings"] = True
        try:
            resultado["raw_filings_count"] = len(os.listdir(raw_path))
        except (OSError, PermissionError):
            resultado["raw_filings_count"] = -1

    # 3. Detectar artefactos de pipeline (por prefijo de nombre)
    agent_names = {"CATALYST", "FORENSIC", "BULL", "RED_TEAM", "REDTEAM"}
    found_agents = set()

    for entry in entries:
        if not entry.endswith(".json") or entry.startswith("_"):
            continue

        if entry.startswith("SourcesPack"):
            if "SOURCES" not in resultado["pipeline_artifacts"]:
                resultado["pipeline_artifacts"].append("SOURCES")
        elif entry.startswith("TruthPack"):
            if "TRUTH_PACK" not in resultado["pipeline_artifacts"]:
                resultado["pipeline_artifacts"].append("TRUTH_PACK")
        elif entry.startswith("ImpliedExpectations"):
            if "IMPLIED" not in resultado["pipeline_artifacts"]:
                resultado["pipeline_artifacts"].append("IMPLIED")
        elif entry.startswith("DecisionPacket"):
            resultado["has_decision_packet"] = True
            if "ARBITRO" not in resultado["pipeline_artifacts"]:
                resultado["pipeline_artifacts"].append("ARBITRO")
        elif entry.startswith("AgentReport"):
            entry_upper = entry.upper()
            for agent in agent_names:
                if agent in entry_upper:
                    canonical = agent if agent != "REDTEAM" else "RED_TEAM"
                    found_agents.add(canonical)

    for agent in sorted(found_agents):
        resultado["pipeline_artifacts"].append(agent)

    # 4. Clasificar (jerarquía: pipeline completo > parcial > inicial > prefetch > raw)
    n_prefetch = len(resultado["prefetch_outputs"])
    n_pipeline = len(set(resultado["pipeline_artifacts"]))  # set() para evitar doble-conteo

    if resultado["has_decision_packet"] and n_pipeline >= 8:
        resultado["classification"] = "PIPELINE_COMPLETO_NO_REGISTRADO"
        resultado["suggested_action"] = "Registrar en ESTADO_REPO — 'Continúa {T}'"
    elif n_pipeline >= 4:
        resultado["classification"] = "PIPELINE_PARCIAL"
        resultado["suggested_action"] = "'Continúa {T}' para completar pipeline"
    elif n_pipeline >= 1:
        resultado["classification"] = "PIPELINE_INICIAL"
        resultado["suggested_action"] = "'Analiza {T}' — retomará desde step faltante"
    elif n_prefetch == 3:
        resultado["classification"] = "PREFETCH_COMPLETO"
        resultado["suggested_action"] = "'Analiza {T}' — saltará a SOURCES_COMPILER"
    elif n_prefetch >= 1:
        resultado["classification"] = "PREFETCH_PARCIAL"
        resultado["suggested_action"] = "'Analiza {T}' — lanzará fetchers faltantes"
    elif resultado["has_raw_filings"] and resultado["raw_filings_count"] > 0:
        resultado["classification"] = "RAW_FILINGS_ONLY"
        resultado["suggested_action"] = "Investigar origen de raw_filings"
    else:
        resultado["classification"] = "DIRECTORIO_VACIO"
        resultado["suggested_action"] = "Ignorar"

    return resultado


def parse_prefetch_inventory(dir_path):
    """Parsea los pre-fetch outputs y retorna inventario de fuentes por fetcher.

    Lee _sec_fetcher_output.json, _transcript_finder_output.json,
    _market_data_output.json si existen. Extrae conteo de fuentes y faltantes.
    Degradación paranoica: nunca crashea.

    Retorna dict con conteos por fetcher, o None si no hay pre-fetch outputs.
    """
    fetcher_map = {
        "_sec_fetcher_output.json": "SEC_FETCHER",
        "_transcript_finder_output.json": "TRANSCRIPT_FINDER",
        "_market_data_output.json": "MARKET_DATA",
    }

    resultado = {}
    total_f = 0
    total_m = 0
    any_found = False

    for filename, fetcher_name in fetcher_map.items():
        fp = os.path.join(dir_path, filename)
        if not os.path.isfile(fp):
            continue
        any_found = True
        data = load_json(fp)
        fuentes = data.get("fuentes", [])
        if not isinstance(fuentes, list):
            fuentes = []
        faltantes = data.get("faltantes", [])
        if not isinstance(faltantes, list):
            faltantes = []
        n_f = len(fuentes)
        n_m = len(faltantes)
        resultado[fetcher_name] = {"fuentes": n_f, "faltantes": n_m}
        total_f += n_f
        total_m += n_m

    if not any_found:
        return None

    resultado["total_fuentes"] = total_f
    resultado["total_faltantes"] = total_m
    return resultado


def parse_sourcespack_inventory(dir_path):
    """Parsea un SourcesPack compilado y retorna inventario de fuentes.

    Busca SourcesPack_v1_*.json en el directorio (excluye _*).
    Degradación paranoica: nunca crashea.

    Retorna dict con conteo de fuentes/faltantes, o None si no hay SourcesPack.
    """
    try:
        entries = os.listdir(dir_path)
    except (OSError, PermissionError):
        return None

    sp_file = None
    for entry in entries:
        if entry.startswith("SourcesPack") and entry.endswith(".json") and not entry.startswith("_"):
            sp_file = entry
            break

    if sp_file is None:
        return None

    data = load_json(os.path.join(dir_path, sp_file))
    if not isinstance(data, dict) or data.get("version_esquema") != "SourcesPack_v1":
        return None

    fuentes = data.get("fuentes", [])
    if not isinstance(fuentes, list):
        fuentes = []
    faltantes = data.get("faltantes", [])
    if not isinstance(faltantes, list):
        faltantes = []

    return {
        "fuentes": len(fuentes),
        "faltantes": len(faltantes),
    }


def build_filings_inventory(repo_root, casos, dirs_sin_estado, mcl_data):
    """Construye inventario completo de fuentes/filings para todos los tickers.

    Tres poblaciones:
      1. Casos registrados (con _estado.json): lee SourcesPack compilado
      2. Dirs sin _estado.json (huérfanos/nuevos): lee SourcesPack o pre-fetch outputs
      3. Candidatos MCL pendientes sin directorio: marca como sin_directorio
    Degradación paranoica: nunca crashea.
    """
    resultado = {
        "casos_con_sourcespack": [],
        "casos_prefetch_only": [],
        "candidatos_sin_directorio": [],
        "resumen": {
            "total_con_sourcespack": 0,
            "total_con_prefetch": 0,
            "necesitan_prefetch": 0,
        },
    }

    tickers_con_dir = set()

    # 1. Casos registrados (con _estado.json)
    if isinstance(casos, list):
        for caso in casos:
            if not isinstance(caso, dict):
                continue
            ticker = caso.get("ticker", "?")
            fecha = caso.get("fecha_caso", "?")
            directorio = caso.get("directorio")
            if not isinstance(directorio, str):
                continue
            tickers_con_dir.add(ticker)
            dir_path = os.path.join(repo_root, directorio)
            sp_inv = parse_sourcespack_inventory(dir_path)
            if sp_inv:
                resultado["casos_con_sourcespack"].append({
                    "ticker": ticker,
                    "fecha": fecha,
                    "fuentes": sp_inv["fuentes"],
                    "faltantes": sp_inv["faltantes"],
                })
                resultado["resumen"]["total_con_sourcespack"] += 1

    # 2. Dirs sin _estado.json (huérfanos)
    if dirs_sin_estado:
        for ticker, dd in dirs_sin_estado:
            tickers_con_dir.add(ticker)
            dir_path = os.path.join(repo_root, "casos", ticker, dd)
            # Primero: SourcesPack compilado?
            sp_inv = parse_sourcespack_inventory(dir_path)
            if sp_inv:
                resultado["casos_con_sourcespack"].append({
                    "ticker": ticker,
                    "fecha": dd,
                    "fuentes": sp_inv["fuentes"],
                    "faltantes": sp_inv["faltantes"],
                })
                resultado["resumen"]["total_con_sourcespack"] += 1
                continue
            # Si no: pre-fetch outputs?
            pf_inv = parse_prefetch_inventory(dir_path)
            if pf_inv:
                resultado["casos_prefetch_only"].append({
                    "ticker": ticker,
                    "fecha": dd,
                    "inventario": pf_inv,
                })
                resultado["resumen"]["total_con_prefetch"] += 1

    # 3. Candidatos MCL pendientes sin directorio
    if isinstance(mcl_data, dict):
        candidatos = mcl_data.get("candidatos", [])
        if isinstance(candidatos, list):
            for c in candidatos:
                if not isinstance(c, dict):
                    continue
                if c.get("estado") != "pendiente_evaluacion":
                    continue
                ticker = c.get("ticker", "?")
                if ticker in tickers_con_dir:
                    continue
                resultado["candidatos_sin_directorio"].append({
                    "ticker": ticker,
                    "tier": c.get("tier", "?"),
                    "score": c.get("score_interes"),
                })
                resultado["resumen"]["necesitan_prefetch"] += 1

    return resultado


def detect_orphaned_work(repo_root, casos, dirs_sin_estado=None):
    """Detecta trabajo huérfano: dirs en casos/ sin _estado.json válido.

    Si dirs_sin_estado se proporciona (lista de (ticker, date_dir) de load_all_case_states),
    clasifica cada uno directamente. Si no, cruza filesystem vs lista de casos (fallback).
    """
    resultado = {
        "orphaned": [],
        "newer_dirs": [],
        "total_orphaned": 0,
        "total_newer": 0,
    }

    if dirs_sin_estado is not None:
        # Modo v1.3: usar lista directa de dirs sin _estado.json
        # Construir mapa de tickers con _estado.json para distinguir orphaned vs newer_dirs
        registered = {}
        if isinstance(casos, list):
            for caso in casos:
                if not isinstance(caso, dict):
                    continue
                ticker = caso.get("ticker")
                if not isinstance(ticker, str):
                    continue
                fecha = caso.get("fecha_caso")
                if ticker not in registered:
                    registered[ticker] = set()
                if isinstance(fecha, str):
                    registered[ticker].add(fecha)

        for ticker, dd in dirs_sin_estado:
            dir_path = os.path.join(repo_root, "casos", ticker, dd)
            clf = classify_directory_work(dir_path)
            if clf["classification"] == "DIRECTORIO_VACIO":
                continue

            if ticker in registered:
                # Ticker tiene otros dirs con _estado.json → es un dir nuevo
                resultado["newer_dirs"].append({
                    "ticker": ticker,
                    "fecha_nueva": dd,
                    "fechas_registradas": sorted(registered[ticker]),
                    "clasificacion": clf,
                })
            else:
                resultado["orphaned"].append({
                    "ticker": ticker,
                    "fecha": dd,
                    "clasificacion": clf,
                })
    else:
        # Fallback: modo legacy (cruzar filesystem vs casos)
        registered = {}
        if isinstance(casos, list):
            for caso in casos:
                if not isinstance(caso, dict):
                    continue
                ticker = caso.get("ticker")
                if not isinstance(ticker, str):
                    continue
                fecha = caso.get("fecha_caso")
                if ticker not in registered:
                    registered[ticker] = set()
                if isinstance(fecha, str):
                    registered[ticker].add(fecha)

        disk_tickers = scan_casos_directory(repo_root)

        for ticker, date_dirs in sorted(disk_tickers.items()):
            if ticker in registered:
                reg_dates = registered[ticker]
                for dd in date_dirs:
                    if dd not in reg_dates:
                        dir_path = os.path.join(repo_root, "casos", ticker, dd)
                        clf = classify_directory_work(dir_path)
                        if clf["classification"] == "DIRECTORIO_VACIO":
                            continue
                        resultado["newer_dirs"].append({
                            "ticker": ticker,
                            "fecha_nueva": dd,
                            "fechas_registradas": sorted(reg_dates),
                            "clasificacion": clf,
                        })
            else:
                latest_date = date_dirs[-1]
                dir_path = os.path.join(repo_root, "casos", ticker, latest_date)
                clf = classify_directory_work(dir_path)
                if clf["classification"] == "DIRECTORIO_VACIO":
                    continue
                resultado["orphaned"].append({
                    "ticker": ticker,
                    "fecha": latest_date,
                    "clasificacion": clf,
                })

    resultado["total_orphaned"] = len(resultado["orphaned"])
    resultado["total_newer"] = len(resultado["newer_dirs"])

    return resultado


def main():
    repo_root = get_repo_root()
    estado_path = os.path.join(repo_root, "ESTADO_REPO.json")
    mcl_path = os.path.join(repo_root, "candidatos", "MasterCandidateList.json")

    estado_global = load_json(estado_path)  # v2.0: solo scout + scanner + meta
    mcl = load_json(mcl_path)

    hoy = date.today()

    # Cargar casos desde _estado.json por directorio (v1.3)
    casos, dirs_sin_estado = load_all_case_states(repo_root)

    # 1. Casos por estado
    conteo_estados = count_cases_by_estado(casos)
    completos = get_tickers_by_estado(casos, "COMPLETO")
    incompletos_detalle = get_incompletos_detalle(casos)
    quarantine_detalle = get_quarantine_detalle(casos)

    # 2. Monitors vencidos
    monitors_vencidos = get_monitors_vencidos(casos, hoy)

    # 3. Último SCOUT (desde ESTADO_REPO.json global)
    scout_info = get_scout_info(estado_global.get("scout"))

    # 4. Último SCANNER (desde ESTADO_REPO.json global)
    scanner_info = get_scanner_info(estado_global.get("scanner"))

    # 5. Urgencias pendientes (CON filtro anti-duplicado — ENTRY_POINT.md §regla)
    urgencias_data = filtrar_urgencias_anti_duplicado(repo_root, scanner_info, casos)
    urgencias = urgencias_data["urgencias_pendientes"]

    # 6. Candidatos por tier y pendientes de evaluación
    candidatos_pendientes = count_candidatos_pendientes(mcl)
    candidatos_tier = get_candidatos_por_tier(mcl)

    # 7. Trabajo huérfano en filesystem (dirs sin _estado.json)
    orphan_data = detect_orphaned_work(repo_root, casos, dirs_sin_estado=dirs_sin_estado)

    # 8. Inventario de fuentes/filings
    filings_inv = build_filings_inventory(repo_root, casos, dirs_sin_estado, mcl)

    # Construir resultado
    resultado = {
        "fecha_resumen": hoy.isoformat(),
        "casos_por_estado": conteo_estados,
        "total_casos": len(casos),
        "completos_tickers": completos,
        "incompletos_detalle": incompletos_detalle,
        "quarantine_detalle": quarantine_detalle,
        "monitors_vencidos": monitors_vencidos,
        "ultimo_scout": scout_info,
        "ultimo_scanner": {
            "fecha": scanner_info["fecha"],
            "hallazgos_raw": urgencias_data["urgencias_raw"],
            "hallazgos_pendientes": urgencias_data["urgencias_pendientes"],
            "resueltos_anti_dup": urgencias_data["urgencias_resueltas"],
        },
        "urgencias_pendientes": urgencias,
        "urgencias_detalle": urgencias_data["urgencias_pendientes_detalle"],
        "candidatos_total": candidatos_tier["total"],
        "candidatos_completados": candidatos_tier["completados"],
        "candidatos_pendientes_evaluacion": candidatos_tier["pendientes_evaluacion"],
        "candidatos_en_pipeline": candidatos_tier["en_pipeline"],
        "candidatos_por_tier": candidatos_tier["por_tier"],
        "trabajo_huerfano": orphan_data["orphaned"],
        "dirs_nuevos_no_registrados": orphan_data["newer_dirs"],
        "total_huerfanos": orphan_data["total_orphaned"],
        "total_dirs_nuevos": orphan_data["total_newer"],
        "inventario_fuentes": filings_inv,
    }

    # Salida
    if "--quarantine" in sys.argv:
        print(json.dumps(quarantine_detalle, ensure_ascii=False, indent=2))
        return
    elif "--json" in sys.argv:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        print(f"=== ELSIAN INVEST ({hoy.isoformat()}) ===")
        print()

        # --- Cabecera compacta (2 líneas) ---
        estado_parts = []
        for est in ["COMPLETO", "QUARANTINE", "EXCLUIDO", "SUPERSEDED", "INCOMPLETO", "LEGACY"]:
            n = conteo_estados.get(est, 0)
            if n > 0:
                estado_parts.append(f"{n} {est.lower()}")
        mon_count = len(monitors_vencidos)
        print(f"ESTADO: {len(casos)} casos ({', '.join(estado_parts)}) | Monitors vencidos: {mon_count}")
        if mon_count > 0:
            for mv in monitors_vencidos:
                print(f"  Monitor: {mv}")
        print(f"META: Scout {scout_info['fecha']} ({scout_info['version']}) · Scanner {scanner_info['fecha']} ({urgencias} urgencias)")

        # --- ACCIÓN REQUERIDA ---
        print()
        print("ACCIÓN REQUERIDA:")
        action_num = 0

        # 0. Re-hacer casos en cuarentena (PRIORIDAD MÁXIMA)
        if quarantine_detalle:
            action_num += 1
            print(f"\n  {action_num}. Re-hacer casos en cuarentena ({len(quarantine_detalle)}):")
            for qd in quarantine_detalle:
                motivo_corto = qd["motivo"]
                if len(motivo_corto) > 60:
                    motivo_corto = motivo_corto[:57] + "..."
                print(f'     {qd["ticker"]:5s} ({qd["fecha"]}) \u2014 {qd["veredicto"]}: {motivo_corto} \u2192 "Re-hacer {qd["ticker"]}"')

        # 1. Continuar pipeline incompleto (casos registrados)
        incompletos_accion = []
        for caso in casos:
            if not isinstance(caso, dict):
                continue
            if caso.get("estado_pipeline") == "INCOMPLETO":
                ticker = caso.get("ticker", "?")
                ns = caso.get("next_step", "?")
                incompletos_accion.append((ticker, ns))
        if incompletos_accion:
            action_num += 1
            print(f"\n  {action_num}. Continuar pipeline incompleto:")
            for t, ns in incompletos_accion:
                print(f'     {t:5s} — next: {ns} → "Continúa {t}"')

        # 1+. Registrar: pipelines completos sin _estado.json
        registrar = []
        for orph in orphan_data.get("orphaned", []):
            clf = orph.get("clasificacion", {})
            if clf.get("classification") == "PIPELINE_COMPLETO_NO_REGISTRADO":
                registrar.append(orph["ticker"])
        if registrar:
            action_num += 1
            print(f"\n  {action_num}. Registrar (pipeline completo sin _estado.json):")
            for t in registrar:
                print(f'     {t} → "Continúa {t}"')

        # 2. Lanzar pipeline: pre-fetch o pipeline parcial con inventario inline
        # Construir mapas ticker→inventario desde filings_inv
        prefetch_inv_map = {}
        for item in filings_inv.get("casos_prefetch_only", []):
            prefetch_inv_map[item["ticker"]] = item["inventario"]
        sourcespack_inv_map = {}
        for item in filings_inv.get("casos_con_sourcespack", []):
            sourcespack_inv_map[item["ticker"]] = item

        pipeline_items = []  # list of (ticker, classification)
        PIPELINE_ACTIONABLE = {"PREFETCH_COMPLETO", "PREFETCH_PARCIAL", "PIPELINE_INICIAL", "PIPELINE_PARCIAL"}
        for orph in orphan_data.get("orphaned", []) + orphan_data.get("newer_dirs", []):
            clf = orph.get("clasificacion", {})
            classification = clf.get("classification", "")
            if classification in PIPELINE_ACTIONABLE:
                ticker = orph.get("ticker", "?")
                pipeline_items.append((ticker, classification))
        if pipeline_items:
            action_num += 1
            print(f"\n  {action_num}. Lanzar pipeline (pre-fetch listo):")
            for t, clf in pipeline_items:
                # Determinar acción: "Continúa" si ya tiene steps del pipeline, "Analiza" si solo pre-fetch
                action_verb = "Continúa" if clf.startswith("PIPELINE") else "Analiza"
                # Inventario: primero pre-fetch detallado, luego SourcesPack agregado
                inv = prefetch_inv_map.get(t)
                if inv:
                    parts = []
                    for fk, label in [("SEC_FETCHER", "SEC"), ("TRANSCRIPT_FINDER", "TRANS"), ("MARKET_DATA", "MKT")]:
                        if fk in inv:
                            s = f"{label}:{inv[fk]['fuentes']}"
                            if inv[fk]["faltantes"] > 0:
                                s += f"({inv[fk]['faltantes']}!)"
                            parts.append(s)
                    inv_str = " + ".join(parts) if parts else "?"
                    print(f'     {t:5s} — {inv_str} → "{action_verb} {t}"')
                elif t in sourcespack_inv_map:
                    sp = sourcespack_inv_map[t]
                    sp_str = f"SourcesPack: {sp['fuentes']}f"
                    if sp.get("faltantes", 0) > 0:
                        sp_str += f"({sp['faltantes']}!)"
                    print(f'     {t:5s} — {sp_str} → "{action_verb} {t}"')
                else:
                    print(f'     {t:5s} → "{action_verb} {t}"')

        # 3. Lanzar pre-fetch: candidatos sin directorio
        sin_dir = filings_inv.get("candidatos_sin_directorio", [])
        if sin_dir:
            action_num += 1
            print(f"\n  {action_num}. Lanzar pre-fetch via Codex ({len(sin_dir)}):")
            by_tier = {}
            for c in sin_dir:
                tier = c.get("tier", "?")
                by_tier.setdefault(tier, []).append(c)
            for tier in sorted(by_tier.keys()):
                items = by_tier[tier]
                tickers_str = ", ".join(f"{c['ticker']}({c['score']})" for c in items)
                print(f"     Tier {tier}: {tickers_str}")

        # 4. Urgencias scanner compactas
        urg_detalle = urgencias_data.get("urgencias_pendientes_detalle", [])
        if urg_detalle:
            action_num += 1
            print(f"\n  {action_num}. Urgencias scanner ({len(urg_detalle)}):")
            # Agrupar por categoría de evento
            urg_groups = {}
            for ud in urg_detalle:
                tipo = ud.get("tipo_evento", "OTHER")
                # Categorizar: 52W_HIGH, 52W_LOW, PRICE_MOVE, FILING_*
                if tipo.startswith("FILING"):
                    cat = "FILING"
                elif tipo == "52W_HIGH":
                    cat = "52W_HIGH"
                elif tipo == "52W_LOW":
                    cat = "52W_LOW"
                elif tipo == "PRICE_MOVE":
                    cat = "PRICE"
                else:
                    cat = tipo
                urg_groups.setdefault(cat, []).append(ud)

            for cat in ["52W_HIGH", "52W_LOW", "PRICE", "FILING"]:
                items = urg_groups.get(cat, [])
                if not items:
                    continue
                parts = []
                for ud in items:
                    ticker = ud["ticker"]
                    desc = ud.get("descripcion", "")
                    tipo = ud.get("tipo_evento", "")
                    # Extraer dato compacto
                    if cat in ("52W_HIGH", "52W_LOW", "PRICE"):
                        # Extraer 5d change
                        m = re.search(r"5d\s*([+-]?\d+\.?\d*)%", desc)
                        if m:
                            parts.append(f"{ticker}({m.group(1)}%)")
                        else:
                            parts.append(ticker)
                    else:
                        # Filing: extraer tipo corto
                        filing_type = tipo.replace("FILING_", "")
                        parts.append(f"{ticker}({filing_type})")
                print(f"     {cat}: {', '.join(parts)}")

            # Categorías residuales
            shown_cats = {"52W_HIGH", "52W_LOW", "PRICE", "FILING"}
            for cat, items in urg_groups.items():
                if cat in shown_cats:
                    continue
                parts = [ud["ticker"] for ud in items]
                print(f"     {cat}: {', '.join(parts)}")

        if action_num == 0:
            print("\n  Sin acciones pendientes.")

        # --- Footer ---
        print()
        print("Operaciones: Scout · Pipeline · Continuar · Monitor · Outcome · Evaluar · Scanner")


if __name__ == "__main__":
    main()
