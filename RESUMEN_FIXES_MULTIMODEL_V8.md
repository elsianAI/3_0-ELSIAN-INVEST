# Resumen Fixes Multi-Model v8 — Para revisión de Codex

## Fecha: 2026-02-19

---

## CAMBIOS v8 (sobre v7, incorporando feedback de Codex)

Codex detectó 4 problemas en v7. Los 4 resueltos:

### [P1] Preflight ya NO repite inferencia pagada en cada step

**Antes**: `check_available()` hacía `-p "respond with ok"` en cada llamada → 3 backends × 3 steps multi = 9 llamadas pagadas por pipeline.

**Ahora**: Caché TTL de 10 minutos a nivel de módulo. Key = `(binary_path, model)`.

```python
# engine/backends/claude.py (y gemini.py análogo)
_AUTH_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}
_AUTH_CACHE_TTL = 600  # 10 min

def check_available(self) -> bool:
    cache_key = (self.binary_path, self.model)
    cached = _AUTH_CACHE.get(cache_key)
    if cached:
        ts, result = cached
        if time.time() - ts < _AUTH_CACHE_TTL:
            return result  # ← cached, 0 tokens
    # ... run check, cache result ...
```

**Coste real**: 1 llamada por backend por cada 10 min. En un pipeline típico (~15-30 min), máximo 1-2 preflights por backend.

### [P1] Preflight valida el modelo real configurado

**Antes**: `check_available()` no pasaba `--model` → podía pasar con modelo default pero fallar con el modelo del step.

**Ahora**: Incluye `--model self.model` en el prompt de preflight:

```python
auth = subprocess.run(
    [self.binary_path, "-p", "respond with ok",
     "--model", self.model,  # ← valida el modelo real
     "--output-format", "json", "--max-turns", "1",
     "--no-session-persistence"],
    ...
)
```

### [P2] `backends_used` viene del dispatcher, no de glob en disco

**Antes**: El router hacía `glob("_multi_{STEP}_*.json")` y parseaba el nombre con `split("_")[-1]` → rompía con `codex_spark`, incluía traces stale.

**Ahora**: `DispatchResult` tiene campo `backends_used: list[str] | None` que se setea directamente en `dispatch_multi_and_fuse()` a partir de `successful_outputs.keys()`:

```python
# base.py — DispatchResult
backends_used: list[str] | None = None

# dispatcher.py — dispatch_multi_and_fuse()
used = sorted(successful_outputs.keys())
fusion_result.backends_used = used

# router.py — usa result.backends_used directamente
return {"backends_used": result.backends_used, ...}
```

### [P2] Gemini preflight ahora parsea envelope como Claude

**Antes**: Solo comprobaba `returncode == 0` → falsos "available" si Gemini devolvía error con exit 0.

**Ahora**: Parsea `json.loads(auth.stdout)` y comprueba `is_error` en el envelope, idéntico a Claude. También con caché TTL.

---

## FICHEROS MODIFICADOS EN v8

| Fichero | Cambio |
|---------|--------|
| `engine/backends/base.py` | `DispatchResult.backends_used: list[str] | None` |
| `engine/backends/claude.py` | `check_available()` con caché TTL + `--model self.model` + `import sys` |
| `engine/backends/gemini.py` | `check_available()` con caché TTL + `--model self.model` + parseo envelope |
| `engine/dispatcher.py` | Setea `backends_used` en los 3 puntos de retorno de `dispatch_multi_and_fuse()` |
| `engine/router.py` | Usa `result.backends_used` en vez de glob |

---

## RESUMEN ACUMULADO (v6 + v7 + v8)

### Calidad de fusión (v6):
- Claude: markdown extraction fallback + is_error detection
- Gemini: envelope unwrapping de `response` field
- RED_TEAM naming: alias resolution REDTEAM ↔ RED_TEAM con fusión preference
- Normalización defensiva en prompt_builder
- Doble traza (raw + normalizado), per-model voting, ARBITRO audit

### Política de bloqueo (v7):
- `min_backends` configurable por step (default=3)
- Pre-flight check antes del paralelo
- Post-dispatch check en dispatch_multi_and_fuse

### Robustez (v8):
- Caché TTL 10 min para preflights (no repite inferencia)
- Validación del modelo real configurado
- `backends_used` desde datos del dispatcher (no glob)
- Gemini preflight con parseo envelope completo

---

## COMPILACIÓN

Todos los ficheros compilan OK: `base.py`, `claude.py`, `gemini.py`, `dispatcher.py`, `router.py`.

## PENDIENTE

- Ejecutar tests `_test_engine.py` (24) y `_test_v5.py` (12)
- Relanzar pipeline ACVA/SOM para validar end-to-end
