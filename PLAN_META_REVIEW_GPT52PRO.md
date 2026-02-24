# Plan de Implementación: Meta-Review con GPT-5.2 Pro vía Proyecto ChatGPT

**Fecha:** 2026-02-23
**Versión del plan:** 1.2
**Autor:** Claude Opus (revisado por Codex + Elsian)
**Estado:** v1.2 — 6 incoherencias residuales de Codex corregidas. Listo para implementación.

---

## 1. Contexto y Objetivo

### 1.1 Problema
El pipeline ELSIAN-INVEST 3.0 ejecuta análisis multi-modelo (Claude, Codex, Gemini) de forma automatizada. El paso final (ARBITRO) consolida todo en un `DecisionPacket_v2` con decisión categórica + probabilística. Sin embargo, no existe una capa de supervisión que cuestione la calidad del razonamiento del ARBITRO con la profundidad que requiere una decisión de inversión real.

### 1.2 Oportunidad
La suscripción ChatGPT Pro ($200/mes) incluye acceso ilimitado a GPT-5.2 Pro, posiblemente el mejor modelo de razonamiento complejo del mercado. Este acceso es exclusivamente a través de la interfaz web de ChatGPT, no por API, pero la funcionalidad de **Proyectos de ChatGPT** permite configurar instrucciones persistentes y ficheros adjuntos que contextualizan todas las conversaciones dentro del proyecto.

### 1.3 Objetivo
Crear un sistema semi-automatizado donde:
1. El operador ejecuta un comando que genera un **prompt de review compilado** para un caso completado
2. El operador lo pega en el **Proyecto ChatGPT** configurado para ELSIAN-INVEST
3. GPT-5.2 Pro produce un **meta-review estructurado**
4. El operador copia la respuesta de vuelta al sistema
5. Un script de ingesta **parsea y persiste** el review como artifact del caso

**Coste adicional:** Cero (incluido en suscripción Pro existente).

---

## 2. Arquitectura General

```
┌─────────────────────────────────────────────────────────────┐
│                   PIPELINE AUTOMATIZADO                      │
│  SOURCES → TRUTH_PACK → IMPLIED → CATALYST ∥ FORENSIC      │
│  → BULL → RED_TEAM → ARBITRO → DecisionPacket_v2           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              REVIEW COMPILER (ejecución explícita)            │
│  python3 -m engine review TICKER [--date YYYY-MM-DD]        │
│                                                              │
│  Lee: _estado.json + artifacts fusionados + DecisionPacket   │
│  Genera: _review_prompt_gpt52pro_{TS}.md (en dir del caso)  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼  (operador copia al proyecto ChatGPT)
┌──────────────────────────────────────────────────────────────┐
│              PROYECTO CHATGPT "ELSIAN Meta-Review"           │
│                                                              │
│  Instrucciones del proyecto: metodología + criterios review  │
│  Ficheros adjuntos: schemas + docs de referencia             │
│  Modelo: GPT-5.2 Pro                                        │
│                                                              │
│  Input: prompt compilado (pegado por operador)               │
│  Output: meta-review estructurado (copiado por operador)     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼  (operador pega respuesta en fichero)
┌──────────────────────────────────────────────────────────────┐
│              REVIEW INGEST (automático)                       │
│  python3 -m engine review_ingest TICKER [--date YYYY-MM-DD] │
│                                                              │
│  Lee: _review_response_raw_{TS}.md (pegado por operador)     │
│  Parsea: extrae JSON estructurado del bloque de respuesta    │
│  Genera: MetaReview_v1_TICKER_DATE.json                      │
│  Actualiza: _estado.json con metadata del review             │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Componente A: Proyecto ChatGPT (configuración única)

### 3.1 Datos del proyecto

| Campo | Valor |
|-------|-------|
| Nombre | `ELSIAN Meta-Review` |
| Modelo | GPT-5.2 Pro |
| Idioma | Español |

### 3.2 Instrucciones del proyecto

Las instrucciones del proyecto se almacenan en un fichero generado automáticamente que el operador pega en la configuración del proyecto ChatGPT. El generador vive en el sistema y se regenera cuando cambia la metodología.

**Contenido de las instrucciones del proyecto** (estructura, no texto final):

```
SECCIÓN 1: IDENTIDAD Y ROL
- Eres el Meta-Revisor del comité de inversión ELSIAN-INVEST
- Tu rol: auditar las decisiones del ARBITRO automatizado
- NO sustituyes al ARBITRO — lo supervisas
- Tu valor: razonamiento profundo, detección de puntos ciegos, coherencia lógica

SECCIÓN 2: CONTEXTO DEL PIPELINE
- Descripción concisa de cada paso (SOURCES → ... → ARBITRO)
- Qué hace cada agente y qué produce
- Cómo funciona la fusión multi-modelo
- Qué es el DecisionPacket_v2 y sus secciones clave

SECCIÓN 3: CRITERIOS DE REVIEW
- Coherencia lógica: ¿las conclusiones se sostienen con las evidencias?
- Rigurosidad de gates: ¿los 5 gates se evaluaron correctamente?
- Calidad de supuestos: ¿los supuestos críticos tienen evidencia Y test de falsación?
- Realismo de escenarios: ¿BASE/BULL/BEAR son creíbles?
- Coherencia probabilística ↔ categórica (tabla A12 del ARBITRO)
- Sizing Kelly: ¿el cálculo es correcto? ¿el sizing final es prudente?
- Puntos ciegos: ¿qué no se ha considerado?
- Desacuerdos: ¿se resolvieron bien los conflictos entre agentes?
- Kill criteria: ¿son observables, específicos y accionables?

SECCIÓN 4: FORMATO DE RESPUESTA OBLIGATORIO
- Análisis narrativo libre (sin límite, profundidad máxima)
- Al final: bloque JSON delimitado por ```json ... ```
- El JSON sigue el schema MetaReview_v1 (adjunto en ficheros del proyecto)

SECCIÓN 5: REGLAS ABSOLUTAS
- Todo en español
- No inventar datos — si no tienes información, di "no evaluable"
- Citar secciones específicas del DecisionPacket cuando critiques
- Ser directo y constructivo — señalar problemas, no adular
- Si la decisión del ARBITRO es correcta, decirlo brevemente y enfocarse en mejoras
```

### 3.3 Ficheros adjuntos al proyecto

Los ficheros se generan automáticamente por el sistema y se actualizan cuando cambian los schemas o la metodología.

| # | Fichero | Contenido | Tamaño aprox. |
|---|---------|-----------|---------------|
| 1 | `MetaReview_v1_SCHEMA.json` | Schema del output esperado (NUEVO) | ~3 KB |
| 2 | `DecisionPacket_v2_SCHEMA.json` | Schema del DP para referencia | ~15 KB |
| 3 | `AgentReport_v1_SCHEMA.json` | Schema de los reports de agentes | ~8 KB |
| 4 | `METODOLOGIA_ELSIAN.md` | Resumen de la metodología de inversión | ~5 KB |
| 5 | `CRITERIOS_REVIEW.md` | Guía detallada de criterios de evaluación | ~4 KB |
| 6 | `REGLAS_COMUNES_EXTRACTO.md` | Extracto de reglas relevantes para review | ~3 KB |

**Total estimado:** ~38 KB en ficheros adjuntos.
**Nota:** ChatGPT Projects permite hasta 20 ficheros y acepta .json y .md sin problemas.

### 3.4 Generador del paquete de proyecto

**Fichero:** `scripts/review/generate_project_package.py`

**Función:** Lee los schemas actuales, las instrucciones, y genera un directorio `_review_project/` con todos los ficheros listos para subir al proyecto ChatGPT.

**Ejecución:**
```bash
python3 scripts/review/generate_project_package.py
```

**Output:**
```
_review_project/
├── INSTRUCCIONES_PROYECTO.md      ← Para pegar en instrucciones del proyecto
├── MetaReview_v1_SCHEMA.json      ← Adjuntar al proyecto
├── DecisionPacket_v2_SCHEMA.json  ← Adjuntar al proyecto
├── AgentReport_v1_SCHEMA.json     ← Adjuntar al proyecto
├── METODOLOGIA_ELSIAN.md          ← Adjuntar al proyecto
├── CRITERIOS_REVIEW.md            ← Adjuntar al proyecto
├── REGLAS_COMUNES_EXTRACTO.md     ← Adjuntar al proyecto
└── _manifest.json                 ← Versiones de schemas usadas (para detectar cambios)
```

**Detección de cambios:** El `_manifest.json` almacena hashes SHA-256 de cada schema fuente. Al ejecutar el generador, compara con los hashes actuales y avisa si hay cambios que requieran actualizar el proyecto ChatGPT.

---

## 4. Componente B: Review Compiler (generación por caso)

### 4.1 Módulo principal

**Fichero:** `engine/review_compiler.py`

**Función pública:** `compile_review_prompt(case_dir: Path, output_path: Path | None = None) -> Path`

### 4.2 Lógica de compilación

El compilador lee los artifacts del caso y genera un prompt markdown optimizado para GPT-5.2 Pro.

#### 4.2.1 Selección de artifacts a incluir

| Artifact | Incluir | Formato | Justificación |
|----------|---------|---------|---------------|
| DecisionPacket_v2 | **SÍ, COMPLETO** | JSON inline | Es el objeto central del review |
| AgentReport_v1 BULL (fusionado) | **SÍ, resumen ejecutivo + claims** | JSON parcial | Perspectiva alcista |
| AgentReport_v1 RED_TEAM (fusionado) | **SÍ, resumen ejecutivo + claims** | JSON parcial | Perspectiva crítica |
| AgentReport_v1 CATALYST (fusionado) | **SÍ, solo resumen ejecutivo** | Texto | Contexto de catalizadores |
| AgentReport_v1 FORENSIC (fusionado) | **SÍ, solo resumen ejecutivo** | Texto | Contexto forense |
| TruthPack_v1 | **NO** | — | Datos brutos, ya integrados en DP |
| ImpliedExpectations_v1 | **SÍ, solo grid de expectativas** | Tabla | Referencia de valoración implícita |
| SourcesPack_v1 | **NO** | — | Demasiado volumen, ya referenciado |
| _multi_* individuales | **NO** | — | Redundante con fusionados |
| _votes (quality) | **SÍ, resumen** | Texto | Confianza del sistema en cada paso |

**Tamaño estimado del prompt compilado:** ~80-120 KB por caso (dentro de las capacidades de GPT-5.2 Pro).

#### 4.2.2 Estructura del prompt compilado

```markdown
# Meta-Review: {TICKER} — {FECHA}

## Contexto del caso
- Ticker: {TICKER}
- Fecha de análisis: {FECHA}
- Pipeline completado: {TIMESTAMP}
- Modelos utilizados: {LISTA_MODELOS}
- Decisión ARBITRO: {DECISION} (score: {SCORE}/100, confianza: {CONFIANZA})

## Calidad del pipeline (quality votes)
{TABLA_RESUMEN_VOTES: paso | score_fusión | score_mejor_modelo | score_peor_modelo}

---

## Expectativas implícitas del mercado
{GRID_IMPLIED_EXPECTATIONS: tabla con métricas clave}

---

## Perspectiva BULL (resumen + claims)
### Resumen ejecutivo
{RESUMEN_BULL}
### Claims principales (solo CRITICO e IMPORTANTE)
{CLAIMS_BULL_FILTRADOS}

---

## Perspectiva RED_TEAM (resumen + claims)
### Resumen ejecutivo
{RESUMEN_RED_TEAM}
### Claims principales (solo CRITICO e IMPORTANTE)
{CLAIMS_RED_TEAM_FILTRADOS}

---

## Perspectiva CATALYST (resumen)
{RESUMEN_CATALYST}

---

## Perspectiva FORENSIC (resumen)
{RESUMEN_FORENSIC}

---

## DecisionPacket completo (ARBITRO)
```json
{DECISION_PACKET_V2_COMPLETO}
```

---

## Solicitud de review

Revisa este caso aplicando los criterios definidos en las instrucciones del proyecto.

Áreas de especial atención para este caso:
{ALERTAS_ESPECIFICAS — generadas automáticamente, ver §4.2.3}

Recuerda finalizar tu análisis con el bloque JSON MetaReview_v1.
```

#### 4.2.3 Generación automática de alertas específicas

El compilador analiza el DecisionPacket y genera alertas contextuales que dirigen la atención de GPT-5.2 Pro:

| Condición detectada | Alerta generada |
|---------------------|-----------------|
| Algún gate es CONDITIONAL (no PASS ni FAIL) | "El gate {X} es CONDITIONAL — evalúa si la justificación es suficiente para no bloquearlo" |
| `confianza` < 0.5 | "La confianza global es baja ({X}) — investiga si es por falta de datos o por debilidad de la tesis" |
| `ratio_asimetria` < 1.0 | "La asimetría es desfavorable ({X}) — el downside supera al upside base" |
| Hay desacuerdos NO_RESUELTO en arbitraje | "Hay {N} desacuerdos no resueltos entre agentes — evalúa si la resolución parcial es aceptable" |
| `sizing_final_pct` está al tope (10%) | "El sizing está al máximo permitido (10%) — evalúa si la convicción justifica la concentración" |
| Supuestos CRITICOS sin test de falsación | "Hay {N} supuestos críticos sin test de falsación definido" |
| Decisión WATCHLIST con score > 70 | "Score alto ({X}) pero decisión WATCHLIST — posible incoherencia" |
| Decisión INVERTIR con score < 50 | "Score bajo ({X}) pero decisión INVERTIR — posible incoherencia" |
| `probabilidad_exito` > 0.8 o < 0.2 | "Probabilidad extrema ({X}) — evalúa si hay suficiente evidencia para una convicción tan fuerte" |

### 4.3 Integración CLI

**Nuevo subcomando en `engine.py`:**

```bash
python3 -m engine review TICKER [--date YYYY-MM-DD]
```

**Comportamiento:**
1. Resuelve el `case_dir` (última fecha si no se especifica)
2. Valida que el pipeline esté COMPLETO (`estado_pipeline == "COMPLETO"`)
3. Genera timestamp (`TS` = `YYYYMMDDTHHMMSS`)
4. Llama a `compile_review_prompt(case_dir)`
5. Guarda el prompt en `{case_dir}/_review_prompt_gpt52pro_{TS}.md`
6. Actualiza `_estado.json` → `meta_review.prompt_timestamp = TS`
7. Imprime en consola:
   ```
   ✓ Prompt de review generado: casos/TZOO/2026-02-21/_review_prompt_gpt52pro_20260223T143022.md

   Siguiente paso:
   1. Abre el proyecto "ELSIAN Meta-Review" en ChatGPT
   2. Pega el contenido del fichero como mensaje
   3. Espera la respuesta de GPT-5.2 Pro
   4. Copia la respuesta completa a: casos/TZOO/2026-02-21/_review_response_raw_20260223T143022.md
   5. Ejecuta: python3 -m engine review_ingest TZOO --date 2026-02-21
   ```

### 4.4 Subcomando de estado

```bash
python3 -m engine review_status [TICKER] [--date YYYY-MM-DD]
```

**Output (sin ticker — todos los casos):**
```
Caso          Pipeline   Prompt     Respuesta   Ingesta    Veredicto
TZOO 02-21    COMPLETO   ✓ 02-23   ✓ 02-23     ✓ 02-23   CUESTIONA
SOM  02-20    COMPLETO   ✓ 02-22   —            —         —
ACVA 02-19    COMPLETO   —          —            —         —
```

### 4.5 Manejo de errores del compilador

| Error | Acción |
|-------|--------|
| `estado_pipeline != "COMPLETO"` | Abortar con mensaje: "Pipeline no completado. Ejecuta: python3 -m engine continue TICKER" |
| DecisionPacket_v2 no encontrado | Buscar por patrón `DecisionPacket_v2_*` en case_dir; si no existe, abortar |
| AgentReport fusionado incompleto | Degradación: incluir solo resumen ejecutivo disponible, marcar sección como "[ARTIFACT INCOMPLETO]" |
| Prompt resultante > 150 KB | Truncar claims de IMPORTANT a solo enunciado (sin evidencias), advertir en consola |
| _estado.json corrupto o faltante | Abortar con mensaje claro |

### 4.6 Estrategia de truncación

Si el prompt compilado excede 150 KB (umbral de calidad para GPT-5.2 Pro):

1. **Nivel 1** (120-150 KB): Reducir claims IMPORTANT a solo enunciado + confianza (sin grid de evidencias)
2. **Nivel 2** (>150 KB): Excluir resúmenes de CATALYST y FORENSIC, mantener solo BULL + RED_TEAM + DecisionPacket
3. **Nivel 3** (>200 KB, edge case extremo): Excluir claims individuales de agentes, mantener solo resúmenes ejecutivos + DecisionPacket completo

Cada nivel de truncación se indica en el prompt: `[NOTA: Este prompt ha sido compactado (nivel N). Algunos detalles de agentes intermedios se han omitido por extensión.]`

---

## 5. Componente C: Schema MetaReview_v1

### 5.1 Ubicación

**Fichero:** `_schemas/review/MetaReview_v1.json`

### 5.2 Estructura del schema

```json
{
  "version_esquema": "MetaReview_v1",
  "caso_id": "CASE_YYYYMMDD_TICKER",
  "fecha_review": "ISO 8601",
  "reviewer": {
    "modelo": "gpt-5.2-pro",
    "plataforma": "chatgpt",
    "proyecto": "ELSIAN Meta-Review"
  },
  "decision_packet_ref": "DecisionPacket_v2_TICKER_DATE_Engine.json",
  "decision_packet_snapshot": {
    "hash_sha256": "string (hash del DP usado para compilar el review)",
    "timestamp_compilacion": "ISO 8601",
    "revision_num": 1
  },

  "veredicto_meta": {
    "estado": "CONFIRMA | CUESTIONA | RECHAZA | NO_EVALUABLE",
    "confianza_review_0_1": 0.0,
    "resumen_1_parrafo": "string"
  },

  "evaluacion_gates": [
    {
      "gate": "data_quality_gate | survivability_gate | mispricing_gate | catalyst_gate | non_speculative_gate",
      "arbitro_dijo": "PASS | CONDITIONAL | FAIL",
      "meta_evaluacion": "CORRECTO | CUESTIONABLE | INCORRECTO",
      "justificacion": "string (1-3 frases)",
      "riesgo_oculto": "string | null"
    }
  ],

  "evaluacion_supuestos_criticos": [
    {
      "assumption_id": "A-XXX",
      "enunciado": "string",
      "arbitro_probabilidad": 0.0,
      "meta_evaluacion": "RAZONABLE | OPTIMISTA | PESIMISTA | INSUFICIENTE_EVIDENCIA",
      "justificacion": "string",
      "sugerencia_probabilidad_0_1": 0.0
    }
  ],

  "evaluacion_escenarios": {
    "base": {
      "arbitro_probabilidad": 0.0,
      "arbitro_retorno": 0.0,
      "meta_evaluacion": "REALISTA | OPTIMISTA | PESIMISTA",
      "justificacion": "string"
    },
    "bull": { "..." : "misma estructura" },
    "bear": { "..." : "misma estructura" }
  },

  "evaluacion_sizing": {
    "kelly_ajustado_arbitro": 0.0,
    "sizing_final_arbitro": 0.0,
    "meta_evaluacion": "ADECUADO | EXCESIVO | CONSERVADOR",
    "justificacion": "string",
    "sizing_sugerido_0_1": 0.0
  },

  "coherencia_logica": {
    "score_0_10": 0,
    "problemas_detectados": [
      {
        "tipo": "CONTRADICCION | SALTO_LOGICO | EVIDENCIA_DEBIL | SESGO | OMISION",
        "descripcion": "string",
        "seccion_afectada": "string (referencia al DP)",
        "severidad": "ALTA | MEDIA | BAJA"
      }
    ]
  },

  "puntos_ciegos": [
    {
      "descripcion": "string",
      "impacto_potencial": "ALTO | MEDIO | BAJO",
      "sugerencia": "string"
    }
  ],

  "coherencia_probabilistica_categorica": {
    "alineadas": true,
    "incongruencias": ["string | null"],
    "justificacion": "string"
  },

  "evaluacion_calidad_pipeline": [
    {
      "paso": "string (nombre del paso)",
      "score_fusion": 0.0,
      "evaluacion_meta": "ADECUADO | PREOCUPANTE | INSUFICIENTE",
      "comentario": "string | null"
    }
  ],

  "alertas_compilador_respondidas": [
    {
      "alerta_original": "string (alerta generada automáticamente por el compilador)",
      "respuesta_gpt": "string (evaluación de GPT-5.2 Pro sobre esta alerta)"
    }
  ],

  "desacuerdos_agentes": {
    "resolucion_arbitro_correcta": true,
    "desacuerdos_mal_resueltos": [
      {
        "tema": "string",
        "problema": "string",
        "sugerencia": "string"
      }
    ],
    "comentarios": "string | null"
  },

  "kill_criteria_evaluacion": {
    "completos": true,
    "accionables": true,
    "especificos": true,
    "cubren_bear_scenario": true,
    "comentarios": "string | null"
  },

  "recomendaciones": [
    {
      "prioridad": "ALTA | MEDIA | BAJA",
      "accion": "string",
      "dirigida_a": "ARBITRO | PIPELINE | OPERADOR"
    }
  ],

  "meta_decision": {
    "accion": "APROBAR | APROBAR_CON_CONDICIONES | REVISAR_MANUALMENTE | RECHAZAR",
    "condiciones": ["string"],
    "siguiente_paso_sugerido": "string"
  }
}
```

### 5.3 Notas de diseño del schema

- **`veredicto_meta.estado`**: No es una decisión de inversión — es una evaluación de la calidad de la decisión del ARBITRO. `CONFIRMA` = el review no encuentra problemas significativos. `CUESTIONA` = hay dudas que deberían investigarse. `RECHAZA` = hay errores graves que invalidan la decisión.
- **`evaluacion_supuestos_criticos`**: Solo evalúa los supuestos marcados como `CRITICO` en el assumption_ledger. No repite los `IMPORTANTE` o `CONTEXTUAL` por economía de atención.
- **`sugerencia_probabilidad_0_1`**: GPT-5.2 Pro puede sugerir una probabilidad alternativa, pero NO es vinculante — es una señal para el operador.
- **`meta_decision.accion`**: `APROBAR` y `APROBAR_CON_CONDICIONES` no requieren acción inmediata. `REVISAR_MANUALMENTE` sugiere que el operador dedique tiempo adicional. `RECHAZAR` sugiere re-ejecutar el pipeline o el paso ARBITRO.

---

## 6. Componente D: Review Ingest (ingesta de respuesta)

### 6.1 Módulo

**Fichero:** `engine/review_ingest.py`

**Función pública:** `ingest_review(case_dir: Path, response_path: Path | None = None) -> Path`

### 6.2 Flujo de ingesta

```
1. Lee prompt_timestamp de _estado.json → meta_review.prompt_timestamp (TS)
2. Busca: {case_dir}/_review_response_raw_{TS}.md
   - Si no existe, busca el _review_response_raw_*.md más reciente
   - Si no existe ninguno, abortar con mensaje
3. Busca el bloque ```json ... ``` en el texto
4. Parsea el JSON
5. Valida contra schema MetaReview_v1
6. Inyecta _meta:
   {
     "motor": "ASISTIDO",
     "plataforma": "chatgpt",
     "modelo": "gpt-5.2-pro",
     "proyecto_chatgpt": "ELSIAN Meta-Review",
     "timestamp": "ISO 8601 (momento de ingesta)",
     "version_protocolo": "V3"
   }
7. Guarda: {case_dir}/MetaReview_v1_{TICKER}_{DATE}.json
8. Guarda narrativa completa: {case_dir}/_review_narrative_gpt52pro_{TS}.md
9. Actualiza _estado.json:
   - Añade campo "meta_review": {
       "estado": "DONE",
       "artefacto": "MetaReview_v1_TICKER_DATE.json",
       "veredicto": "CONFIRMA|CUESTIONA|RECHAZA|NO_EVALUABLE",
       "meta_decision": "APROBAR|APROBAR_CON_CONDICIONES|...",
       "prompt_timestamp": "TS",
       "timestamp": "ISO 8601"
     }
10. Imprime resumen en consola
```

### 6.3 Manejo de errores

| Error | Acción |
|-------|--------|
| No se encuentra bloque JSON | Intento de extracción con regex más permisivos (````json`, `{` inicial, etc.); si falla, guardar solo narrativa como `_review_narrative_gpt52pro_{TS}.md` y marcar estado como `PARCIAL` |
| JSON no válido | Mostrar error de parseo con línea aproximada; sugerir corrección manual del fichero |
| Schema validation fail | Modo permisivo: rellenar campos faltantes opcionales con `null`, guardar con warning; solo abortar si faltan campos requeridos (`veredicto_meta`, `meta_decision`) |
| No se encuentra `_review_response_raw_{TS}.md` | Mensaje: "Copia la respuesta de GPT-5.2 Pro a: {case_dir}/_review_response_raw_{TS}.md" (donde TS es el prompt_timestamp almacenado en _estado.json) |
| GPT-5.2 Pro rechaza evaluar | Añadir estado `NO_EVALUABLE` al enum de `veredicto_meta.estado`; persistir la narrativa explicativa |
| Hash del DP no coincide (DP fue re-ejecutado tras generar prompt) | Warning: "El DecisionPacket ha cambiado desde que se generó el prompt. Regenera: python3 -m engine review TICKER" |

### 6.4 Integración CLI

```bash
python3 -m engine review_ingest TICKER [--date YYYY-MM-DD]
```

**Output esperado:**
```
✓ MetaReview ingestado: MetaReview_v1_TZOO_20260221.json
  Veredicto: CUESTIONA
  Meta-decisión: APROBAR_CON_CONDICIONES
  Condiciones: ["Verificar margen operativo Q1 antes de sizing definitivo"]
  Problemas detectados: 2 (1 ALTA, 1 MEDIA)
  _estado.json actualizado
```

---

## 7. Componente E: Integración en Decisions (NO en Dashboard)

> **Nota v1.2 (corrección Codex #1):** La visualización de meta-review va en `generate_decisions()` (subcomando `decisions`), NO en `generate_dashboard()` (subcomando `dashboard`). El dashboard muestra estado de pipeline; decisions muestra decisiones de arbitraje. El meta-review es una extensión de la decisión.

### 7.1 Cambios en `engine/dashboard.py` → función `generate_decisions()`

El subcomando `decisions` debe mostrar el estado del meta-review para cada caso.

**En nivel 0 (`python3 -m engine decisions`):**
```
TZOO  WATCHLIST  62  →2026-04-15 (EN_ESPERA) [MR:CUESTIONA]
SOM   INVERTIR   78  →2026-03-15 (ACTIVO)    [MR:CONFIRMA]
ACVA  DESCARTAR  31  →—                       [MR:—]
```

Donde `[MR:X]` indica (mapeo explícito `veredicto_meta.estado` → tag display):

| `veredicto_meta.estado` | Tag display | Significado |
|--------------------------|-------------|-------------|
| `CONFIRMA` | `MR:CONFIRMA` | Review completado, decisión confirmada |
| `CUESTIONA` | `MR:CUESTIONA` | Review completado, hay dudas significativas |
| `RECHAZA` | `MR:RECHAZA` | Review completado, errores graves detectados |
| `NO_EVALUABLE` | `MR:NO_EVAL` | GPT-5.2 Pro no pudo evaluar (datos insuficientes, etc.) |
| *(no existe)* | `MR:—` | No se ha realizado review |
| *(prompt generado, sin ingesta)* | `MR:PEND` | Prompt generado pero respuesta no ingestada aún |

**En nivel 1 (detalle, con `decisions -v`):**
```
│  Meta-Review: CUESTIONA (gpt-5.2-pro, 2026-02-23)
│  Meta-decisión: APROBAR_CON_CONDICIONES
│  Problemas: 2 (1 ALTA severidad)
│  Condición: Verificar margen operativo Q1 antes de sizing definitivo
```

### 7.2 Lógica de detección

`_extract_decision_info()` ya lee `_estado.json`. Se extiende para leer el campo `meta_review` si existe. El tag `[MR:X]` se renderiza después del tag de estado de caso existente (`EN_ESPERA`, `ACTIVO`, etc.).

---

## 8. Componente F: Generador de documentación del proyecto

### 8.1 METODOLOGIA_ELSIAN.md (fichero adjunto al proyecto)

Documento auto-generado que resume la metodología para GPT-5.2 Pro:

```markdown
# Metodología ELSIAN-INVEST 3.0

## Pipeline de análisis
El pipeline analiza oportunidades de inversión en renta variable...

### Pasos del pipeline
1. **SOURCES**: Recopilación de fuentes (SEC filings, transcripts, market data)
2. **TRUTH_PACK**: Extracción y validación de datos financieros factuales
3. **IMPLIED**: Cálculo de expectativas implícitas del mercado
4. **CATALYST**: Detección y scoring de catalizadores (multi-modelo)
5. **FORENSIC**: Análisis forense financiero y de supervivencia (multi-modelo)
6. **BULL**: Construcción del caso alcista (multi-modelo)
7. **RED_TEAM**: Crítica destructiva del caso (multi-modelo)
8. **ARBITRO**: Decisión final con sizing probabilístico

### Modelo multi-agente
Cada paso analítico (4-7) se ejecuta en paralelo por 3 modelos (Claude, Codex, Gemini).
Los resultados se fusionan en un artifact consolidado.
El ARBITRO recibe SOLO los artifacts fusionados.

### Decisiones
- INVERTIR: Todos los gates pasan, sizing > 0
- WATCHLIST: Potencial pero falta convicción o catalizador
- DESCARTAR: Riesgos inaceptables
- BLOQUEADO: Datos insuficientes no remediables

### Sizing (Kelly)
- Kelly crudo → ajustado por confianza (×0.7) → cap máximo 10%
- Solo se aplica si decisión = INVERTIR
```

### 8.2 CRITERIOS_REVIEW.md (fichero adjunto al proyecto)

```markdown
# Criterios de Meta-Review

## 1. Coherencia lógica
- ¿Las conclusiones del resumen ejecutivo se sostienen con la evidencia del assumption_ledger?
- ¿Hay saltos lógicos entre claims y decisión?
- ¿Los scores parciales (SMCQRV) reflejan correctamente lo que dicen los agentes?

## 2. Rigor de gates
- ¿Cada gate tiene justificación suficiente?
- ¿Un CONDITIONAL se está usando como "PASS blando" sin evidencia?
- ¿Hay gates que deberían ser FAIL pero se marcaron como PASS?

## 3. Supuestos críticos
- ¿Cada supuesto CRITICO tiene al menos una evidencia con source_id?
- ¿Los tests de falsación son realmente observables y medibles?
- ¿Las probabilidades asignadas son coherentes con la evidencia?
- ¿Hay dependencias circulares entre supuestos?

## 4. Escenarios
- ¿Las probabilidades suman ~1.0?
- ¿El escenario BASE es realmente el más probable, o es un BULL disfrazado?
- ¿El BEAR contempla un escenario suficientemente adverso?
- ¿Los retornos son realistas para los horizontes dados?

## 5. Sizing y Kelly
- ¿Los inputs del Kelly (p, b) son coherentes con los escenarios?
- ¿El ajuste por confianza es apropiado?
- ¿El sizing final es prudente dado el nivel de incertidumbre?

## 6. Puntos ciegos
- ¿Hay riesgos macro no considerados?
- ¿Se ha evaluado el riesgo de liquidez?
- ¿Se han considerado riesgos regulatorios?
- ¿Hay competidores o disrupciones no mencionados?

## 7. Kill criteria
- ¿Son específicos (no genéricos)?
- ¿Tienen umbrales numéricos donde es posible?
- ¿La acción asociada (EXIT, REDUCE_50, etc.) es proporcional?
- ¿Cubren los riesgos más graves del BEAR scenario?
```

---

## 9. Cambios en ficheros existentes

### 9.1 Ficheros nuevos a crear

| Fichero | Tipo | Descripción |
|---------|------|-------------|
| `engine/review_compiler.py` | Módulo Python | Compilación de prompts de review |
| `engine/review_ingest.py` | Módulo Python | Ingesta de respuestas de GPT-5.2 Pro |
| `scripts/review/generate_project_package.py` | Script Python | Generador del paquete de proyecto ChatGPT |
| `_schemas/review/MetaReview_v1.json` | Schema JSON | Schema del output del meta-review |
| `_review_project/` | Directorio | Output del generador de paquete de proyecto |
| `_review_project/INSTRUCCIONES_PROYECTO.md` | Markdown | Instrucciones para el proyecto ChatGPT |
| `_review_project/METODOLOGIA_ELSIAN.md` | Markdown | Resumen de metodología |
| `_review_project/CRITERIOS_REVIEW.md` | Markdown | Criterios de evaluación |
| `_review_project/REGLAS_COMUNES_EXTRACTO.md` | Markdown | Extracto de reglas comunes |

### 9.2 Ficheros existentes a modificar

| Fichero | Cambio |
|---------|--------|
| `engine/engine.py` | Añadir subcomandos `review`, `review_ingest` y `review_status` |
| `engine/dashboard.py` | Extender `generate_decisions()` y `_extract_decision_info()` para mostrar estado MR |
| `engine/state.py` | Añadir función `update_meta_review_fields()` para persistir datos del review |
| `engine/validator.py` | Añadir `"MetaReview_v1"` a `SCHEMA_MAP` con ruta relativa `review/MetaReview_v1.json` (relativa a `schemas_dir`, consistente con las demás entradas como `artefactos/DecisionPacket_v2.json`) |
| `_schemas/estado/caso_estado_v1.json` | Añadir campo `meta_review` al schema de estado |
| `_operativa/REGLAS_COMUNES.md` | Documentar el flujo de meta-review en §nuevo |
| `CHANGELOG.md` | Registrar la feature |

> **Nota v1.2 (corrección Codex #2):** `engine/validator.py` SÍ requiere modificación. El `SCHEMA_MAP` actual no incluye `MetaReview_v1`, por lo que `validate_artifact()` fallaría con "Unknown schema". Se debe añadir la entrada correspondiente.

### 9.3 Ficheros que NO se modifican

| Fichero | Razón |
|---------|-------|
| `engine/router.py` | El review NO es un paso del pipeline DAG — es post-pipeline |
| `engine/prompt_builder.py` | El review compiler tiene su propia lógica de compilación |
| `engine/dispatcher.py` | No hay dispatch automático — es manual vía ChatGPT |
| `engine/backends/*.py` | No hay backend de ChatGPT — es interacción manual |

---

## 10. Flujo operativo completo

### 10.1 Setup inicial (una sola vez)

```bash
# 1. Generar paquete de proyecto
python3 scripts/review/generate_project_package.py

# 2. En ChatGPT web:
#    - Crear proyecto "ELSIAN Meta-Review"
#    - Seleccionar modelo: GPT-5.2 Pro
#    - Pegar contenido de _review_project/INSTRUCCIONES_PROYECTO.md como instrucciones
#    - Adjuntar los ficheros de _review_project/ (schemas + docs)
```

### 10.2 Por cada caso completado

```bash
# 1. Pipeline se completa normalmente
python3 -m engine pipeline TZOO --date 2026-02-21

# 2. Generar prompt de review
python3 -m engine review TZOO --date 2026-02-21
# → Genera: casos/TZOO/2026-02-21/_review_prompt_gpt52pro_20260223T143022.md

# 3. OPERADOR: Copia contenido del .md y lo pega en el proyecto ChatGPT
#    (puede ser en un hilo nuevo del proyecto, o continuando uno existente del mismo ticker)

# 4. OPERADOR: Espera respuesta de GPT-5.2 Pro, la copia a:
#    casos/TZOO/2026-02-21/_review_response_raw_20260223T143022.md

# 5. Ingestar respuesta
python3 -m engine review_ingest TZOO --date 2026-02-21
# → Genera: MetaReview_v1_TZOO_20260221.json
# → Actualiza: _estado.json
# → Muestra: resumen del veredicto

# 6. Decisions muestra estado actualizado
python3 -m engine decisions
```

### 10.3 Actualización del proyecto (cuando cambian schemas)

```bash
# 1. Regenerar paquete
python3 scripts/review/generate_project_package.py
# → Detecta: "⚠ DecisionPacket_v2.json ha cambiado desde última generación"
# → Genera nuevos ficheros

# 2. OPERADOR: Actualiza ficheros adjuntos en el proyecto ChatGPT
```

---

## 11. Consideraciones de diseño

### 11.1 ¿Por qué no incluir TODOS los artifacts?

El DecisionPacket_v2 del caso TZOO pesa ~74 KB. Si añadiéramos todos los AgentReports completos (BULL 51KB + RED_TEAM 80KB + CATALYST 75KB + FORENSIC 65KB) llegaríamos a ~345 KB solo en JSON — sin contar el prompt wrapper. Aunque GPT-5.2 Pro puede manejar contextos largos, la calidad de razonamiento se degrada con exceso de información. La estrategia es: **DecisionPacket completo** (es el objeto a auditar) + **resúmenes ejecutivos y claims críticos de los agentes** (contexto necesario sin ruido).

### 11.2 ¿Por qué separar compilación e ingesta?

Porque hay un paso humano en medio (pegar en ChatGPT, esperar respuesta, copiar respuesta). Si fuera un solo comando, no tendría sentido. Además, esto permite que el operador haga múltiples reviews antes de ingestar, o que revise la respuesta de GPT-5.2 Pro antes de incorporarla.

### 11.3 ¿Por qué no usar la API de ChatGPT?

1. GPT-5.2 Pro vía API tiene un coste de $21/MTk input y $168/MTk output — para un prompt de ~80KB el coste sería ~$4-6 por review
2. La suscripción Pro ya incluye uso ilimitado de GPT-5.2 Pro en la interfaz
3. El paso humano tiene valor propio: el operador lee tanto el prompt como la respuesta, creando un checkpoint de supervisión real
4. La funcionalidad de Proyectos de ChatGPT ahorra la necesidad de re-contextualizar en cada conversación

### 11.4 Valor de la memoria conversacional del proyecto

Al usar hilos dentro del mismo proyecto para el mismo ticker, GPT-5.2 Pro puede referenciar reviews anteriores. Esto permite comparaciones temporales: "en el review anterior de TZOO, señalé preocupación por los márgenes — ¿se ha resuelto en esta nueva ejecución?"

### 11.5 El meta-review NO es vinculante

El `MetaReview_v1` se persiste como artifact informativo. No modifica la decisión del ARBITRO ni el sizing. El operador es quien decide si actuar sobre las recomendaciones del meta-review (re-ejecutar ARBITRO, ajustar manualmente, investigar más, o ignorar). El subcomando `decisions` muestra el veredicto como tag `[MR:X]` pero NO altera el color o estado del caso — es información complementaria.

### 11.6 Convención de nombres de ficheros

Alineado con REGLAS_COMUNES.md donde `_*` indica ficheros intermedios/temporales:

| Fichero | Prefijo | Razón |
|---------|---------|-------|
| `_review_prompt_gpt52pro_{TS}.md` | `_` | Fichero intermedio generado, con timestamp. No es artifact canónico |
| `_review_response_raw_{TS}.md` | `_` | Input manual del operador, con timestamp del prompt asociado |
| `_review_narrative_gpt52pro_{TS}.md` | `_` | Output secundario (narrativa completa), con timestamp |
| `MetaReview_v1_TICKER_DATE.json` | sin `_` | Artifact canónico persistido |

Donde `{TS}` = timestamp en formato `YYYYMMDDTHHMMSS` generado al ejecutar `review`.

### 11.7 Versionado del paquete de proyecto

El `_manifest.json` generado por `generate_project_package.py` contiene:

```json
{
  "version_paquete": "1.0",
  "generado": "ISO 8601",
  "hashes": {
    "DecisionPacket_v2.json": "sha256:...",
    "AgentReport_v1.json": "sha256:...",
    "MetaReview_v1.json": "sha256:...",
    "INSTRUCCIONES_PROYECTO.md": "sha256:...",
    "CRITERIOS_REVIEW.md": "sha256:...",
    "METODOLOGIA_ELSIAN.md": "sha256:..."
  },
  "schemas_source_hashes": {
    "_schemas/artefactos/DecisionPacket_v2.json": "sha256:...",
    "_schemas/artefactos/AgentReport_v1.json": "sha256:..."
  }
}
```

Al regenerar, el script compara `schemas_source_hashes` con los hashes actuales de `_schemas/` y reporta qué ha cambiado, permitiendo al operador saber exactamente qué ficheros debe actualizar en el proyecto ChatGPT.

### 11.8 Histórico de reviews y protección de ficheros intermedios

> **Nota v1.2 (corrección Codex #5):** En v1.0, los ficheros intermedios usaban nombres fijos (`_review_prompt_gpt52pro.md`), lo que causaba riesgo de colisión si se generaba un nuevo prompt antes de ingestar la respuesta anterior. En v1.2, todos los ficheros intermedios llevan sufijo timestamp `_{TS}`.

**Nombres de ficheros intermedios (con timestamp):**
- `_review_prompt_gpt52pro_20260223T143022.md`
- `_review_response_raw_20260223T143022.md`
- `_review_narrative_gpt52pro_20260223T143022.md`

El comando `review` genera el prompt con timestamp y almacena ese timestamp en `_estado.json` campo `meta_review.prompt_timestamp`. El comando `review_ingest` busca el response cuyo timestamp coincida con el prompt más reciente. Si no lo encuentra, busca el `_review_response_raw_*.md` más reciente.

**Artifact canónico (sin timestamp, con rotación):**
- Primera review: `MetaReview_v1_TZOO_20260221.json` (revision_num: 1 en snapshot)
- Si se re-ejecuta ARBITRO y se hace nuevo review: el anterior se renombra a `MetaReview_v1_TZOO_20260221_rev1.json` y el nuevo toma el nombre canónico
- `_estado.json` siempre apunta al review más reciente
- El campo `decision_packet_snapshot.revision_num` permite trazar qué versión del DP se revisó

---

## 12. Dependencias y requisitos

### 12.1 Dependencias Python (ya existentes en el proyecto)
- `json`, `pathlib`, `hashlib`, `datetime` — stdlib
- `jsonschema` — ya usado por `engine/validator.py`

### 12.2 No se requieren dependencias nuevas

### 12.3 Requisitos externos
- Cuenta ChatGPT Pro activa con acceso a GPT-5.2 Pro
- Proyecto creado en ChatGPT con instrucciones y ficheros adjuntos
- Operador disponible para el paso manual (copiar/pegar)

---

## 13. Tests y validación

### 13.1 Tests unitarios

| Test | Descripción |
|------|-------------|
| `test_compile_review_prompt_tzoo` | Compilar prompt para TZOO, verificar estructura y tamaño |
| `test_compile_review_prompt_missing_artifacts` | Caso con artifacts faltantes — debe degradar graciosamente |
| `test_compile_alerts_generation` | Verificar que las alertas automáticas se generan correctamente |
| `test_ingest_valid_response` | Ingestar un JSON válido MetaReview_v1 |
| `test_ingest_malformed_json` | Ingestar respuesta con JSON roto — error informativo |
| `test_ingest_missing_fields` | Ingestar JSON parcial — salvar lo que se pueda |
| `test_project_package_manifest` | Verificar que el manifest detecta cambios en schemas |
| `test_estado_update` | Verificar que _estado.json se actualiza correctamente |

### 13.2 Test de integración real

1. Ejecutar `python3 -m engine review TZOO --date 2026-02-21`
2. Verificar que el prompt generado es coherente y legible
3. Pegarlo en ChatGPT con GPT-5.2 Pro
4. Verificar que la respuesta incluye el bloque JSON
5. Ejecutar `python3 -m engine review_ingest TZOO --date 2026-02-21`
6. Verificar que el artifact se guarda y el estado se actualiza
7. Verificar que `decisions` muestra el estado MR con tag `[MR:X]`

---

## 14. Orden de implementación sugerido

| Fase | Componente | Prioridad | Dependencias |
|------|-----------|-----------|--------------|
| 1 | Schema `MetaReview_v1.json` | ALTA | Ninguna |
| 2 | `engine/review_compiler.py` + subcomando CLI `review` | ALTA | Schema |
| 3 | `scripts/review/generate_project_package.py` + docs adjuntos | ALTA | Schema |
| 4 | Configurar proyecto en ChatGPT (manual) | ALTA | Paquete generado |
| 5 | Test real: compilar → pegar → obtener respuesta | ALTA | Fases 1-4 |
| 6 | `engine/review_ingest.py` + subcomando CLI `review_ingest` | ALTA | Schema + test real |
| 7 | `engine/state.py` — `update_meta_review_fields()` | MEDIA | Ingest |
| 8 | `engine/validator.py` — añadir `MetaReview_v1` a `SCHEMA_MAP` | MEDIA | Schema |
| 9 | `engine/dashboard.py` — extensión MR en `generate_decisions()` | MEDIA | State |
| 10 | `_schemas/estado/caso_estado_v1.json` — campo meta_review | MEDIA | State |
| 11 | Subcomando `review_status` en `engine/engine.py` | MEDIA | State + Compiler |
| 12 | Tests unitarios | MEDIA | Todo lo anterior |
| 13 | Documentación en REGLAS_COMUNES.md + CHANGELOG.md | BAJA | Todo lo anterior |

**Estimación total:** 4-6 horas de implementación (sin contar el test real con ChatGPT).

---

## 15. Decisiones de consenso (Opus + Codex)

Las 5 preguntas abiertas de la v1.0 han sido respondidas tras la revisión de Codex:

### P1: Formato de artifacts en el prompt → **OPCIÓN A+ (híbrida estructurada)**
DecisionPacket como JSON completo + extractos **estructurados** (no solo narrativa) de BULL y RED_TEAM. Es decir, los claims de BULL/RED_TEAM se incluyen como fragmentos JSON filtrados (solo CRITICO + IMPORTANTE), no como texto libre resumido. Esto preserva la estructura para que GPT-5.2 Pro pueda referenciar assumption_ids y claim_ids concretos.

### P2: Re-arbitraje automático → **OPCIÓN A (NO automático)**
El meta-review es informativo. No se dispara REARBITRATE automáticamente. En una fase posterior, se puede añadir un flag manual (`python3 -m engine rearbitrate TICKER --from-review`) si el operador lo decide.

### P3: Histórico de reviews → **OPCIÓN A (con rotación)**
Un review canónico por ejecución. Los anteriores se preservan con sufijo `_revN`. Clave para trazabilidad y aprendizaje temporal de GPT-5.2 Pro dentro del proyecto ChatGPT.

### P4: Generación automática del prompt de review → **OPCIÓN A (explícita)**
> **Nota v1.2 (corrección Codex #6):** La pregunta original confundía dos cosas: el generador de paquete de proyecto (`generate_project_package.py`, se ejecuta raramente) vs. el generador de prompt por caso (`review`, se ejecuta tras cada pipeline). La decisión aplica a ambos: ninguno se ejecuta automáticamente. El operador ejecuta `python3 -m engine review TICKER` explícitamente, o usa un flag opcional (`python3 -m engine pipeline TICKER --with-review`) para encadenar la generación del prompt al final del pipeline.

### P5: Quality votes en el prompt → **OPCIÓN A CONDICIONADA (sí, con nota anti-sesgo)**
Incluir quality votes como tabla resumen, pero precedidos por esta nota en el prompt:
> "Los scores de calidad son una señal de calidad formal del pipeline (validación de schema, completitud de campos, ratio de nulos). No son indicadores de verdad fundamental ni de calidad del razonamiento. Úsalos como contexto, no como juicio previo."

---

*Este plan está diseñado para ser revisado conjuntamente por Claude, Codex y Elsian antes de iniciar la implementación.*
