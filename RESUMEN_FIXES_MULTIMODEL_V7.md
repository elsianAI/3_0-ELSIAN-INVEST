# Resumen de Fixes Multi-Model Pipeline v7 — Para revisión de Codex

## Fecha: 2026-02-19
## Scope: Fixes de calidad + política de bloqueo si backend falla

---

## RESUMEN EJECUTIVO

Se han aplicado **2 rondas** de fixes al pipeline multi-model:

**Ronda 1 (v6)** — 5 bugs de calidad: envelopes no extraídos, naming collision RED_TEAM, normalización de fusion.

**Ronda 2 (v7)** — Cambio de política: si un backend falla en un step multi-model, el pipeline se **BLOQUEA** en vez de degradar silenciosamente. Detectado porque en ACVA, Claude falló con "Not logged in" en BULL y RED_TEAM (~130ms, 0 tokens) pero el pipeline marcó DONE con solo 2/3 backends.

---

## RONDA 1: FIXES DE CALIDAD (v6)

### Bug 1 — claude.py: Markdown extraction fallback
- `dispatch()` ahora extrae JSON de markdown fences (`\`\`\`json ... \`\`\``) cuando `json.loads(result_text)` falla
- Impacto: Claude envelope 34KB → payload limpio 27KB

### Bug 2 — gemini.py: Envelope unwrapping
- Post-parse check: si `output` tiene keys `response` + `session_id`, extrae el inner payload
- Impacto: Gemini envelope 17KB → payload 11KB

### Bug 3 — router.py: RED_TEAM naming collision
- `_find_artifact()` con alias resolution `REDTEAM ↔ RED_TEAM`
- Preferencia por artifacts con `_meta.fusion=True`
- Warning logueado cuando coexisten ambas variantes

### Bug 4 — prompt_builder.py: Normalización defensiva
- `_normalize_backend_output()` como capa defensiva en `build_fusion_prompt()`
- Detecta y desenvuelve envelopes de Claude y Gemini
- Early return para envelopes con `is_error: true`

### Bug 5 — claude.py: Error envelope detection
- Check de `envelope.get("is_error")` ANTES de intentar extraer resultado
- "Not logged in", errores de auth → `DispatchResult(success=False)`

### Extras (propuestas originales de Codex, implementadas):
- **Doble traza** en dispatcher: `_multi_raw_{STEP}_{backend}.json` (crudo) + `_multi_{STEP}_{backend}.json` (normalizado)
- **Per-model quality voting**: `_vote_per_model()` genera votos `{STEP}__model_{backend}`
- **ARBITRO audit trail**: `_arbitro_input_audit.json` con ficheros consumidos

---

## RONDA 2: POLÍTICA DE BLOQUEO (v7) — NUEVO

### Problema detectado en ACVA

Claude CLI no estaba logueado. El pipeline:
1. Lanzó 3 backends en paralelo (codex, gemini, claude)
2. Claude retornó `is_error: true` en 130ms → `"Not logged in · Please run /login"`
3. Gemini y Codex completaron correctamente
4. `dispatch_multi_and_fuse()` fusionó 2/3 → DONE
5. El usuario no se enteró de que perdió 1/3 de la diversidad

**Filosofía**: "Si falla un modelo, es motivo de bloquear la ejecución."

### Cambio 1: `check_available()` mejorado (claude.py, gemini.py)

Pre-flight auth check de 2 fases:
- Fase 1: `--version` (binario existe)
- Fase 2: prompt trivial `"respond with ok"` con `--output-format json` → detecta "Not logged in", API key inválida, etc. antes de lanzar el paralelo

```python
# claude.py — check_available() ahora hace:
# 1. claude --version → binary exists
# 2. claude -p "respond with ok" --output-format json --max-turns 1
#    → parse envelope → check is_error → detect auth failures
```

Coste: ~2s + unos pocos tokens. Pero evita lanzar un dispatch largo ($) que va a fallar.

### Cambio 2: `min_backends` en engine_config.json

Nueva config por step multi-model:

```json
"BULL": {
  "models": ["codex", "gemini", "claude"],
  "min_backends": 3
}
```

Default = `len(models)` = requiere todos. Si se quiere permitir degradación, se puede bajar a 2.

### Cambio 3: Pre-flight check en dispatch_step() — fail early

Si `check_available()` detecta que un backend no está operativo y `len(available) < min_backends`:

```
BLOCKED: Not enough backends for BULL: 2/3 available.
Unavailable: claude. Fix auth/connectivity for these backends before retrying.
```

El step se marca **FAILED** inmediatamente. No se lanzan los otros 2 backends (ahorra $ y tiempo).

### Cambio 4: Post-dispatch check en dispatch_multi_and_fuse()

Incluso si `check_available()` pasó pero el dispatch falló (ej: timeout de un backend):

```
BLOCKED: Insufficient backends for BULL: 2/3 succeeded.
Failed: claude: Claude CLI error: Not logged in · Please run /login
```

Doble red de seguridad.

### Cambio 5: `backends_used` en resultado del router

El resultado de un step multi-model ahora incluye qué backends contribuyeron:

```json
{
  "success": true,
  "artifact": "AgentReport_v1_BULL_...",
  "backends_used": ["codex", "gemini", "claude"]
}
```

---

## FICHEROS MODIFICADOS (total entre v6 y v7)

| Fichero | Cambios |
|---------|---------|
| `engine/backends/claude.py` | Bug 1 (markdown), Bug 5 (is_error), `check_available()` con auth pre-flight |
| `engine/backends/gemini.py` | Bug 2 (envelope), `check_available()` con auth pre-flight |
| `engine/router.py` | Bug 3 (aliases), per-model voting, audit trail, `backends_used` |
| `engine/prompt_builder.py` | Bug 4 (normalización defensiva) |
| `engine/dispatcher.py` | Doble traza, normalización, `min_backends` pre-flight + post-dispatch |
| `engine_config.json` | `min_backends: 3` por step multi-model |

---

## VERIFICACIÓN PENDIENTE

1. **Con Claude deslogueado**: `check_available()` → False → pipeline BULL falla inmediatamente con "BLOCKED: Not enough backends"
2. **Con Claude logueado**: pipeline completo con `backends_used: [codex, gemini, claude]`
3. **Tests**: `_test_engine.py` 24/24 y `_test_v5.py` 12/12
4. **Compilación**: Los 5 ficheros python + JSON compilan OK ✅

---

## PARA DISCUSIÓN CON CODEX

1. **¿Está de acuerdo con la política de bloqueo?** El default `min_backends = len(models)` es estricto. Alternativa: `min_backends = len(models) - 1` para tolerar 1 fallo.

2. **Pre-flight auth check**: consume ~2s + tokens. ¿Es aceptable el coste? Alternativa: cachear el resultado N minutos.

3. **Codex implementó `lookup_step_name` / `vote_step_name` en maybe_vote_step**: necesitamos verificar que nuestro `_vote_per_model()` use esos nuevos parámetros correctamente.

4. **`_find_artifact` de Codex**: prioriza fusionados antes que prefijo. Nosotros hacemos lo mismo pero con approach ligeramente distinto (alias bidireccional). Revisar si conviene unificar.

5. **Codex propone `engine/output_parser.py` como módulo separado**: nosotros lo tenemos inline. ¿Merece la pena un refactor a módulo separado para testabilidad?
