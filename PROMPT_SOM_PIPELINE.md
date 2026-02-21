# Tarea: Pipeline SOM (LON:SOM) bien definido y reproducible

## Contexto

Este repo es ELSIAN INVEST 3.0. SOM (Somero Enterprises Inc) es non-US (LSE), por lo que **el run principal debe usar hints** (`--exchange`, `--country`, `--web-ir`).

Objetivo: ejecutar y documentar el pipeline de forma reproducible, con evidencia completa, sin cambios de codigo.

## Reglas de ejecucion

1. No modificar engine, runners ni config.
2. Capturar stdout+stderr de cada comando importante en `tmp/*.log`.
3. Si un paso falla, documentar exactamente el error y el estado parcial.
4. No inventar resultados: todo debe salir de artefactos/logs.

## Fase 0 — Pre-check

```bash
cd /Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST

python3 -c "from engine.router import execute_pipeline; print('Engine OK')"
python3 -m engine dashboard
python3 -m py_compile engine/engine.py engine/router.py engine/dispatcher.py engine/prompt_builder.py
```

## Fase 1 — Reset del caso SOM

```bash
rm -rf casos/SOM
```

Verificar que no existe:

```bash
test ! -d casos/SOM && echo "OK: casos/SOM borrado"
```

## Fase 2 — Run principal (CON hints, obligatorio)

Comando canonico:

```bash
python3 -m engine pipeline SOM --date 2026-02-17 \
  --exchange LSE --country GB \
  --web-ir https://www.somero.com/investors \
  2>&1 | tee tmp/som_2026-02-17_pipeline.log
```

## Fase 3 — Validacion post-run principal

### 3.1 Estado e hints persistidos

```bash
python3 << 'PYEOF'
import json
from pathlib import Path
p = Path('casos/SOM/2026-02-17/_estado.json')
s = json.loads(p.read_text())
print('estado_pipeline:', s.get('estado_pipeline'))
print('empresa_hints:', s.get('empresa_hints'))
print('pipeline:', {k:v.get('estado') for k,v in s.get('pipeline',{}).items()})
PYEOF
```

### 3.2 Fuentes y cobertura

```bash
python3 << 'PYEOF'
import json, collections
from pathlib import Path
sp = Path('casos/SOM/2026-02-17/SourcesPack_v1_SOM_2026-02-17.json')
j = json.loads(sp.read_text())
f = j.get('fuentes', [])
print('fuentes_total:', len(f))
print('with_local_path:', sum(1 for x in f if x.get('local_path')))
print('tipos:', dict(collections.Counter((x.get('tipo') or 'N/A') for x in f)))
print('cobertura_documental:', j.get('cobertura_documental', {}))
PYEOF
```

### 3.3 Evidencia de resolver IR

No depende solo del log global. Revisar outputs de fetchers:

```bash
rg -n "investors\.somero\.com|web_ir|Resolved|ir_url_resolver" \
  casos/SOM/2026-02-17/_sec_fetcher_output.json \
  casos/SOM/2026-02-17/_transcript_finder_output.json \
  tmp/som_2026-02-17_pipeline.log || true
```

## Fase 4 — Continue sin flags (persistencia de hints)

```bash
python3 -m engine continue SOM --date 2026-02-17 \
  2>&1 | tee tmp/som_2026-02-17_continue.log
```

Esperado: ejecuta sin volver a pasar `--exchange/--country/--web-ir`.

## Fase 5 — Test negativo separado (SIN hints)

Ejecutar en otra fecha para no contaminar el run principal:

```bash
python3 -m engine pipeline SOM --date 2026-02-18 \
  2>&1 | tee tmp/som_2026-02-18_no_hints.log
```

Verificar estado:

```bash
python3 << 'PYEOF'
import json
from pathlib import Path
s = json.loads(Path('casos/SOM/2026-02-18/_estado.json').read_text())
print('estado_pipeline:', s.get('estado_pipeline'))
print('pipeline:', {k:v.get('estado') for k,v in s.get('pipeline',{}).items()})
print('_errors:', s.get('_errors', {}))
PYEOF
```

Esperado en test negativo:
- SOURCES no debe romper por plumbing.
- Si falla, debe fallar en TRUTH_PACK por cobertura/calidad.

## Criterios de aceptacion (PASS/FAIL)

### PASS principal
- Se ejecuto Fase 2 con hints (comando exacto).
- `empresa_hints` persistidos en `_estado.json` (no null).
- `SourcesPack` no vacio y con `local_path` util.
- El resolver IR se evidencia en outputs de fetchers.

### PASS persistencia
- `continue` (Fase 4) funciona sin flags.

### PASS test negativo
- Run sin hints (Fase 5) muestra fallo controlado en TRUTH_PACK (no bug de SOURCES).

## Entregable obligatorio

Generar `INFORME_PIPELINE_SOM.md` en la raiz con esta estructura minima:

1. Resumen ejecutivo (estado final run principal, tiempo, steps)
2. Comandos ejecutados (copiados literal)
3. Evidencias por fase (extractos de logs + rutas de artefactos)
4. Resultado PASS/FAIL de cada criterio
5. Riesgos residuales y siguiente paso recomendado

## Nota clave

El run principal de SOM **siempre** debe ejecutarse con hints non-US. Si se ejecuta sin hints, el resultado no es valido para evaluar soporte non-US.
