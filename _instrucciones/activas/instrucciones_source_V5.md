SOURCES V5 --> Recolector de fuentes primarias con **cache local** de documentos.

> **Modo de ejecución: SUB-AGENTES OBLIGATORIO** (ver PROTOCOLO_AUTONOMO §1):
> SEC_FETCHER_V2 (instrucciones_sec_fetcher_V2.md)
> ‖ MARKET_DATA (instrucciones_market_data_V1.md) ‖ TRANSCRIPT_FINDER_V2 (instrucciones_transcript_finder_V2.md)
> → SOURCES_COMPILER_V2 (instrucciones_sources_compiler_V2.md). Los 3 primeros en paralelo.
> Este archivo sirve como referencia de la misión completa. La ejecución debe usar siempre los sub-agentes.

> **Cambio respecto a V4:** V5 añade descarga y almacenamiento local del contenido textual
> de filings SEC y transcripts al momento de localizarlos. El SourcesPack incluye `local_path`
> por cada fuente descargada, eliminando re-fetch por agentes downstream.

## 1. MISIÓN
Construir o actualizar SourcesPack_v1 recopilando documentos oficiales, filings SEC, transcripciones y datos de mercado. **Descargar el contenido textual de cada filing y transcript encontrado** y guardarlo localmente en `casos/{T}/_raw_filings/` (nivel de ticker, compartido entre analisis).

## 2. REGLA ABSOLUTA DE SALIDA
- NORMAL: salida ÚNICAMENTE JSON `SourcesPack_v1` + archivos descargados en `casos/{T}/_raw_filings/`.
- PATCH: salida ÚNICAMENTE JSON `PatchBundle_v3`.

## 3. PROHIBICIONES
- No inventar métricas, hechos, fechas ni documentos.
- No hacer análisis financiero ni construir tesis.
- Extractos máximo 25 palabras.
- No simular URLs inexistentes.
- **No usar formato Markdown en URLs.** Siempre URL cruda: `"https://..."`. Nunca `"[https://...](https://...)"` ni `"[texto](url)"`.
- No modificar el contenido descargado (guardar tal cual se recibe).

## 4. INPUTS

| Modo | Input |
|------|-------|
| NORMAL | Ticker/empresa (texto o JSON con campos opcionales: nombre, bolsa, cik, web_ir) |
| PATCH | RemediationPlan_v1 (fichero adjunto) |

## 5. DETECCIÓN DE MODO
- Hay fichero adjunto RemediationPlan_v1 => PATCH.
- Cualquier otro caso => NORMAL.

## 6. MODO NORMAL

N1) Identificar empresa: usar ticker, nombre, CIK y/o web_ir proporcionados.

N2) Crear directorio `_raw_filings/` a nivel del ticker (`casos/{T}/_raw_filings/`) si no existe. Este directorio es compartido entre todos los analisis del mismo ticker.

N3) Buscar fuentes según cobertura obligatoria:
    - 10-K / 20-F (informe anual)
    - 10-Q / 6-K (informe trimestral)
    - Earnings Release + Exhibit 99
    - Transcripción de resultados
    - Presentación a inversores
    - DEF14A (proxy)
    - Credit Agreement (si aplica)
    - Datos de mercado (precio, acciones, market cap)

N4) **Al localizar cada filing/transcript, descargar y cachear:**
    - Acceder a la URL del documento.
    - **Guardar el archivo original** (PDF o HTML) tal cual en `_raw_filings/`:
      - Naming: `{source_id}_{tipo}_{periodo}.{ext}` (ext = pdf, html, htm)
    - **Extraer el contenido textual** (texto plano) y guardar junto al original:
      - Naming: `{source_id}_{tipo}_{periodo}.txt`
    - **Naming general**: ver REGLAS_COMUNES §1 "Cache local de documentos fuente".
    - El campo `local_path` en el JSON apunta al `.txt` (que leen agentes downstream).
    - El original (`.pdf`/`.html`) queda como referencia para revisión manual.
    - **Excepción**: MARKET_DATA no se descarga como archivo (sus datos se capturan en el campo `datos` del JSON).
    - Si la descarga falla: registrar en `log.limitaciones`, no incluir `local_path`.

N5) Invariantes:
    - source_id: formato "SRC_###" (3 dígitos).
    - DEDUP por URL o accession number.
    - **FORMATO URL OBLIGATORIO**: todas las URLs deben ser cadenas crudas `"https://..."`. NUNCA emitir `"[https://...](https://...)"` ni ningún formato Markdown.
    - **`local_path`**: incluir en cada fuente cuyo contenido se descargo exitosamente. Ruta relativa a la raiz del repo (e.g., `casos/CRCT/_raw_filings/SRC_001_10-K_FY2024.txt`).
    - Máximo 1 fuente tipo MARKET_DATA.

N6) Documentar faltantes con prioridad y cómo obtenerlos.

N7) Salida: SOLO JSON `SourcesPack_v1` + archivos en `casos/{T}/_raw_filings/`.

## 7. MODO PATCH

P0) Leer RemediationPlan del fichero adjunto.
    - work_orders := fichero.work_orders
    - decision_packet_ref := fichero.decision_packet_ref

P1) Filtrar WOs: solo `agent_role=="SOURCES"` Y `tipo=="FETCH_SOURCES"`.

P2) Ejecutar cada WO: buscar las fuentes indicadas en targets.
    - **Descargar y cachear cada nueva fuente encontrada** siguiendo N4).

P3) Construir SourcesPack_v1 con las fuentes encontradas/actualizadas, incluyendo `local_path`.

P4) CREAR PatchBundle_v3:
```json
{
  "version_esquema": "PatchBundle_v3",
  "decision_packet_ref": { "file_name": "<del plan>" },
  "current_step": 1,
  "artifact_updates": {
    "sources_pack": "<SourcesPack_v1 generado>",
    "truth_pack": null,
    "implied_expectations": null,
    "agent_reports": { "CATALYST": null, "FORENSIC": null, "BULL": null, "RED_TEAM": null }
  },
  "patch_reports": [{
    "agent_role": "SOURCES",
    "status_global": "DONE|PARTIAL|BLOCKED",
    "wo_results": [{ "wo_id": "...", "status": "...", "notes": "..." }]
  }],
  "source_requests": [...]
}
```

P5) Determinar status:
    - DONE: todas las fuentes solicitadas encontradas.
    - PARTIAL: algunas encontradas, otras no.
    - BLOCKED: ninguna encontrada.

P6) Salida: SOLO JSON `PatchBundle_v3`.

## 8. ESQUEMAS
- SourcesPack_v1.json
- PatchBundle_v3.json
- RemediationPlan_v1.json
