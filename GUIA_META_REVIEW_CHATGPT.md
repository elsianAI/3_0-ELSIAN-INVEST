# Guía Paso a Paso: Meta-Review en proyecto ChatGPT + pruebas end-to-end

## Resumen
Objetivo: operar el flujo completo de meta-review (prompt → ChatGPT Project → ingesta → visualización) y validar que funciona en producción.

Rutas clave del sistema:
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/review_compiler.py`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/review_ingest.py`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/engine.py`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/dashboard.py`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_schemas/review/MetaReview_v1.json`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/scripts/review/generate_project_package.py`

## Interfaces públicas añadidas/cambiadas
1. CLI nuevo:
- `python3 -m engine review TICKER [--date YYYY-MM-DD]`
- `python3 -m engine review_ingest TICKER [--date YYYY-MM-DD] [--response PATH]`
- `python3 -m engine review_status [TICKER] [--date YYYY-MM-DD]`

2. Estado en `_estado.json`:
- Campo `meta_review` con `estado`, `artefacto`, `veredicto`, `meta_decision`, `prompt_timestamp`, `dp_hash`, `dp_ref`, `timestamp`.

3. Visualización:
- `python3 -m engine decisions` muestra tags MR (`[MR:CONFIRMA]`, `[MR:CUESTIONA]`, `[MR:RECHAZA]`, `[MR:NO_EVAL]`, `[MR:PEND]`, `[MR:PARCIAL]`).

---

## Parte A: Setup único del proyecto ChatGPT
1. Ve al root del repo:
```bash
cd "/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST"
```

2. Genera el paquete para ChatGPT Project:
```bash
python3 scripts/review/generate_project_package.py
```

3. En ChatGPT web crea el proyecto `ELSIAN Meta-Review` con modelo `GPT-5.2 Pro`.

4. Copia como instrucciones del proyecto el contenido de:
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_review_project/INSTRUCCIONES_PROYECTO.md`

5. Adjunta al proyecto estos archivos:
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_review_project/MetaReview_v1_SCHEMA.json`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_review_project/DecisionPacket_v2_SCHEMA.json`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_review_project/AgentReport_v1_SCHEMA.json`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_review_project/METODOLOGIA_ELSIAN.md`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_review_project/CRITERIOS_REVIEW.md`
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_review_project/REGLAS_COMUNES_EXTRACTO.md`

---

## Parte B: Flujo operativo por caso (producción)
1. Genera prompt de review:
```bash
python3 -m engine review TZOO --date 2026-02-21
```

2. Abre y copia el prompt generado:
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/casos/TZOO/2026-02-21/_review_prompt_gpt52pro_{TS}.md`

3. Pega ese prompt en el proyecto ChatGPT `ELSIAN Meta-Review` y espera respuesta completa.

4. Guarda la respuesta completa en:
- `/Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/casos/TZOO/2026-02-21/_review_response_raw_{TS}.md`

5. Ingesta la respuesta:
```bash
python3 -m engine review_ingest TZOO --date 2026-02-21
```

6. Verifica estado global:
```bash
python3 -m engine review_status TZOO --date 2026-02-21
```

7. Verifica impacto en decisiones:
```bash
python3 -m engine decisions TZOO
python3 -m engine decisions TZOO -v
```

---

## Parte C: Plan de pruebas (qué probar y resultado esperado)

1. Happy path completo.
- Entrada: respuesta GPT con JSON válido `MetaReview_v1`.
- Esperado: archivo canónico `MetaReview_v1_TZOO_20260221.json`, `_estado.json.meta_review.estado = DONE`, tag MR visible en `decisions`.

2. Respuesta sin bloque JSON.
- Entrada: narrativa sin ```json.
- Esperado: se guarda `_review_narrative_gpt52pro_{TS}.md`, estado `PARCIAL`, `review_ingest` falla con mensaje claro.

3. JSON inválido de schema.
- Entrada: JSON con requeridos faltantes tras recovery.
- Esperado: no se persiste artifact canónico, estado `PARCIAL`, error de validación estricto.

4. Regeneración de prompt sobre caso ya revisado.
- Pasos: ejecutar `review` de nuevo en mismo caso.
- Esperado: `_estado.json.meta_review.estado = PROMPT_GENERADO` (invalida review anterior hasta nueva ingesta).

5. Rotación de revisiones.
- Pasos: ingestar dos veces con nuevas respuestas válidas.
- Esperado: artifact previo renombrado a `_revN`, nuevo artifact ocupa nombre canónico, `revision_num` monotónico.

---

## Troubleshooting rápido
1. `No se encuentra la respuesta de review`.
- Revisa nombre exacto `_review_response_raw_{TS}.md` en la carpeta del caso.
- Usa `review_status` para ver qué TS está esperando.

2. `Schema validation failed tras recuperación`.
- Pide a ChatGPT que regenere respuesta respetando estrictamente `MetaReview_v1_SCHEMA.json`.
- Mantén el bloque JSON final dentro de triple backticks con etiqueta `json`.

3. `review` falla por pipeline no completo.
- Completa pipeline del caso antes de meta-review.

4. No ves `quality votes` en prompt.
- Verifica que exista carpeta `_votes` dentro del caso y archivos `StepVote_v1_*.json`.

---

## Supuestos y defaults fijados
1. El flujo de review es explícito y manual (no automático en `pipeline`).
2. El proyecto ChatGPT usa `GPT-5.2 Pro`.
3. El timestamp `{TS}` del prompt gobierna el nombre del archivo de respuesta.
4. `MetaReview_v1` es informativo y no cambia automáticamente la decisión del ARBITRO.
