# Criterios de Meta-Review

## 1. Coherencia lógica
- ¿Las conclusiones del resumen ejecutivo se sostienen con la evidencia del assumption_ledger?
- ¿Hay saltos lógicos entre claims y decisión?
- ¿Los scores parciales (SMCQRV) reflejan correctamente lo que dicen los agentes?
- ¿La narrativa del ARBITRO es consistente con los datos numéricos?

## 2. Rigor de gates
- ¿Cada gate tiene justificación suficiente y específica?
- ¿Un CONDITIONAL se está usando como "PASS blando" sin evidencia concreta?
- ¿Hay gates que deberían ser FAIL pero se marcaron como PASS?
- ¿Los gates reflejan correctamente los hallazgos de FORENSIC y CATALYST?

## 3. Supuestos críticos
- ¿Cada supuesto CRITICO tiene al menos una evidencia con source_id verificable?
- ¿Los tests de falsación son realmente observables, medibles y con umbral definido?
- ¿Las probabilidades asignadas son coherentes con la cantidad y calidad de evidencia?
- ¿Hay dependencias circulares entre supuestos?
- ¿Se han considerado supuestos implícitos no documentados?

## 4. Escenarios
- ¿Las probabilidades de BASE + BULL + BEAR suman ~1.0?
- ¿El escenario BASE es realmente el más probable, o es un BULL disfrazado?
- ¿El BEAR contempla un escenario suficientemente adverso (no solo "menos crecimiento")?
- ¿Los retornos estimados son realistas para los horizontes temporales dados?
- ¿Los drivers de cada escenario son distintos y no redundantes?

## 5. Sizing y Kelly
- ¿Los inputs del Kelly (probabilidad de éxito p, ratio beneficio/pérdida b) son coherentes con los escenarios?
- ¿El ajuste por confianza es apropiado dado el nivel de incertidumbre?
- ¿El sizing final es prudente dado el nivel de conocimiento de la empresa?
- ¿Un sizing > 5% está justificado por evidencia extraordinariamente fuerte?

## 6. Puntos ciegos
- ¿Hay riesgos macro (tipos de interés, recesión, geopolítica) no considerados?
- ¿Se ha evaluado el riesgo de liquidez del activo?
- ¿Se han considerado riesgos regulatorios específicos del sector?
- ¿Hay competidores emergentes o disrupciones tecnológicas no mencionados?
- ¿Se ha considerado el riesgo de concentración de clientes/proveedores?

## 7. Kill criteria
- ¿Son específicos (no genéricos como "si el negocio empeora")?
- ¿Tienen umbrales numéricos donde es posible (ej: "margen operativo < 5%")?
- ¿La acción asociada (EXIT, REDUCE_50, etc.) es proporcional al riesgo?
- ¿Cubren los riesgos más graves contemplados en el BEAR scenario?
- ¿Son realmente monitorizables con datos públicos disponibles?

## 8. Coherencia probabilística ↔ categórica
- ¿La decisión categórica (INVERTIR/WATCHLIST/DESCARTAR) es coherente con las probabilidades?
- ¿Un INVERTIR con probabilidad_exito < 0.5 tiene justificación excepcional?
- ¿Un DESCARTAR con probabilidad_exito > 0.6 está bien fundamentado?
- ¿La tabla A12 del ARBITRO (si presente) es internamente consistente?

## 9. Desacuerdos entre agentes
- ¿El ARBITRO documentó los desacuerdos principales entre agentes?
- ¿La resolución de cada desacuerdo es razonada y no arbitraria?
- ¿Hay señales de "sesgo de consenso" (ignorar la voz discordante)?
