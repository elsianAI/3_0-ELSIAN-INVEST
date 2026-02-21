# Quality Voting v1 (Determinista)

## Objetivo
`quality_voting` añade un score de calidad **determinista** para cada step LLM del pipeline principal (`PIPELINE`) sin introducir bloqueos nuevos en producción.

- Modo v1: `deterministic_only`
- Política v1: `report_only`
- Sin juez LLM en v1
- Sin umbrales de PASS/WARN/FAIL en v1

## Alcance v1
Se votan solo steps con `type != python` dentro de `pipeline_dag.PIPELINE`.

Quedan fuera en v1:
- operaciones (`MONITOR`, `SCANNER`, `SCOUT`, `OUTCOME`, `EVALUAR`, `BENCHMARK`) cuando `include_operations=false`
- multi-subject voting (`multi_subjects.enabled=false`)

## Configuración
Se configura en `engine_config.json` bajo `quality_voting`.

Campos clave:
- `enabled`: activa/desactiva voting
- `mode`: `deterministic_only`
- `policy`: `report_only`
- `global_log_path`: log global append-only JSONL
- `per_case_dirname`: carpeta por caso para `StepVote_v1`
- `min_runs_for_stats`: umbral mínimo para tendencias en dashboard
- `critical_fields`: campos críticos por tipo de artefacto

`config_hash` se calcula **solo** sobre la subsección `quality_voting`.

## Reglas deterministas (pesos uniformes)
Para artefactos LLM estándar:
1. `schema_valid`
2. `critical_fields_completeness`
3. `null_ratio`

Cada regla pesa `1.0`. El score final es media ponderada (0-100).

## Caso especial: `TP_EXTRACTOR_FILING`
No usa schema de artefacto final en este punto. En su lugar:
- score por filing = `% de secciones con datos` sobre:
  - `historico_anual`
  - `historico_trimestral`
  - `balance_sheet_ultimo`
- score agregado del step = media simple de filings válidos

## Persistencia
Por cada step votado:
1. Se escribe `StepVote_v1` en `caso/.../_votes/`
2. Se añade `VoteEvent_v1` al JSONL global (`_evaluacion/votes_log_v1.jsonl`)

El append global se hace con lock de archivo y `fsync` para tolerar ejecuciones concurrentes.

## Dashboard
`python3 -m engine dashboard --quality` muestra:
- cobertura de votos
- media/mediana por step
- reglas más falladas
- aviso de muestra insuficiente cuando `runs < min_runs_for_stats`

Sin `--quality`, el dashboard permanece igual.
