# _errors/ — Histórico Global de Errores del Pipeline

Directorio de registro centralizado de todos los errores detectados en el engine.
Diseñado para ser consumido por agentes de código (Copilot, Claude, etc.) que necesitan
entender qué falló, en qué archivo del engine y con qué contexto exacto.

---

## Archivos

| Archivo | Descripción |
|---|---|
| `error_history.jsonl` | Log append-only de **todos** los errores (OPEN y RESOLVED). Nunca se modifica, solo se añaden líneas. |
| `open_errors.json` | Snapshot de errores con `estado=OPEN`. Se actualiza en cada fallo/resolución. Punto de entrada para el agente. |

---

## Cómo leer los errores (para el agente)

**Paso 1 — Obtener errores activos:**
```bash
python3 -m engine errors list
python3 -m engine errors list --ticker KAR
python3 -m engine errors list --step BULL
```

**Paso 2 — Si `open_errors.json` se corrompió o perdió:**
```bash
python3 -m engine errors rebuild
# o con el script standalone:
python3 scripts/qa/repair_open_errors.py
```

---

## Schema del registro (`error_record_v1`)

Cada línea de `error_history.jsonl` y cada entrada de `open_errors.json["errors"]`
sigue este schema. Ver definición completa en `_schemas/error_record_v1.json`.

| Campo | Tipo | Descripción para el agente |
|---|---|---|
| `error_id` | string | ID único: `ERR_{TICKER}_{DATE}_{STEP}_{TS}` |
| `version` | string | Siempre `"error_record_v1"` |
| `timestamp_iso` | string | Momento exacto del fallo (UTC ISO-8601) |
| `estado` | enum | `OPEN` = sin resolver \| `RESOLVED` = completado después del fallo |
| `ticker` | string | Ticker del caso afectado (ej. `KAR`) |
| `fecha_caso` | string | Fecha del caso (`YYYY-MM-DD`) |
| `step` | string | Paso del pipeline que falló (ej. `BULL`, `FORENSIC`, `ARBITRO`) |
| `error_type` | enum | Categoría del error (ver tabla abajo) |
| `error_msg` | string | Mensaje de error normalizado |
| `stack_trace` | string\|null | Traceback Python si disponible en el contexto |
| `source_context` | object | `{ module, file }` — dónde buscar en el código del engine |
| `engine_context` | object | `{ backend, transport, model_profile, attempts }` — config activa al fallar |
| `diagnostics` | object | `{ compact_path, full_path }` — rutas a artefactos de diagnóstico completos |
| `case_dir` | string | Ruta relativa al caso (ej. `casos/KAR/2026-02-22`) |
| `resolved_at` | string\|null | Timestamp de resolución |
| `resolved_by` | string\|null | Quién resolvió (ej. `engine:mark_step_done`) |

---

## Valores de `error_type`

| Valor | Cuándo ocurre | Dónde buscar en el engine |
|---|---|---|
| `LLM_FAILURE` | El backend LLM (claude/codex/gemini) falló todos los reintentos | `engine/backends/`, `engine/dispatcher.py` |
| `SCHEMA_VALIDATION` | El JSON producido por el LLM no valida contra el schema esperado | `engine/validator.py`, `engine/step_contracts.py` |
| `TIMEOUT` | El LLM excedió el timeout configurado | `engine/dispatcher.py`, `engine_config.json` |
| `PARSE_ERROR` | No se pudo parsear la respuesta del LLM (JSON malformado, markdown inesperado) | `engine/backends/`, `engine/review_ingest.py` |
| `PIPELINE_STATE` | Error de estado del pipeline (ej. `estado_pipeline=INCOMPLETO` incorrecto) | `engine/state.py`, `engine/router.py` |
| `UNKNOWN` | Error no clasificado | Revisar `error_msg` + `diagnostics.full_path` |

---

## Flujo de vida de un registro

```
mark_step_failed()          mark_step_done()
       │                           │
       ▼                           ▼
 append_error()            resolve_error()
  estado=OPEN               estado=RESOLVED
       │                           │
       ▼                           ▼
error_history.jsonl  ←──  append nueva línea RESOLVED
open_errors.json     ←──  elimina entrada del snapshot
```

---

## Rutas de diagnóstico completo

Cada registro tiene `diagnostics.full_path` apuntando a:
```
casos/{TICKER}/{DATE}/_diagnostics/failures/{STEP}.{TS}.full.json
```
Este archivo contiene el payload completo del fallo, incluyendo todos los intentos,
outputs del LLM y decisiones del router. Es el recurso más rico para debuggear.
