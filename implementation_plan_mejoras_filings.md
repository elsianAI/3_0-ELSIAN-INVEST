# V6.2 Plan Final (ajustado con revisión crítica): extracción robusta y generalista sin regresión

## Resumen
**Objetivo:** Elevar la calidad de SOURCES → TRUTH_PACK como producto propio, con trazabilidad por campo y despliegue incremental seguro.
Estado actual: Fase 1A completada, pendientes Fases 1B, 2 y 3.
Este plan incorpora los 9 ajustes críticos consensuados:
1. Chunking por sección (no token fijo ciego).
2. Pre-flight con unidades por sección.
3. Fase 1 dividida en 1A/1B.
4. Activar parciales de TP (`keep_tp_filing_partials: true`) para observabilidad durante rollout.
5. Cuantificar coste/latencia antes de activar chunking global (Benchmark A/B).
6. Conversión de moneda separada de extracción determinista (se hace en merger).
7. Gap-fill selectivo movido a Fase 3.
8. Umbral de reconciliación con fallback cuando no hay `total_assets`.
9. Lógica restatement simplificada pero sin perder jerarquía de calidad documental (Nota: El flag explícito `restatement_applied` no está forzado a materializarse; basta con la reconciliación material V6.1 actual).

---

## Estado Actual Real y Baseline V5.3
- **Baseline V5.3 consolidada:**
  - Robustecimiento market-data no-US.
  - Deuda por componentes estrictamente sin leases.
  - Recovery GCT fortalecido con fallback a filesystem + validations por fingerprinting/schema (no retroceder ni reabrir).
- **Git y Quality Coverage:**
  - Configurados con base golden tests.
  - Stats: `85` pruebas verificadas (78 runners, 7 engine). Snapshot `5/5` superado exitosamente.

## Decisiones cerradas (design-complete)

### Restatement / precedencia
- **Regla final:** “Más reciente manda” dentro del mismo tier de calidad documental.
- **Tier de calidad:** ANNUAL_REPORT auditado > INTERIM_REPORT auditado > REGULATORY_FILING > IR_NEWS/PRESENTATION.
- Si hay conflicto inter-tier para mismo periodo/campo: Se conserva el valor del tier superior. Se registra el conflicto en `reconciliation_log`.
- Si el filing de tier superior incluye ajuste sobre periodos anteriores, su valor prevalecerá sin necesidad de reglas condicionales complejas (el filing reciente dicta la corrección real).
- **Clave merge multi-periodo compuesta:** [(periodo, fecha_fin, tipo_periodo, moneda_original)](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/scripts/regression_check.py#357-413).

### Chunking
- Sección primero, tokens después.
- Chunk primario por sección detectada en preflight. Si la sección excede el límite, subdivisión interna con overlap.
- **Defaults:** `target_tokens_haiku=12000`, `target_tokens_flash=16000`, `max_chunk_tokens=18000`, `overlap_tokens=1000`, `max_chunks_per_filing=8`, `max_output_tokens_per_chunk=2500`.

### Conversión de moneda
- El extractor **determinístico extrae en moneda original**.
- La conversión a USD se centraliza en normalización/merge (fuera de la capa de extracción), con trazabilidad de `currency`, `unit_scale`, `fx_source`.

### Observabilidad y Git automatizado
- `keep_tp_filing_partials=true` obligatorio durante Fase 1A/1B/2 (canary y hardening).
- Git conservador:
  - Trabajar en rama actual: **`codex/v6.2-extraction-platform`**.
  - 1 commit por comando CLI que acabe correctamente (no por sub-step).
  - Stage selectivo: solo [case_dir](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/engine.py#2225-2234) + `CHANGELOG.md` (no `ESTADO_REPO.json`).
  - `commit_on_failure` a false.
  - Push condicional tras comandos exitosos si hubo commit previo (en [engine.py](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/engine.py) para [pipeline](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/engine.py#1463-1514), [continue](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/engine.py#1516-1720), [step](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/engine.py#1742-1804) y [rehacer](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/engine.py#1806-1885)).

---

## Fase 1A (infraestructura y control de riesgo) — HECHO
**Cambios implementados:**
- Archivos configurados: [engine_config.json](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine_config.json), [scripts/regression_check.py](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/scripts/regression_check.py), y golden states generados.
- Activar `keep_tp_filing_partials=true` y golden snapshots base para las 5 empresas.
- [regression_check.py](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/scripts/regression_check.py) tolerante: filing-derived exacto, market-derived con tolerancia 5%.
- Git utilidades programadas.

---

## Fase 1B (cambio de extracción con bajo riesgo) — Implementación parcial alta, pendiente cierre canary/aceptación
**Archivos objetivo (con implementación V6.1 en curso):**
- [_instrucciones/activas/instrucciones_tp_extractor_filing_V1.md](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/_instrucciones/activas/instrucciones_tp_extractor_filing_V1.md)
- [engine/prompt_builder.py](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/engine/prompt_builder.py)
- [scripts/runners/filing_preflight.py](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/scripts/runners/filing_preflight.py)
- [scripts/runners/tp_validator.py](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/scripts/runners/tp_validator.py)
- [scripts/runners/tp_extractor_merger.py](file:///Users/ismaelsanchezgarcia/Library/CloudStorage/OneDrive-Personal/ELSIAN_local/3_0-ELSIAN-INVEST/scripts/runners/tp_extractor_merger.py)

**Cambios introducidos / a consolidar:**
1. **Multi-periodo por filing:** Extracción de todos los periodos visibles en arrays, límite 10. **(Action: enforce `max_periods_per_filing=10` en código de merger/validator, no solo en prompt).**
2. **Pre-flight determinista detectando sección:** Validar idioma, estándar, moneda y unidades *por sección*.
3. **Calidad y completitud**: Reajustar `DATA_COMPLETENESS` por tipo documental.
4. **Reconciliación cruzada con umbral material (Regla V6.1):**
   - Detectar "concordancia" si `diff_pct < 1%`.
   - "Potential_restatement" si `diff_pct > 5%` y `diff_abs > max(5M, 0.5% * total_assets_periodo)`.
   - **Fallback de Umbral:** Si `total_assets` es null, usar `max(5M, 0.5% * 1_000_000_000)` como base conservadora del 1B.
   - `reconciliation_log` persistido correctamente.

---

## Fase R1 (Cierre funcional de lo ya implementado) — PENDIENTE
**Objetivo:** Completar y congelar la validación funcional en el mundo real antes de avanzar de ciego a arquitecturas complejas de multicapa (Fase 2).
1. Ejecutar **canary tests** en TEP, GCT, KAR, 0327, y EVER.
2. **Validación funcional de outputs:** No solo basarse en que pasen los tests unitarios, revisar manualmente métricas y comportamientos core (market_cap_usd, balances, defaults).
3. **Freeze de baseline post-R1:** Actualizar y fijar los _golden snapshots_ base contra estos resultados, cerrando la aceptación del baseline V6.2-R1.

---

## Fase 2 (multi-capa de extracción) — PENDIENTE
1. **Capa 1 determinista (Python-first):** Un script Python expuesto vía API que extrae hechos básicos (ingresos, etc.) sin usar LLM. Opera en *fail-open* (si no encuentra algo, continúa el ciclo LLM normal).
2. **Integración Capa 1:** Inyectar hints deterministas en triggers LLM de capa 2.
3. **Capa 2 chunked barato:** Modo de chunk escalado condicionado a un parametro `OFF` por defecto, activable posterior a benchmarks. Usa modelos flash/haiku limitados a la delimitación semántica del documento antes de token-limits.
4. **Capa 3 de reconciliación:** Extender merger para combinar y priorizar señales de determinista + chunked + pipeline base, delegando conflictos de gran disparidad al modelo Opus/Pro.
5. **Provenance:** Crear registro por caso en `_extraction_provenance.json` guardando moneda original, método, unidad, recencia y calidad de data hallada.

---

## Fase 3 (optimizaciones avanzadas) — PENDIENTE
1. **Gap-fill selectivo por campo:** Un retry final, puntual, buscando exclusivamente los campos faltantes en secciones prioritarias.
2. **Cobertura dinámica:** Ampliar o acotar extracciones en base al déficit pre-calculado del pipeline.
3. **Confianzas:** Medir y exportar `confidence_by_field` utilizable por el step de arbitraje y RedTeam.
4. **Taxonomías:** Sistema determinista de alias actualizables con versiones.

---

## Criterios de Aceptación, Testing y Rollback
- **Fase 1B:** Incremento observable en la completitud métrica de TEP (vía canary test), sin regresión en Golden Tests de GCT/KAR/0327/EVER.
- **Evaluación de Chunking en Fase 2 (A/B Test):** Comparar modelo pipeline anterior vs activado en 5 filings predeterminados. Evaluar impacto costo (`<=1.5x` vs baseline) frente factor cualitativo (mejora de completitud evidente) y cuellos de latencia red y cold-start (`<=2.5x` vs baseline).
- **Rollback incondicional:** Toda caída persistente en validaciones doradas de casos base obliga a desechar las adaptaciones de fase y retroceder a la versión base.
- **Supuesto clave:** `deuda_total_usd` excluirá arrendamientos financieros. OCR permanecerá inactivo.
