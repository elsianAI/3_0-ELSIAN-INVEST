# Resumen Fixes Multi-Model v9 — Para revisión de Codex

## Fecha: 2026-02-19

---

## CAMBIOS v9 (sobre v8, incorporando feedback de Codex)

Codex detectó 3 problemas en v8. Los 3 resueltos:

### [C1] Cache TTL diferenciado: éxitos 10min, fallos 60s

**Antes**: `_AUTH_CACHE_TTL = 600` único → si un backend fallaba (ej: "Not logged in"), el fallo se cacheaba 10 minutos. El usuario hacía `/login`, relanzaba el pipeline, y el caché seguía devolviendo `False` durante 9 minutos más.

**Ahora**: Dos TTLs separados:

```python
# claude.py y gemini.py
_AUTH_CACHE_TTL_OK = 600    # 10 min for successes (avoid repeated paid calls)
_AUTH_CACHE_TTL_FAIL = 60   # 60s for failures (allow quick retry after fix)

# Al consultar caché:
ttl = _AUTH_CACHE_TTL_OK if result else _AUTH_CACHE_TTL_FAIL
if time.time() - ts < ttl:
    return result
```

**Efecto**: Tras hacer login/fix, el usuario puede reintentar en ~60s en vez de esperar 10min.

### [C2] Gemini non-JSON preflight → False (no True)

**Antes**: Si el preflight de Gemini devolvía texto no-JSON (stdout con texto plano), el `except json.JSONDecodeError: pass` caía al `return True` → falso positivo de "available".

**Ahora**: Non-JSON con `--output-format json` = backend no saludable → `return False`:

```python
# gemini.py check_available()
stdout = (auth.stdout or "").strip()
if not stdout:
    # Empty stdout → not healthy
    _AUTH_CACHE[cache_key] = (time.time(), False)
    return False
try:
    envelope = json.loads(stdout)
    if isinstance(envelope, dict) and envelope.get("is_error"):
        _AUTH_CACHE[cache_key] = (time.time(), False)
        return False
except json.JSONDecodeError:
    # Non-JSON from --output-format json → not healthy
    print(f"[gemini] Pre-flight check FAILED: non-JSON response: {stdout[:150]}")
    _AUTH_CACHE[cache_key] = (time.time(), False)
    return False
```

**Aplicado también a claude.py** para consistencia.

### [C3] Claude auth check gratuito: `claude auth status`

**Antes**: `check_available()` ejecutaba `-p "respond with ok"` → inferencia pagada (~2s, tokens consumidos). Multiplicado por cada pipeline, era coste innecesario.

**Ahora**: Fase 2a intenta `claude auth status` (FREE, 0 tokens, ~200ms). Solo si `auth status` no está disponible (CLI antigua sin ese subcomando), cae a la inferencia pagada como fallback legacy:

```python
# claude.py check_available()

# Phase 2a: Try `claude auth status` (FREE — no tokens)
try:
    auth = subprocess.run(
        [self.binary_path, "auth", "status"],
        capture_output=True, text=True, timeout=15,
    )
    if auth.returncode != 0:
        _AUTH_CACHE[cache_key] = (time.time(), False)
        return False
    status_text = (auth.stdout or "").lower()
    if "not logged in" in status_text or "no active" in status_text:
        _AUTH_CACHE[cache_key] = (time.time(), False)
        return False
    _AUTH_CACHE[cache_key] = (time.time(), True)
    return True
except (subprocess.TimeoutExpired, FileNotFoundError):
    pass  # auth status not available → fall back to paid prompt

# Phase 2b: Fallback — lightweight paid prompt (legacy)
# ... (código existente de v8)
```

**Nota sobre validación de modelo**: `auth status` no soporta `--model`. Los errores de modelo inválido se detectarán en `dispatch()` y el step se bloqueará igualmente vía `min_backends`. Trade-off aceptable: 0 tokens vs detección de modelo diferida.

---

## FICHEROS MODIFICADOS EN v9

| Fichero | Cambio |
|---------|--------|
| `engine/backends/claude.py` | TTL diferenciado + `auth status` free + non-JSON → False |
| `engine/backends/gemini.py` | TTL diferenciado + non-JSON → False + empty stdout → False |

---

## RESUMEN ACUMULADO (v6 + v7 + v8 + v9)

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

### Robustez preflight (v8):
- Caché TTL para preflights (no repite inferencia)
- Validación del modelo real configurado
- `backends_used` desde datos del dispatcher (no glob)
- Gemini preflight con parseo envelope completo

### Preflight hardening (v9):
- Cache TTL diferenciado: OK=10min, FAIL=60s (retry rápido)
- Non-JSON preflight response → False (no falso positivo)
- Claude `auth status` gratuito (0 tokens, ~200ms)
- Fallback a inferencia pagada solo si CLI no soporta `auth status`

---

## COMPILACIÓN

Todos los ficheros compilan OK: `claude.py`, `gemini.py`.

## PENDIENTE

- Ejecutar tests `_test_engine.py` (24) y `_test_v5.py` (12)
- Relanzar pipeline ACVA/SOM para validar end-to-end
- Cuando todas las instancias de Claude CLI tengan `auth status`, eliminar Phase 2b (fallback pagado)
