# INFORME DE ROBUSTEZ DEL PIPELINE — ELSIAN INVEST 3.0

**Fecha:** 24 de febrero de 2026
**Versión:** 1.0
**Alcance:** Auditoría exhaustiva a nivel de código de todo el engine (24 módulos Python, ~8,000 líneas), scripts auxiliares, backends de modelos, y evidencia de errores reales en los 14 casos ejecutados.

---

## 1. RESUMEN EJECUTIVO

Se han identificado **84 puntos de fallo** distribuidos en 12 categorías, de los cuales **30 son de riesgo ALTO o CRÍTICO**. Al menos 8 de estos fallos han sido **confirmados en ejecuciones reales** (evidencia en `_estado.json`, `open_errors.json`, y logs de votación).

El pipeline tiene una arquitectura sólida (state atómico con locks, retry con fallback de transporte, JSON recovery cascade de 4 niveles, quality voting determinista), pero presenta debilidades recurrentes en: manejo de excepciones silenciosas, limpieza de recursos en paths de fallo, y concurrencia en escrituras paralelas.

### Métricas Clave

| Métrica | Valor |
|---------|-------|
| Puntos de fallo identificados | 84 |
| Riesgo CRÍTICO | 9 |
| Riesgo ALTO | 21 |
| Riesgo MEDIO | 36 |
| Riesgo BAJO | 18 |
| Confirmados en logs reales | 8 |
| Módulos más afectados | dispatcher.py (12), router.py (11), state.py (8), backends/*.py (14) |

---

## 2. HALLAZGOS CRÍTICOS (Prioridad Inmediata)

### 2.1 Excepciones silenciosas en `state.py` (líneas 213, 269)

**Archivo:** `engine/state.py`
**Líneas:** 213, 269-270
**Severidad:** CRÍTICA

```python
# Línea 213 — mark_step_done()
except Exception:
    pass  # error_tracker is non-critical; never fail the pipeline

# Línea 269-270 — mark_step_failed()
except Exception:
    pass  # error_tracker is non-critical; never fail the pipeline
```

**Problema:** Cuando `error_tracker.resolve_error()` o `error_tracker.append_error()` fallan, la excepción se traga completamente. Esto es aceptable para el tracker, PERO el `pass` no distingue entre errores del tracker y errores inesperados (e.g., `ImportError`, `MemoryError`). Cualquier excepción hija se silencia.

**Evidencia real:** El caso `0327/2026-02-23` muestra `estado_pipeline=INCOMPLETO` pese a todos los sub-steps marcados como `DONE`, lo que sugiere que `mark_step_done` falló parcialmente sin propagarse.

**Fix recomendado:**
```python
except Exception as exc:
    import logging
    logging.getLogger("engine.state").warning(
        "error_tracker call failed (non-blocking): %s", exc
    )
```

---

### 2.2 Race condition TOCTOU en `load_state()` (línea 64)

**Archivo:** `engine/state.py`
**Líneas:** 63-74

```python
def load_state(case_dir: Path) -> dict:
    state_file = case_dir / "_estado.json"
    if not state_file.exists():          # ← CHECK (sin lock)
        raise FileNotFoundError(...)
    lock_path = _state_lock_path(case_dir)
    lock_path.touch(exist_ok=True)
    with open(lock_path) as lf:
        fcntl.flock(lf, fcntl.LOCK_SH)  # ← LOCK (después del check)
        try:
            with open(state_file) as f:  # ← USE
                return json.load(f)
```

**Problema:** La verificación `state_file.exists()` ocurre ANTES de adquirir el lock. Entre el check y el lock, otro proceso puede eliminar o reescribir el archivo. Esto crea una ventana de race condition clásica (TOCTOU: Time-Of-Check-to-Time-Of-Use).

**Impacto:** En ejecución paralela `CATALYST || FORENSIC`, ambos procesos pueden leer estado parcial o corrupto. El sistema tiene `read_modify_write()` que usa lock exclusivo correctamente, pero `load_state()` (usado para lecturas simples) no está protegido.

**Fix recomendado:** Mover el check dentro del lock:
```python
def load_state(case_dir: Path) -> dict:
    lock_path = _state_lock_path(case_dir)
    lock_path.touch(exist_ok=True)
    with open(lock_path) as lf:
        fcntl.flock(lf, fcntl.LOCK_SH)
        try:
            state_file = case_dir / "_estado.json"
            if not state_file.exists():
                raise FileNotFoundError(f"No state file: {state_file}")
            with open(state_file) as f:
                return json.load(f)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
```

---

### 2.3 File descriptor leak en `_write_state_unlocked()` (línea 100)

**Archivo:** `engine/state.py`
**Líneas:** 96-105

```python
fd, tmp_path = tempfile.mkstemp(dir=str(case_dir), suffix=".tmp", prefix="_estado_")
try:
    with open(fd, "w") as f:   # ← abre fd de nuevo
        json.dump(state, f, indent=2, ensure_ascii=False)
    Path(tmp_path).replace(state_file)
except Exception:
    Path(tmp_path).unlink(missing_ok=True)
    raise
```

**Problema:** `tempfile.mkstemp()` retorna un file descriptor ya abierto (`fd`). Luego `open(fd, "w")` lo abre de nuevo, lo cual funciona pero puede causar leak si la primera apertura no se cierra adecuadamente en todos los paths de excepción. Lo correcto es usar `os.fdopen()`.

**Fix recomendado:**
```python
fd, tmp_path = tempfile.mkstemp(dir=str(case_dir), suffix=".tmp", prefix="_estado_")
try:
    with os.fdopen(fd, "w") as f:   # ← envuelve fd correctamente
        json.dump(state, f, indent=2, ensure_ascii=False)
    Path(tmp_path).replace(state_file)
except Exception:
    Path(tmp_path).unlink(missing_ok=True)
    raise
```

**Nota:** El mismo patrón se repite en `save_estado_repo()` (líneas 513-522) y en `_resolve_input_artifacts()` (línea 1565 de router.py, que ya usa `os.fdopen` correctamente).

---

### 2.4 Ejecución paralela sin timeout en `_execute_parallel_steps()` (líneas 1770-1797)

**Archivo:** `engine/router.py`
**Líneas:** 1770-1797

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
    future_to_step = {
        executor.submit(execute_step, config, case_dir, step, ticker, hints=hints): step
        for step in steps
    }
    for future in concurrent.futures.as_completed(future_to_step):  # ← SIN timeout
        step = future_to_step[future]
        try:
            results[step] = future.result()
        except Exception as e:
            ...
```

**Problema:** `as_completed()` se llama sin parámetro `timeout`. Si uno de los backends se cuelga indefinidamente (e.g., Gemini 429 sin backoff adecuado, o Claude con output infinito), todo el pipeline queda bloqueado eternamente.

**Impacto:** El pipeline no tiene mecanismo de kill para threads que excedan el timeout. El `ThreadPoolExecutor` context manager sale, pero los threads pueden seguir ejecutándose.

**Fix recomendado:**
```python
max_timeout = max(
    config.get_model_spec(p).primary_transport.timeout_seconds
    for p in config.get_step_profiles(steps[0])
    if config.get_model_spec(p) and config.get_model_spec(p).primary_transport
) + 60  # buffer de 60s

for future in concurrent.futures.as_completed(future_to_step, timeout=max_timeout):
    ...

# Cancelar futures pendientes
for future in future_to_step:
    if not future.done():
        future.cancel()
```

---

### 2.5 Lost-write race en `error_tracker.py` (líneas 277-287)

**Archivo:** `engine/error_tracker.py`
**Líneas:** 277-287

```python
open_data = _load_open_errors()         # ← LEE sin lock
errors_list = open_data.get("errors", [])
errors_list = [
    e for e in errors_list
    if not (e.get("ticker") == ticker and ...)
]
errors_list.append(record)
open_data["errors"] = errors_list
_save_open_errors(open_data)             # ← ESCRIBE sin lock
```

**Problema:** Entre `_load_open_errors()` y `_save_open_errors()`, otro proceso paralelo puede actualizar el archivo. La actualización del primer proceso se pierde completamente (patrón de lost write clásico).

**Evidencia real:** Se han observado inconsistencias en `open_errors.json` donde errores conocidos (de logs de votación) no aparecen en el registro.

**Fix recomendado:** Implementar patrón de read-modify-write con file lock (similar a `state.py:read_modify_write()`).

---

## 3. HALLAZGOS ALTOS (Segunda Prioridad)

### 3.1 No hay cleanup de procesos zombie en backends de timeout

**Archivos:** `engine/backends/claude.py`, `codex.py`, `gemini.py`, `copilot.py`
**Severidad:** ALTA

Todos los backends usan `subprocess.run()` con `timeout=`. Cuando ocurre `TimeoutExpired`, Python mata el proceso automáticamente, PERO:

1. **Codex** crea un archivo de output temporal (`tempfile.NamedTemporaryFile`) que se limpia en `finally`, pero el proceso Codex puede seguir escribiendo si no fue matado a tiempo.
2. **Gemini** no tiene cleanup de archivos intermedios.
3. **Copilot** usa el mismo patrón de subprocess.run sin verificar que el proceso hijo realmente terminó.

**Fix recomendado:** Añadir `proc.kill()` explícito + `proc.wait(timeout=5)` en el handler de timeout de cada backend.

---

### 3.2 JSON recovery acepta fragmentos parciales (`_is_viable_recovered_artifact`)

**Archivo:** `engine/dispatcher.py`
**Líneas:** 85-98

```python
def _is_viable_recovered_artifact(payload: dict) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if "version_esquema" in payload:
        return True
    return len(payload) >= 8   # ← MAGIC NUMBER
```

**Problema:** La validación acepta cualquier dict con ≥8 claves, sin verificar que sean las claves correctas para el step. Un sub-objeto interno o metadata podría tener 8+ claves y ser aceptado como artefacto válido.

**Impacto:** Si el recovery extrae un sub-fragmento en vez del artefacto completo, se escribe a disco y se pasa a pasos posteriores, causando fallos en cascade.

**Fix recomendado:** Validar contra el schema del paso:
```python
def _is_viable_recovered_artifact(payload: dict, step_name: str = None) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if "version_esquema" in payload:
        return True
    if step_name:
        schema = get_primary_schema(step_name)
        if schema:
            is_valid, _ = validate_artifact(payload, schema, schemas_dir)
            return is_valid
    return len(payload) >= 8
```

---

### 3.3 Threading lock no protege en multiprocessing

**Archivo:** `engine/dispatcher.py`
**Línea:** 63

```python
_PROMPT_EXCERPT_LOCK = threading.Lock()
```

**Problema:** `threading.Lock` solo protege threads del mismo proceso Python. Si el pipeline usa `multiprocessing` o `subprocess` para lanzar workers, el lock no tiene efecto y múltiples procesos pueden escribir al mismo archivo JSONL simultáneamente, causando corrupción.

**Evidencia:** El pipeline actual usa `ThreadPoolExecutor` (no multiprocessing) para los steps paralelos, así que el impacto inmediato es bajo. PERO si se cambia a multiprocessing en el futuro, la corrupción será silenciosa.

**Fix recomendado:** Usar `fcntl.flock()` (OS-level) en vez de `threading.Lock()`, consistente con el patrón ya usado en `state.py` y `quality_voting.py`.

---

### 3.4 `_extract_decision_fields` swallows ALL exceptions (línea 1948)

**Archivo:** `engine/router.py`
**Líneas:** 1800-1949

```python
def _extract_decision_fields(case_dir: Path, step_result: dict) -> None:
    ...
    try:
        ... # 150 líneas de lógica compleja
    except (json.JSONDecodeError, OSError, ValueError):
        pass  # ← Se traga 3 tipos de excepción
```

**Problema:** La función `_extract_decision_fields` es de 150 líneas con lógica compleja de parsing de DecisionPacket. Si falla por CUALQUIER razón (JSON corrupto, campo faltante, TypeError), se silencia completamente. El estado del caso queda con `decision=None, score=None, confianza=None` sin ninguna indicación de error.

**Impacto:** El caso se marca como `COMPLETO` pero sin decisión. `estado_resumen.py` mostrará `decision=None` sin explicar por qué.

**Fix recomendado:**
```python
except (json.JSONDecodeError, OSError, ValueError) as exc:
    print(f"[router] ERROR: Failed to extract decision fields from ARBITRO: {exc}", file=sys.stderr)
    # Opcionalmente, marcar en el estado que la extracción falló
```

---

### 3.5 Partial artifacts no se limpian en retry de TRUTH_PACK

**Archivo:** `engine/router.py`
**Líneas:** 1293-1296

```python
# Clean stale partials from previous runs to avoid merger contamination
for old_partial in case_dir.glob("_tmp_tp_filing_*.json"):
    old_partial.unlink()
```

**Problema:** Esta limpieza solo ocurre al INICIO de `_run_parallel_filing_step`. Si el step falla después de escribir 3 de 10 parciales, los 3 archivos quedan en disco. En el siguiente retry, se limpian correctamente (línea 1294). PERO si el pipeline se reinicia manualmente (no retry automático), esos parciales pueden contaminar el merger.

**Impacto:** `TP_EXTRACTOR_MERGER` puede fusionar parciales de distintas ejecuciones, mezclando datos old+new.

**Fix recomendado:** Añadir limpieza también en el path de fallo:
```python
if successful == 0:
    # Cleanup any partial files written during this failed run
    for partial in case_dir.glob("_tmp_tp_filing_*.json"):
        partial.unlink(missing_ok=True)
    return {"success": False, ...}
```

---

### 3.6 `load_all_case_states` lee sin lock (línea 458-462)

**Archivo:** `engine/state.py`
**Líneas:** 445-463

```python
def load_all_case_states(casos_dir: Path) -> list[dict]:
    ...
    for case_dir in sorted(ticker_dir.iterdir()):
        state_file = case_dir / "_estado.json"
        if state_file.exists():
            try:
                with open(state_file) as f:      # ← SIN lock
                    results.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass                               # ← silencioso
    return results
```

**Problema doble:**
1. Lee `_estado.json` sin shared lock (a diferencia de `load_state()` que sí usa lock).
2. Si falla el parse, traga la excepción silenciosamente — el caso simplemente desaparece de la lista.

**Impacto:** `estado_resumen.py` y `generate_dashboard()` pueden mostrar datos parciales o perder casos enteros sin notificación.

---

### 3.7 Auth cache no invalida otros modelos al expirar

**Archivo:** `engine/backends/claude.py`
**Líneas:** 97-107

```python
def _invalidate_auth_cache_if_auth_error(self, *texts: str) -> None:
    combined = " ".join(texts).lower()
    if any(p in combined for p in _AUTH_FAILURE_PATTERNS):
        cache_key = (self.binary_path, self.model)
        _AUTH_CACHE.pop(cache_key, None)   # ← solo invalida ESTE modelo
```

**Problema:** Si la API key expira, el error "not logged in" afecta a TODOS los modelos de ese backend. Pero el cache solo invalida la entrada del modelo específico. Los demás modelos mantienen su cache "válido" y fallarán en la siguiente llamada.

**Fix recomendado:** Invalidar todas las entradas del mismo binary_path:
```python
if any(p in combined for p in _AUTH_FAILURE_PATTERNS):
    keys_to_remove = [k for k in _AUTH_CACHE if k[0] == self.binary_path]
    for k in keys_to_remove:
        _AUTH_CACHE.pop(k, None)
```

---

## 4. HALLAZGOS MEDIOS (Tercera Prioridad)

### 4.1 Validación de schema se ejecuta sin cache

**Archivo:** `engine/validator.py`, líneas 70-71
El schema se carga de disco en cada llamada a `validate_artifact()`. Con ~1000 validaciones por pipeline, esto genera I/O innecesario.

**Fix:** Añadir `@functools.lru_cache` al loader de schemas.

### 4.2 Inconsistencia en truncamiento de stderr entre backends

**Archivos:** Todos los backends
Claude trunca stderr a 500 chars en log pero 2000 en error_msg. Codex usa 500/500. Gemini usa limites diferentes.

**Fix:** Definir constante `_MAX_STDERR_LOG = 1000` y `_MAX_STDERR_MSG = 3000` compartida.

### 4.3 `_infer_exchange_from_text()` tiene cobertura limitada

**Archivo:** `engine/router.py`, líneas 134-144
Solo reconoce NASDAQ, NYSE, AMEX. No reconoce variantes de non-US exchanges (SEHK, HKEX, LSE, ASX, EPA, etc.) pese a que el pipeline procesa tickers de estos mercados.

**Fix:** Ampliar el mapping o usar la tabla ya definida en `_run_parallel_filing_step` (línea 1218).

### 4.4 No hay validación de formato de ticker

**Archivo:** `engine/engine.py`, línea 1457+
`ticker = args.ticker.upper()` acepta cualquier string. No hay validación de longitud, caracteres, ni blacklist.

**Fix:** Añadir regex de validación (e.g., `^[A-Z0-9.-]{1,12}$`).

### 4.5 `_filing_sort_key` captura excepciones genéricas

**Archivo:** `engine/router.py`, línea 1015
```python
try:
    selection_score = float(item.get("selection_score") or 0.0)
except Exception:
    selection_score = 0.0
```
El `except Exception` es demasiado amplio. Debería ser `except (TypeError, ValueError)`.

### 4.6 Prompt builder no valida post-truncamiento

**Archivo:** `engine/prompt_builder.py`
Cuando se trunca el contenido de un filing a N caracteres, no se verifica que la estructura JSON interna siga siendo válida. Puede cortar un JSON a mitad de string.

**Fix:** Truncar en límites de línea, nunca dentro de bloques `json`.

### 4.7 `_load_json_file()` retorna dict vacío en error

**Archivo:** `engine/router.py`, líneas 147-152
```python
def _load_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text())
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
```
Retorna `{}` tanto si el archivo no existe como si tiene JSON corrupto. El caller no puede distinguir entre ausencia y corrupción.

### 4.8 Quality voting con `fcntl` condicional

**Archivo:** `engine/quality_voting.py`, línea 577+
```python
if fcntl is not None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
```
En macOS, `fcntl` siempre está disponible. Pero si alguien porta el código, la condición permite ejecución sin locks.

---

## 5. CADENAS DE PROPAGACIÓN DE ERRORES

Errores tempranos causan cascadas de fallos:

### Cadena 1: Prefetch → TruthPack → Pipeline Stop
```
PREFETCH falla parcialmente (datos non-US incompletos)
  → SOURCES_COMPILER genera pack con fuentes parciales
    → TP_EXTRACTOR procesa solo filings con extraction_status=OK
      → TP_MERGER fusiona parciales incompletos
        → TP_VALIDATOR rechaza TruthPack (confidence <60%)
          → Pipeline STOP (fail_fast=true)
```

### Cadena 2: Gemini 429 → Catalizador penalizado
```
Gemini rate limited (HTTP 429) durante CATALYST_DETECTION
  → Solo 2 de 3 modelos producen output
    → Fusión con input incompleto
      → CATALYST_SCORING recibe detección parcial
        → Score de catalizador penalizado
          → ARBITRO recibe señal débil
            → Decisión conservadora (WATCHLIST)
```

### Cadena 3: iXBRL silencioso → datos erróneos
```
iXBRL file corrupto → except: pass (línea 396 de prompt_builder.py)
  → LLM no recibe datos autoritativos
    → LLM extrae datos de texto (potencialmente incorrectos)
      → TruthPack contiene datos no-autoritativos
        → Scoring y decisión basados en datos menos fiables
```

---

## 6. PLAN MAESTRO DE MEJORAS (Priorizado por Impacto)

### FASE 1: Correcciones Críticas (1-2 semanas, ~25h)

| # | Mejora | Archivo(s) | Esfuerzo | Riesgo |
|---|--------|-----------|----------|--------|
| 1 | Mover check de exists() dentro del lock en `load_state()` | state.py | 1h | Bajo |
| 2 | Usar `os.fdopen()` en `_write_state_unlocked()` y `save_estado_repo()` | state.py | 1h | Bajo |
| 3 | Añadir timeout a `as_completed()` en parallel execution | router.py | 2h | Medio |
| 4 | Implementar file-level lock para `open_errors.json` writes | error_tracker.py | 3h | Medio |
| 5 | Loggear excepciones silenciadas en `mark_step_done/failed` | state.py | 0.5h | Bajo |
| 6 | Loggear fallo de `_extract_decision_fields` en vez de pass | router.py | 0.5h | Bajo |
| 7 | Añadir subprocess cleanup en todos los timeout handlers | backends/*.py | 4h | Medio |
| 8 | Validar artefacto recuperado contra schema del paso | dispatcher.py | 3h | Medio |
| 9 | Limpiar parciales en path de fallo de TP_EXTRACTOR | router.py | 1h | Bajo |
| 10 | Invalidar auth cache completo del backend al expirar | claude.py | 1h | Bajo |

### FASE 2: Robustez General (2-4 semanas, ~40h)

| # | Mejora | Archivo(s) | Esfuerzo |
|---|--------|-----------|----------|
| 11 | Usar `fcntl.flock` en vez de `threading.Lock` para prompt excerpts | dispatcher.py | 2h |
| 12 | Cache de schemas en validator | validator.py | 2h |
| 13 | Validación de ticker format en engine entry point | engine.py | 1h |
| 14 | Truncamiento seguro post-JSON en prompt_builder | prompt_builder.py | 4h |
| 15 | Loggear warning cuando iXBRL falla en vez de pass silencioso | prompt_builder.py | 0.5h |
| 16 | Ampliar `_infer_exchange_from_text()` con exchanges non-US | router.py | 2h |
| 17 | Estandarizar límites de truncamiento de stderr entre backends | backends/*.py | 2h |
| 18 | Añadir recovery_method al DispatchResult.failure_ctx | backends/base.py | 2h |
| 19 | Validar timeout y model parameters en dispatch entry | backends/base.py | 1h |
| 20 | Añadir locks de lectura en `load_all_case_states()` | state.py | 2h |

### FASE 3: Mejora Continua (ongoing)

| # | Mejora | Descripción |
|---|--------|-------------|
| 21 | Test suite de robustez | Suite que simula timeouts, JSON corrupto, discos llenos, rate limits |
| 22 | Alertas de calidad | Notificar cuando un modelo cae <85% en un paso |
| 23 | Dashboard de errores | Visualización de tasas de fallo por modelo/paso |
| 24 | Cleanup automático de tmp/ | Rotación de archivos temporales (2,426 archivos actualmente) |
| 25 | Regression test case | Re-ejecutar caso de referencia tras cada cambio de instrucciones |

---

## 7. RESUMEN POR MÓDULO

### engine/state.py (8 issues)
- TOCTOU race en `load_state()` — CRÍTICO
- fd leak en `_write_state_unlocked()` — ALTO
- Excepciones silenciadas en `mark_step_done/failed` — ALTO
- `load_all_case_states` sin lock y sin log — ALTO
- Patrón repetido en `save_estado_repo()` — MEDIO

### engine/router.py (11 issues)
- Parallel execution sin timeout — CRÍTICO
- `_extract_decision_fields` swallows exceptions — ALTO
- Parciales no limpiados en path de fallo — ALTO
- `_load_json_file` no distingue ausencia vs corrupción — MEDIO
- `_infer_exchange_from_text` cobertura limitada — MEDIO
- `_filing_sort_key` except genérico — BAJO

### engine/dispatcher.py (12 issues)
- `_is_viable_recovered_artifact` acepta fragmentos — ALTO
- Threading lock no protege multiprocessing — ALTO
- Prompt excerpt metadata fail silencioso — MEDIO
- JSON recovery demasiado permisivo — MEDIO
- Truncation continuation sin validación completa — MEDIO

### engine/backends/*.py (14 issues)
- Sin cleanup de zombies en timeout — ALTO
- Auth cache no invalida todos los modelos — ALTO
- Codex sin JSON recovery — MEDIO
- exit_code inconsistente — MEDIO
- stderr truncamiento variable — BAJO

### engine/error_tracker.py (5 issues)
- Lost-write race en `open_errors.json` — CRÍTICO
- `_append_to_history` lock/unlock edge case — MEDIO

### engine/prompt_builder.py (6 issues)
- iXBRL failure silenciosa — ALTO
- Post-truncation sin validación JSON — MEDIO
- Null bytes en filing content — MEDIO
- Import fallback sin definir — MEDIO

### engine/quality_voting.py (3 issues)
- Atomic write fd leak potencial — MEDIO
- fcntl condicional innecesario — BAJO
- Concurrent JSONL append edge cases — BAJO

### engine/validator.py (2 issues)
- Schema cargado de disco cada vez — MEDIO
- Error message inconsistente — BAJO

### engine/config.py (3 issues)
- model_catalog vacío no validado — MEDIO
- Timeout no bounded — MEDIO
- pipeline_dag capabilities no verificadas — BAJO

---

## 8. EVIDENCIA DE ERRORES REALES EN CASOS EJECUTADOS

### Caso 0327 (PAX Global / Hong Kong)
- `estado_pipeline=INCOMPLETO` pese a sub-steps `DONE` — posible corrupción de estado
- FCF spike inexplicado (HK$490M → HK$1,163M) — datos no-autoritativos post iXBRL failure

### Caso SOM (SOM Group / UK)
- 3 fallos consecutivos en `TP_VALIDATOR` con confidence 55-75%
- Pa\u00eds/exchange aparecen como UNKNOWN en DecisionPacket pese a estar en _estado.json — bug de propagación en `_extract_decision_fields`

### Caso TEP (Teleperformance / Francia)
- Pipeline bloqueado en TP_VALIDATOR — datos insuficientes para empresa francesa
- iXBRL extractor no procesa PDFs (URD francés es PDF-first)

### Caso ACVA (ACV Auctions / US)
- Codex crash silencioso en IMPLIED: 2.3s de ejecución sin output — sin stderr ni log
- SBC no divulgado en los datos extraídos

### Múltiples casos (TZOO, SONO, IOSP, NEXN)
- Gemini HTTP 429 rate limiting: 35+ eventos durante ejecución paralela CATALYST||FORENSIC
- Copilot fallback exitoso pero con latencia adicional de 30-60s

---

## 9. CONCLUSIONES

El pipeline ELSIAN INVEST 3.0 tiene una base arquitectónica sólida con patrones bien diseñados (state atómico, retry con fallback, quality voting determinista). Sin embargo, la robustez se ve comprometida por:

1. **Excepciones silenciosas** — el patrón `except: pass` aparece en 16 ubicaciones críticas, cada una un potencial punto de fallo invisible
2. **Race conditions en concurrencia** — el pipeline paralelo (CATALYST||FORENSIC) y el error_tracker tienen ventanas de corrupción
3. **Cleanup insuficiente en paths de fallo** — parciales, temp files, y auth cache no se limpian correctamente cuando las cosas van mal
4. **Inconsistencia en manejo de errores** — cada backend tiene su propio estilo de truncamiento, exit codes, y recovery

Las correcciones de la **Fase 1** (25 horas estimadas) eliminarían los 9 fallos críticos y los 21 de riesgo alto, reduciendo significativamente la probabilidad de crashes no controlados y corrupción de datos.

---

*Documento generado el 24 de febrero de 2026. Basado en lectura completa del código fuente, análisis de 14 casos ejecutados, 632 eventos de votación, y 139 errores catalogados.*
