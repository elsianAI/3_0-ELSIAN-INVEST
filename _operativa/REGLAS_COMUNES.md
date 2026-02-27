# ELSIAN INVEST — Reglas Comunes

> **Aplicables a TODOS los motores** (autónomo y asistido) y **TODOS los modelos** (Claude, Codex, Gemini). Referenciado por los protocolos de ejecución.

---

## §1 CONVENCIONES DE ARCHIVOS

### Estructura de directorio por ticker
```
casos/{T}/
├── _raw_filings/                                (cache local, compartido entre análisis)
│   ├── SRC_001_10-K_FY2024.htm                  (original HTML de SEC EDGAR)
│   ├── SRC_001_10-K_FY2024.txt                  (texto plano para agentes LLM)
│   ├── SRC_002_10-Q_Q2-2025.htm
│   ├── SRC_002_10-Q_Q2-2025.txt
│   ├── SRC_007_TRANSCRIPT_Q4-2024.txt           (transcripts suelen ser solo texto)
│   └── ...
├── {D}_{M}/                                     (análisis — {M} = modelo CamelCase)
│   ├── _estado.json
│   ├── SourcesPack_v1_{T}_{D}_{M}.json
│   ├── TruthPack_v1_{T}_{D}_{M}.json
│   ├── ImpliedExpectations_v1_{T}_{D}_{M}.json
│   ├── AgentReport_v1_CATALYST_{T}_{D}_{M}.json
│   ├── AgentReport_v1_FORENSIC_{T}_{D}_{M}.json
│   ├── AgentReport_v1_BULL_{T}_{D}_{M}.json
│   ├── AgentReport_v1_REDTEAM_{T}_{D}_{M}.json
│   ├── DecisionPacket_v2_{T}_{D}_{M}.json
│   ├── MonitoringUpdate_v1_{T}_{D}_revN_{M}.json   (si aplica)
│   └── OutcomeRecord_v1_{T}_{D}_{M}.json           (si aplica)
├── {D}_{M2}/                                    (benchmark con otro modelo, opcional)
│   ├── _estado.json
│   └── ... (artefactos completos)
```

### Cache local de documentos fuente (`_raw_filings/`)

Los sub-agentes de SOURCES (SEC_FETCHER, TRANSCRIPT_FINDER) descargan el contenido textual de cada documento al momento de localizarlo. El contenido se guarda en `casos/{T}/_raw_filings/` (a nivel de ticker, compartido entre todos los análisis del mismo ticker) para que los agentes downstream lo lean localmente sin re-fetch.

**Naming**: `{source_id}_{tipo}_{periodo}.{ext}`

| Componente | Descripción | Ejemplo |
|------------|-------------|---------|
| `source_id` | ID de la fuente en SourcesPack | `SRC_001` |
| `tipo` | Tipo de filing en mayúsculas | `10-K`, `10-Q`, `TRANSCRIPT`, `DEF14A` |
| `periodo` | Periodo fiscal o fecha del evento | `FY2024`, `Q2-2025`, `Q4-2024` |
| `ext` | Extensión según tipo de archivo | `.txt`, `.htm`, `.html`, `.pdf` |

**Extensiones**: Se guardan **dos archivos** por cada fuente descargada:

| Archivo | Naming | Propósito | Ejemplo |
|---------|--------|-----------|---------|
| **Original** | `{source_id}_{tipo}_{periodo}.{ext_original}` | Referencia archival con formato, tablas y gráficos | `SRC_001_10-K_FY2024.htm` |
| **Texto plano** | `{source_id}_{tipo}_{periodo}.txt` | Consumo directo por agentes LLM downstream | `SRC_001_10-K_FY2024.txt` |

Donde `{ext_original}` es la extensión del documento fuente: `.htm`/`.html` (filings SEC), `.pdf` (presentaciones, proxies) o la extensión nativa del documento.

**Reglas**:

1. **Obligatorio para filings SEC y transcripts.** MARKET_DATA no requiere archivo (sus datos se capturan estructurados en el campo `datos` del SourcesPack).
2. **El SourcesPack incluye `local_path`** en cada fuente que tiene archivo local. Formato: `casos/{T}/_raw_filings/{filename}` (ruta relativa a la raíz del repo). `local_path` apunta siempre al `.txt` (que es lo que leen agentes downstream).
3. **El original (.htm/.pdf) se guarda junto al .txt** con el mismo nombre base pero extensión original. Queda como referencia para revisión manual, verificación de tablas/gráficos, y trazabilidad archival.
4. **Agentes downstream leen `local_path` (.txt) primero.** Si `local_path` existe y el archivo está presente, NO se accede a la URL. La URL queda como referencia y fallback.
5. **El contenido es una snapshot inmutable.** No se modifica después de guardarlo. Si se necesita versión actualizada, se re-ejecuta SOURCES completo.
6. **El SOURCES_COMPILER preserva `local_path`** durante la consolidación y re-numeración (actualizando el source_id en el filename si cambia). Al renombrar, renombra **ambos archivos** (original + .txt).
7. **Si la descarga del original falla** pero el texto se extrajo correctamente, guardar solo el `.txt` y registrar la limitación en `log.limitaciones`.

### Distincion: `faltantes[]` vs `log.limitaciones`

| Campo | Donde vive | Que registra | Ejemplo |
|-------|-----------|-------------|---------|
| `faltantes[]` | SourcesPack_v1 | Documentos que se buscaron y **no se localizaron** | `"10-K FY2023 no disponible en EDGAR"` |
| `log.limitaciones` | Cualquier artefacto | Restricciones operativas del agente durante la ejecucion | `"Descarga original .htm fallo, solo .txt disponible"` |

**Regla:** `faltantes` es inventario de **huecos documentales**. `log.limitaciones` es inventario de **restricciones del proceso**. No mezclar.

### Archivos intermedios de sub-agentes (`_*_output.json`)

Los sub-agentes del Step 1 (SEC_FETCHER, MARKET_DATA, TRANSCRIPT_FINDER) generan outputs intermedios en el directorio del caso antes de que el SOURCES_COMPILER los consolide. Estos archivos son **temporales** — existen entre la ejecución de los fetchers y la compilación final del SourcesPack.

**Convención de naming:**

| Sub-agente | Archivo | Contenido |
|------------|---------|-----------|
| SEC_FETCHER | `_sec_fetcher_output.json` | SourcesPack_v1 parcial, fuentes `SRC_SEC_###` |
| MARKET_DATA | `_market_data_output.json` | SourcesPack_v1 parcial, fuente `SRC_MKT_001` |
| TRANSCRIPT_FINDER | `_transcript_finder_output.json` | SourcesPack_v1 parcial, fuentes `SRC_TR_###` / `SRC_PR_###` |

**Reglas:**

1. Los 3 archivos usan el schema `SourcesPack_v1` (campo `version_esquema: "SourcesPack_v1"`), con source_ids prefijados por sub-agente. El SOURCES_COMPILER los re-numera a SRC_001, SRC_002, etc. durante la consolidación.
2. Los archivos intermedios **no se incluyen en commits**. Solo el SourcesPack_v1 final (post-compilación) se commitea.
3. Si estos archivos existen al iniciar un pipeline, el orquestador los detecta y puede reutilizarlos (ver `PROTOCOLO_AUTONOMO.md` §1 "Pre-fetch: Detección de outputs pre-existentes"). Esto permite que un motor externo (ej. Codex vía OpenAI) pre-genere los outputs de Step 1 antes de que el pipeline principal los consuma.
4. Tras la compilación exitosa del SourcesPack_v1 final, los archivos intermedios **pueden mantenerse** como referencia (no es necesario eliminarlos — el prefijo `_` los distingue de artefactos canónicos).

**Generación automatizada:** Los archivos intermedios pueden generarse via los runners en `scripts/runners/`. Ver `PROTOCOLO_AUTONOMO.md` §1 "Runners de pre-fetch" y `POLITICA_FALTANTES.md`.

### Variables
- `{T}`: Ticker en mayúsculas (ej. CROX, GCT, AAPL)
- `{D}`: Fecha YYYY-MM-DD del día de ejecución
- `{D_ID}`: Misma fecha sin guiones YYYYMMDD

### [LEGACY] Nombrado dual-modelo

> **NOTA:** El modo DUAL_MODELO fue eliminado en la migración de 2026-02-14. Esta sección se mantiene como referencia para casos históricos que tienen artefactos con sufijos de modelo (`_codex53`, `_opus46`, `_gemini3pro`).

Cuando se ejecutaba un step en modo `DUAL_MODELO`, se generaban **N+1 archivos por step** (uno por modelo activo + canónico).

Con la configuración actual (`codex53`, `opus46`, `gemini3pro`) se guardan 4 archivos:

| Tipo | Patrón | Ejemplo |
|------|--------|---------|
| Output codex53 | `{Schema}_v{N}_{T}_{D}_codex53.json` | `TruthPack_v1_INMD_2026-02-10_codex53.json` |
| Output opus46 | `{Schema}_v{N}_{T}_{D}_opus46.json` | `TruthPack_v1_INMD_2026-02-10_opus46.json` |
| Output gemini3pro | `{Schema}_v{N}_{T}_{D}_gemini3pro.json` | `TruthPack_v1_INMD_2026-02-10_gemini3pro.json` |
| Canónico (ganador) | `{Schema}_v{N}_{T}_{D}.json` | `TruthPack_v1_INMD_2026-02-10.json` |

**Aliases de modelo** (usados en filenames, siempre lowercase):

| Alias | Modelo completo |
|-------|----------------|
| `codex53` | GPT-5.3 Codex (OpenAI) |
| `opus46` | Claude Opus 4.6 (Anthropic) |
| `gemini3pro` | Gemini 3 Pro (Google) |
| `chatgpt` | Modelo activo de ChatGPT (manual/asistido, opcional) |

**Reglas de naming dual:**
- El artefacto canónico (sin sufijo) es siempre el ganador de la votación ciega.
- `_estado.json` del caso apunta SIEMPRE al artefacto canónico.
- Los artefactos modelo-específicos (con sufijo) quedan para histórico y comparación.
- En single-model (AUTONOMO o ASISTIDO), NO se añade sufijo — el naming es idéntico al actual.

> --- FIN SECCION LEGACY --- Los agentes NO deben aplicar reglas de esta seccion a casos nuevos. Solo es referencia para interpretar artefactos historicos con sufijos `_codex53`, `_opus46`, `_gemini3pro`.

### IDs

| Tipo | Formato | Ejemplo |
|------|---------|---------|
| Caso | `CASE_{D_ID}_{T}_{M}` | `CASE_20260208_AAPL_Claude` |
| Fuente | `SRC_###` | `SRC_001` |
| Supuesto | `A-###` | `A-001` |
| Catalizador | `C-###` | `C-001` |
| Kill Criteria | `KC-###` | `KC-001` |
| Claim | `CLM_###` | `CLM_001` |
| Predicción (AgentReport) | `PRED_###` | `PRED_001` |
| Predicción (DecisionPacket) | `CP-###` | `CP-001` |

### Bloque `_meta` (OBLIGATORIO en todo artefacto)

Todo artefacto JSON generado debe incluir un bloque `_meta` en el top-level con la siguiente estructura:

```json
"_meta": {
  "motor": "AUTONOMO | ASISTIDO",
  "plataforma": "claude_code | codex | gemini_cli | chatgpt",
  "modelo": "claude-opus-4.6 | gpt-5.3-codex | gemini-3.1-pro-preview | chatgpt-4o | ...",
  "proyecto_chatgpt": "<nombre del proyecto, solo si motor=ASISTIDO>",
  "timestamp": "YYYY-MM-DDTHH:MM:SSZ",
  "version_protocolo": "V3",
  "modo_dual": {
    "modelo_alias": "codex53 | opus46 | gemini3pro | chatgpt",
    "es_canonico": true | false,
    "votacion": {
      "score_recibido": 0-100 | null,
      "score_por_votante": {
        "codex53": 0-100,
        "opus46": 0-100,
        "gemini3pro": 0-100
      },
      "votantes_validos": ["codex53", "opus46", "gemini3pro"],
      "resultado": "codex53 | opus46 | gemini3pro | EMPATE | FALLBACK_SINGLE"
    }
  }
}
```

**Campos principales:**

| Campo | Tipo | Obligatorio | Descripción |
|-------|------|-------------|-------------|
| `motor` | enum | SÍ | `"AUTONOMO"` o `"ASISTIDO"` (legacy: `"DUAL_MODELO"`) |
| `plataforma` | enum | SÍ | Runtime de ejecución: `"claude_code"`, `"codex"`, `"gemini_cli"`, `"chatgpt"` (legacy: `"cowork"`, `"openclaw"`) |
| `modelo` | string | Sí | Modelo LLM específico. Ej: `"claude-opus-4.6"`, `"gpt-5.3-codex"`, `"gemini-3.1-pro-preview"`, `"chatgpt-4o"`, `"gpt-5.2-pro"` |
| `proyecto_chatgpt` | string | Solo si ASISTIDO | Nombre del proyecto ChatGPT usado. Ej: `"ELSIAN_TRUTH_PACK"` |
| `timestamp` | string (ISO 8601) | SÍ | Momento de generación del artefacto |
| `version_protocolo` | string | SÍ | Versión del protocolo operativo (`"V3"` actualmente) |

**[LEGACY] Campos `modo_dual` (solo en artefactos históricos con `motor=DUAL_MODELO`):**

| Campo | Tipo | Obligatorio | Descripción |
|-------|------|-------------|-------------|
| `modo_dual.modelo_alias` | enum | SÍ | Alias corto del modelo: `"codex53"`, `"opus46"`, `"gemini3pro"`, `"chatgpt"` |
| `modo_dual.es_canonico` | boolean | SÍ | `true` si este artefacto fue seleccionado como canónico post-votación |
| `modo_dual.votacion.score_recibido` | number/integer/null | SÍ | Score ciego final recibido por el artefacto (normalmente promedio de votantes válidos) |
| `modo_dual.votacion.score_por_votante` | object | Recomendado | Mapa `{alias_votante: score_0_100}` para trazabilidad de votación multi-modelo |
| `modo_dual.votacion.votantes_validos` | array[string] | Recomendado | Lista de aliases que emitieron voto válido |
| `modo_dual.votacion.resultado` | enum | SÍ | Ganador global del step: `"codex53"`, `"opus46"`, `"gemini3pro"`, `"EMPATE"` o `"FALLBACK_SINGLE"` |

**Retrocompatibilidad:** Artefactos existentes con el campo `agente` (formato anterior) siguen siendo válidos. Para nuevos artefactos, usar siempre `plataforma` + `modelo`.

**Reglas:**
- El agente que genera el artefacto es responsable de rellenar `_meta` automáticamente.
- En modo ASISTIDO, el copiloto AÑADE el bloque `_meta` al JSON que recibe del usuario (ChatGPT no lo genera — el copiloto lo inyecta antes de guardar). El copiloto pregunta al usuario qué modelo usó si no lo sabe.
- En modo AUTÓNOMO con subagentes (CATALYST ‖ FORENSIC), el agente principal inyecta `_meta` en cada output antes de guardar.
- `modelo` debe ser el identificador exacto del LLM (ej. `"gpt-5.3-codex"`, `"gemini-3.1-pro-preview"`; no alias ambiguos como `"codex"`). `plataforma` identifica el runtime/entorno.
- Si el agente no puede determinar su propio modelo, usar un identificador genérico (ej. `"cowork"`, `"chatgpt"`) como `modelo`.

---

## §2 REGLAS ABSOLUTAS

1. **No inventes datos.** Si no tienes un dato, ponlo como `null` y márcalo en `faltantes_criticos`.
2. **No inventes URLs.** Si no encuentras un documento, di que no lo encontraste.
3. **Cada afirmación requiere evidencia** con `source_id`, ubicación y cita corta (max 25 palabras).
4. **Cada hipótesis requiere test de falsación** con evento observable, ventana temporal y fuente prevista.
5. **Escala siempre "1" (USD absolutos).** Sin excepciones.
6. **URLs siempre raw.** Nunca formato Markdown dentro de JSON.
7. **Valida SIEMPRE antes de guardar** (§3). Sin excepciones.
8. **Actualiza `_estado.json` del caso y CHANGELOG después de cada paso.**
9. **Sigue las instrucciones del agente al pie de la letra.** No improvises ni te saltes pasos.
10. **Si algo no cuadra, para y pregunta al usuario.**
11. **Campos `_0_1` en rango [0, 1].** El ÚNICO campo en escala 0-5 es `conviccion_preliminar_0_5`.
12. **Todo texto en español.** Si una fuente está en inglés, la interpretación va en español.
13. **Enums = valor único.** Nunca `"A|B|C"`.
14. **`predicciones_calibracion` y `peticiones_de_fuentes` son OBLIGATORIOS** en todo AgentReport.
15. **No propagues bugs.** El ÁRBITRO debe verificar rangos antes de copiar valores.

---

## §3 PROTOCOLO DE VALIDACIÓN

Después de generar cada artefacto JSON, ejecutar validación programática con Python.

### Validaciones obligatorias

1. **JSON parseable**
2. **`version_esquema` presente y correcta** (debe coincidir con el schema)
3. **`caso_id` coherente** con el caso actual
4. **`fecha_corte` coherente**
5. **URLs NO en formato Markdown** dentro del JSON
6. **Campos requeridos top-level** según schema:

| Schema | Campos requeridos |
|--------|------------------|
| SourcesPack_v1 | caso_id, fecha_corte, empresa, cobertura_documental, fuentes |
| TruthPack_v1 | caso_id, fecha_corte, empresa, mercado, historico_anual, data_quality |
| ImpliedExpectations_v1 | caso_id, fecha_corte, empresa, status, snapshot_mercado, multiples_implicitos |
| AgentReport_v1 | version_esquema, caso_id, fecha_corte, agente, _meta, resumen_ejecutivo, claims, payload, predicciones_calibracion, peticiones_de_fuentes |

> **Nota:** `agente` se mantiene por compatibilidad con `AgentReport_v1.json` schema. `_meta` es obligatorio por protocolo V3+. Ambos deben estar presentes.
| DecisionPacket_v2 | caso_id, fecha_corte, empresa, resumen_ejecutivo, gates, assumption_ledger, escenarios, decision_probabilistica |
| DecisionPacket_v1 (legacy) | caso_id, fecha_corte, empresa, resumen_ejecutivo, gates, assumption_ledger, escenarios |
| MonitoringUpdate_v1 | caso_id, fecha_corte, revision_numero, cambios_detectados, bandera, accion_recomendada |
| OutcomeRecord_v1 | caso_id, ticker, estado, tracking_de_precio |
| CalibrationReport_v1 | fecha_corte, scope, metricas_calibracion |

7. **`_meta` presente y válido**:
   - Formato nuevo (V3+): `motor` (AUTONOMO|ASISTIDO), `plataforma` (no vacío), `modelo` (no vacío), `timestamp` (ISO 8601), `version_protocolo`
   - Formato legacy (aceptado): `motor`, `agente` (no vacío), `timestamp`, `version_protocolo`; `motor=DUAL_MODELO` con `modo_dual` presente
8. **Rangos**: campos `_0_1` en [0,1], campos `_0_5` en [0,5], campos `probabilidad` en [0,1]
9. **Enums sin pipe** (`|`)
10. **Idioma**: sin texto en inglés, portugués u otros mezclados

### Validación cross-artefacto (obligatoria en ÁRBITRO)

> **Timing:** Los checks cross-artefacto completos solo se ejecutan en el Step 8 (ARBITRO), cuando todos los artefactos estan disponibles. Opcionalmente, tras Steps 1 y 2 se pueden verificar: (a) que `empresa.ticker` sea consistente entre SourcesPack y TruthPack, (b) que `source_ids` referenciados en TruthPack existan en SourcesPack.

1. **Confianza consistency**: `input_refs[].confianza_0_1` debe coincidir con `resumen_ejecutivo.confianza_0_1` de cada AgentReport
2. **source_id cross-ref**: IDs referenciados deben existir en SourcesPack
3. **Cifras financieras**: revenue, FCF, EV, market cap deben ser idénticas en TruthPack, ImpliedExpectations y AgentReports (tolerancia <2%)
4. **Kill criteria traceability**: cada `kc_id` debe tener `relacionado_con_assumption_id` que exista en `assumption_ledger`
5. **Probabilidades escenarios**: deben sumar 1.0 (±0.05)
6. **Scoring aritmética**: si hay componentes desglosados, deben sumar el total declarado

### Correcciones automáticas permitidas

| Problema | Corrección |
|----------|-----------|
| URLs Markdown | Extraer URL raw |
| Escala en miles/millones | Multiplicar y cambiar escala a "1" |
| caso_id/fecha_corte incorrectos | Corregir al valor esperado |
| `confianza_0_1` en escala 0-5 | Dividir entre 5 |
| Enum pipe-separated | Tomar primer valor |
| Grid duplicada | Deduplicar filas |

Siempre registrar correcciones en CHANGELOG.

### Reglas de integridad para subagentes

Estas reglas **deben incluirse** en el prompt de cada subagente (CATALYST, FORENSIC, BULL, RED_TEAM):

```
REGLAS DE INTEGRIDAD OBLIGATORIAS:
1. ESCALA: Todo campo _0_1 en [0,1]. Todo campo _0_5 en [0,5].
2. IDIOMA: TODO el texto en español.
3. CAMPOS OBLIGATORIOS: resumen_ejecutivo, claims, payload, predicciones_calibracion, peticiones_de_fuentes, log.
4. ENUMS: valor único, NUNCA separados por pipe (|).
5. SOURCE_IDS: solo IDs existentes en SourcesPack.
6. FALSACIÓN: cada claim DEBE tener test observable con ventana_meses y fuente_prevista.
7. NO DUPLICAR: aportar perspectiva diferente al resto de agentes.
```

---

## §4 ACTUALIZACIÓN DE ESTADO

Después de cada paso completado, actualizar **tres** archivos:

### 4.1 `_estado.json` (por caso)

Actualizar el archivo `_estado.json` en el directorio del caso (`casos/{T}/{D}_{M}/_estado.json`):

1. Leer `_estado.json` existente (o crear si no existe — ver plantilla en `_schemas/estado/caso_estado_v1.json`)
2. Actualizar campos:
   - `pipeline.{STEP}.estado` → `"DONE"`
   - `pipeline.{STEP}.artefacto` → nombre del archivo guardado
   - `_meta.ultima_actualizacion` → timestamp actual ISO 8601
   - `_meta.actualizado_por` → identificador del agente/motor
3. Si es ÁRBITRO: además actualizar `decision`, `score`, `confianza`, `probabilistica`, `next_step`, `proxima_revision`, `estado_pipeline` → `"COMPLETO"`. **Auditoría obligatoria:** tras guardar, ejecutar `python3 scripts/case_quality_audit.py --ticker {T} --date {D}`. Si resultado FAIL → cambiar `estado_pipeline` → `"QUARANTINE"`, `next_step` → `"RE-HACER"`, y añadir bloque `auditoria_YYYY_MM_DD` con veredicto y motivo.
4. Si es MONITOR: append a array `monitoring[]`, actualizar `proxima_revision`
5. Guardar `_estado.json` (pretty-print, ensure_ascii=False)

**NOTA:** `ESTADO_REPO.json` ya NO contiene datos de casos individuales. Solo contiene metadatos globales (scout, scanner). Para operaciones de SCOUT o SCANNER que actualizan secciones globales, seguir modificando `ESTADO_REPO.json` directamente.

### 4.2 CHANGELOG.md

- Tabla de estado del pipeline: marcar step como `✅ DONE` con fecha y notas
- Historial de cambios: entrada bajo la fecha del día con artefacto, métricas clave, issues

### 4.3 _docs/FECHAS_CLAVE.md (solo después de ÁRBITRO, MONITOR u OUTCOME)

| Evento | Qué actualizar |
|--------|---------------|
| Pipeline completado | Añadir caso al resumen rápido + calendario + kill criteria |
| MONITOR ejecutado | Actualizar próxima revisión, score/confianza si cambiaron |
| OUTCOME ejecutado | Marcar caso como CERRADO, eliminar fechas futuras |

---

## §5 BUGS CONOCIDOS POR AGENTE

### TRUTH_PACK
- Escala incorrecta (miles en vez de absolutos). Verificar siempre.
- TTM mal calculado. Fórmula: `TTM = FY + período_parcial_actual - período_parcial_año_anterior`
- `metricas_derivadas.nota` ausente (requerido por V5)
- `data_quality` FAIL → intentar corregir antes de continuar

### IMPLIED
- Grid duplicada con método exit_multiple (no varía con crecimiento_terminal)
- Inconsistencia EBIT vs EBITA. Usar EBIT.

### CATALYST / BULL
- Claims duplicados entre ambos agentes. BULL = valoración/escenarios, CATALYST = timing/catalizadores.
- `peticiones_de_fuentes` omitido. Es OBLIGATORIO.

### BULL
- `confianza_0_1` en escala 0-5 en vez de 0-1. Bug crítico recurrente.
- `conviccion_preliminar_0_5` SÍ va en escala 0-5 (es el único).

### RED_TEAM
- `riesgo_principal` pipe-separated. Debe ser valor único.
- Claims con estructura no-estándar (usar `falsacion`, no `evaluacion_red_team`)

### FORENSIC
- Texto en portugués en claims. Verificar idioma.

### ÁRBITRO
- Propaga bugs de `confianza_0_1` de AgentReports sin verificar rango.
- Usa `payload.diagnostico_global.confianza_0_1` en vez de `resumen_ejecutivo.confianza_0_1`.

---

## §6 MANEJO DE ERRORES

| Situación | Acción |
|-----------|--------|
| JSON no parseable | Regenerar artefacto |
| Campos faltantes | Completar si es determinista, si no informar al usuario |
| TRUTH_PACK data_quality FAIL | Intentar corregir, si no preguntar al usuario |
| Artefacto previo necesario no existe | Bloquear y preguntar |
| ÁRBITRO emite REMEDIATE | Seguir protocolo REMEDIATE del manual (`_docs/MANUAL_ELSIAN_INVEST.md`) |
| Sesión se agota a mitad de pipeline | Guardar todo, actualizar CHANGELOG/`_estado.json`, commit de seguridad (§7), retomar con modo CONTINUAR |

---

## §7 PROTOCOLO GIT

### Regla general

Git se usa para capturar unidades de trabajo coherentes. Los commits intermedios de steps individuales están PROHIBIDOS.

### Puntos de commit obligatorio

| Evento | Cuándo | Formato del mensaje |
|--------|--------|---------------------|
| Pipeline completo | Después de guardar DecisionPacket + actualizar estado | `Pipeline {T}: {DECISIÓN} (score {N}/100)` |
| SCOUT completo | Después de guardar CandidateList merged | `Scout {D}: batch {N} candidatos` |
| MONITOR ejecutado | Después de guardar MonitoringUpdate | `Monitor {T}: {BANDERA} (rev #{N})` |
| OUTCOME ejecutado | Después de guardar OutcomeRecord | `Outcome {T}: {ESTADO}` |
| EVALUADOR ejecutado | Después de guardar CalibrationReport | `Calibración {D}: {N} casos evaluados` |
| Benchmark completo | Después de comparar dos análisis inter-modelo | `Benchmark {T}: {MODELO_A} vs {MODELO_B} (ganador: {GANADOR})` |
| Cambio estructural | Tras modificar instrucciones, schemas o configuración | Descriptivo libre |

### Sesión agotada a mitad de pipeline

Si la sesión se va a agotar a mitad de pipeline:

1. Guardar todos los artefactos completados
2. Actualizar `_estado.json` del caso y CHANGELOG
3. El operador hará commit con mensaje: `[WIP] {T}: steps 1-{N} completados, pendiente desde {SIGUIENTE}`

### Qué NO hacer commit

- Steps intermedios del pipeline (cada SOURCES, TRUTH_PACK, etc. por separado)
- Archivos temporales o de pruebas
- Artefactos parciales o con validación FAIL no resuelta

### Qué incluir en cada commit

Siempre incluir juntos:
- Los artefactos generados (JSON en `casos/{T}/{D}_{M}/`, incluyendo `_estado.json`)
- `CHANGELOG.md`
- `_docs/FECHAS_CLAVE.md` (si se actualizó)
- `_benchmark/comparaciones.json` (si es BENCHMARK)
- Archivos de `candidatos/` o `_scout/` (si es SCOUT)

### Responsabilidad del commit

El commit git lo ejecuta **el operador** (el propio agente en Claude Code/Codex/Gemini CLI, o el usuario en modo asistido).

**Flujo correcto:**

1. El agente genera artefactos, actualiza `_estado.json` del caso, CHANGELOG.md y FECHAS_CLAVE.md
2. El agente **NO intenta ejecutar `git add` ni `git commit`** (a menos que opere en un entorno con acceso git)
3. El operador revisa y ejecuta el commit cuando sea conveniente

**Ejemplo de commit:**

```bash
git add casos/{T}/{D}_{M}/ CHANGELOG.md _docs/FECHAS_CLAVE.md
git commit -m "Pipeline {T}: INVERTIR (score 82/100)"
```

---

## §8 RESUMEN FINAL AL USUARIO

Obligatorio después de cada punto de cierre. Se muestra en conversación, NO se guarda como artefacto.

### Pipeline completo → Markdown completo
Extraer del DecisionPacket: veredicto, score, confianza, gates, escenarios, kill criteria, próximos pasos.

### MONITOR → Tabla compacta
Decisión actual, bandera, score (delta), KC activados, próxima revisión, acción recomendada.

### OUTCOME → Tabla compacta
Estado, retorno realizado, holding period, acierto tesis, lección principal.

### EVALUADOR → Markdown completo
Casos evaluados, accuracy predicciones, sesgo, Brier score, sesgos por agente, recomendaciones.
