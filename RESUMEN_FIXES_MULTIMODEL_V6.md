# Resumen de Fixes Multi-Model Pipeline — Para revisión de Codex

## Fecha: 2026-02-18
## Scope: Corrección de bugs de calidad en flujo multi-model (BULL, RED_TEAM, ARBITRO)

---

## PROBLEMA RAÍZ

El pipeline multi-model ejecuta 3 backends (codex, gemini, claude) en paralelo para steps BULL, RED_TEAM y ARBITRO. Los resultados se fusionan vía Claude. Se detectaron **5 bugs** que causaban pérdida de calidad:

1. Los backends Claude y Gemini devuelven **envelopes** (metadatos del CLI) en vez del payload del artifact limpio
2. La fusión recibía esos envelopes (34KB con metadatos vs 27KB de contenido útil)
3. ARBITRO podía consumir un archivo RED_TEAM individual (3 claims) en vez del fusionado (7 claims) por colisión de nombres
4. No existía trazabilidad per-model ni auditoría de qué archivos consumía ARBITRO
5. **[NUEVO - detectado en ACVA]** Claude CLI devuelve `is_error: true` (e.g. "Not logged in") con exit code 0, y `claude.py` lo trataba como éxito → el envelope de error se pasaba al fusionador como output válido

---

## FICHEROS MODIFICADOS (5)

### 1. `engine/backends/claude.py` — Bug 1 + Bug 5

**Bug 1 — Markdown extraction**: `json.loads(result_text)` falla cuando Claude devuelve resultado envuelto en markdown (` ```json ... ``` `). El fallback retornaba el envelope completo.

**Fix Bug 1**: Añadido regex fallback para extracción de JSON desde markdown fences entre el `json.loads` y el fallback a envelope.

**Bug 5 — Error envelope no detectado** (detectado en run ACVA): Claude CLI puede retornar exit code 0 pero con `is_error: true` en el JSON envelope (e.g. "Not logged in · Please run /login", errores de auth, etc.). El código anterior no comprobaba `is_error`, así que el envelope de error se trataba como éxito.

**Fix Bug 5**: Check de `envelope.get("is_error")` **antes** de intentar extraer el resultado:

```python
# Check for error envelope FIRST
if isinstance(envelope, dict) and envelope.get("is_error"):
    error_msg = envelope.get("result", "Unknown Claude CLI error")
    return DispatchResult(
        False, None, raw, self.model, "claude", duration,
        f"Claude CLI error: {str(error_msg)[:500]}"
    )
```

**Impacto verificado con ACVA**: El envelope `{is_error: true, result: "Not logged in"}` ahora retorna `DispatchResult(success=False)` → el dispatcher lo excluye de la fusión → solo Gemini y Codex se fusionan correctamente.

---

### 2. `engine/backends/gemini.py` — Bug 2

**Problema**: `_extract_json(raw)` parsea exitosamente el envelope `{session_id, response, stats}` como JSON válido, pero retorna el envelope en vez del AgentReport que está dentro de `envelope.response` como string markdown.

**Fix**: Post-parse check para detectar envelope y extraer inner payload:

```python
if (isinstance(output, dict)
        and "response" in output
        and ("session_id" in output or "stats" in output)):
    inner = _extract_json(str(output["response"]))
    if inner is not None and isinstance(inner, dict):
        output = inner
```

**Impacto verificado (SOM)**: Gemini BULL trace 17,028 bytes → 11,284 bytes (-34%).

---

### 3. `engine/router.py` — Bug 3 + Extras

**Bug 3 — RED_TEAM naming collision**:

Existían dos ficheros:
- `AgentReport_v1_REDTEAM_SOM_*.json` (fusionado, 7 claims, `_meta.fusion` presente)
- `AgentReport_v1_RED_TEAM_SOM_*.json` (individual Gemini, 3 claims)

**Fix `_find_artifact()`**:
- Alias resolution bidireccional: `REDTEAM ↔ RED_TEAM`
- Si hay matches primarios + alias, WARNING logueado + preferencia al primario
- Si hay múltiples matches, preferencia a artifacts con `_meta.fusion=True`
- Fallback: longest name → lexicographic last

**Extra — Per-model quality voting** (`_vote_per_model()`):
- Nueva función que lee `_multi_{STEP}_{backend}.json` traces
- Ejecuta `maybe_vote_step()` con step_name=`{STEP}__model_{backend}`
- Permite comparar calidad individual vs fusionada en los votes

**Extra — ARBITRO input audit trail**:
- `_resolve_input_artifacts()` ahora loguea qué ficheros se resolvieron
- Para ARBITRO: genera `_arbitro_input_audit.json` con nombres y tamaños de artifacts consumidos

---

### 4. `engine/prompt_builder.py` — Bug 4 + defensa Bug 5

**Bug 4**: `build_fusion_prompt()` pasaba outputs raw sin normalizar.

**Fix**:
- Nueva función `_normalize_backend_output()` — capa defensiva que desenvuelve envelopes Claude y Gemini
- Añadido early-return para `is_error: true` envelopes (defensa en profundidad para Bug 5)
- `build_fusion_prompt()` llama `_normalize_backend_output()` antes de serializar

---

### 5. `engine/dispatcher.py` — Extra: Doble traza + normalización temprana

**Mejora**: `dispatch_multi_and_fuse()` ahora:
1. Normaliza outputs antes de pasarlos a fusión (via `_normalize_backend_output`)
2. Persiste dos ficheros por backend:
   - `_multi_raw_{STEP}_{backend}.json` — Output tal cual del CLI (con envelope)
   - `_multi_{STEP}_{backend}.json` — Payload normalizado (limpio)

---

## VERIFICACIÓN REALIZADA

1. **Compilación**: Los 5 ficheros compilan sin errores
2. **Test SOM (datos reales)**:
   - Claude envelope 34KB → normalizado 27KB correctamente
   - Gemini envelope 17KB → normalizado 11KB correctamente
   - Codex sin cambio (ya limpio, 21KB)
   - `_find_artifact("AgentReport_v1_REDTEAM")` → encuentra fusionado correcto
3. **Test ACVA (datos reales con error)**:
   - Claude `is_error: true` + `"Not logged in"` → ahora retorna `success=False`
   - El envelope de error NO se pasa al fusionador
   - Gemini y Codex outputs siguen normalizándose correctamente

---

## PENDIENTE

- **Relanzar pipeline ACVA** para verificar end-to-end con los fixes
- **Verificar sesión Claude CLI**: ejecutar `claude /login` si la sesión ha expirado
- **Considerar**: añadir check de auth en `check_available()` de `ClaudeBackend` para detectar problemas de login antes de despachar

---

## CORRESPONDENCIA CON PLAN DE CODEX

| Fase Codex | Nuestro Fix | Estado |
|---|---|---|
| Fase 1: Naming RED_TEAM | Bug 3: `_find_artifact()` con aliases + fusion preference | ✅ |
| Fase 2: Normalizar envelopes | Bug 1 (claude) + Bug 2 (gemini) + Bug 4 (prompt_builder) | ✅ |
| Fase 3: Garantía input ARBITRO | Bug 3 + audit trail `_arbitro_input_audit.json` | ✅ |
| Fase 4: Quality voting per-model | `_vote_per_model()` en router.py | ✅ |
| Extra: doble traza | `_multi_raw_*` en dispatcher.py | ✅ |
| **NUEVO: Bug 5 (is_error)** | claude.py + prompt_builder.py defensa | ✅ |

**Diferencias de approach**:
- Codex propone módulo separado `engine/output_parser.py`; nosotros integramos inline en backends + capa defensiva en prompt_builder. Menor surface area, mismo resultado.
- Codex propone cambiar convención canónica a `RED_TEAM` (con underscore); nosotros mantenemos `REDTEAM` como canónico (ya usado en `_get_artifact_filename` y `STEP_INPUT_ARTIFACTS`), con alias bidireccional como fallback.
