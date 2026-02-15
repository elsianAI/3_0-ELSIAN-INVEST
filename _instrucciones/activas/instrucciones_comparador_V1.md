COMPARADOR BENCHMARK --> Evaluacion cualitativa inter-modelo de un mismo caso.

## 1. MISION
Comparar dos analisis del mismo ticker hechos por modelos diferentes. Evaluar dimensiones cualitativas que el script `benchmark_comparator.py` no puede medir automaticamente. Producir un veredicto estructurado por dimension y un veredicto global.

## 2. REGLA ABSOLUTA DE SALIDA
- Salida: bloque JSON para insertar en `_benchmark/comparaciones.json` (campo `evaluacion_agente`).
- El agente NO modifica los artefactos originales de ninguno de los dos directorios.

## 3. PROHIBICIONES
- No inventar diferencias donde no las hay. Si ambos modelos producen analisis equivalentes, declarar EMPATE.
- No favorecer sistematicamente al modelo que ejecuta la comparacion. Aplicar el mismo rigor a ambos.
- No evaluar velocidad de ejecucion (eso depende de infraestructura, no de calidad analitica).
- No re-hacer el analisis. Evaluar lo que existe, no lo que "deberia" existir.

## 4. INPUTS

| Input | Obligatorio | Descripcion |
|-------|-------------|-------------|
| Directorio caso A (`casos/{T}/{D}_{M}/`) | Si | Analisis original (modelo A) |
| Directorio caso B (`casos/{T}/{D}_{M2}/`) | Si | Benchmark (modelo B) |
| Output de `benchmark_comparator.py` | Si | Metricas objetivas ya calculadas |

Artefactos a leer de CADA directorio:
- `SourcesPack_v1_*.json` (deberia ser identico o muy similar — mismas fuentes)
- `TruthPack_v1_*.json`
- `ImpliedExpectations_v1_*.json`
- `AgentReport_v1_CATALYST_*.json`
- `AgentReport_v1_FORENSIC_*.json`
- `AgentReport_v1_BULL_*.json`
- `AgentReport_v1_RED_TEAM_*.json` (o `REDTEAM`)
- `DecisionPacket_v2_*.json` (o v1)

## 5. DIMENSIONES DE EVALUACION (orden estricto)

### D1. Profundidad de analisis
- Cual modelo profundizo mas en los drivers clave del caso?
- Evaluar: granularidad de cifras, segmentacion de revenue, analisis de margen por linea, descomposicion de FCF.
- No confundir volumen con profundidad. 10 claims superficiales < 5 claims con cifras y contexto.

### D2. Originalidad
- Cual encontro insights no obvios o no disponibles en los primeros parrafos de los filings?
- Evaluar: identificacion de riesgos ocultos, analisis de notas al pie, deteccion de cambios contables, lectura de credit agreements.
- Penalizar repeticion de lo que ya dice el TruthPack sin anadir interpretacion.

### D3. Rigor evidencial
- Cual tiene mejor trazabilidad claim -> source_id -> cita concreta?
- Evaluar: cada claim tiene evidencias con source_id valido? Las citas son verificables?
- Usar la metrica `claims_con_evidencia` del script como base, pero verificar cualitativamente la calidad de las citas (no solo su existencia).

### D4. Calibracion de confianza
- Las probabilidades en `predicciones_calibracion` son razonables o infladas/desinfladas?
- Evaluar: probabilidades que son round numbers (0.5, 0.7, 0.9) sugieren menos reflexion que valores como 0.65 o 0.73.
- Una probabilidad extrema (>0.9 o <0.1) necesita evidencia excepcional.

### D5. Calidad del Red Team
- Cual modelo planteo objeciones mas contundentes y dificiles de descartar?
- Evaluar: el Red Team ataco la tesis central o solo los riesgos obvios? Planteo escenarios concretos con cifras?
- Un Red Team que concluye "la empresa es buena pero tiene riesgos normales" es un Red Team debil.

### D6. Coherencia de la decision
- La decision final (INVERTIR/NO_INVERTIR/WATCHLIST) se sigue logicamente de los reports?
- Evaluar: si Forensic encontro banderas rojas graves, se reflejan en los gates y en el score?
- Coherencia entre `score_0_100`, `veredicto_final`, y el contenido de los AgentReports.

### D7. Peticiones de fuentes
- Cual identifico mejor las lagunas de informacion?
- Evaluar: los `faltantes` en SourcesPack son relevantes? Las preguntas en `peticion_para_truth_pack` son accionables?
- Si un modelo ignoro un filing tipo importante (credit agreement, proxy) sin explicar por que, penalizar.

## 6. FORMATO DE SALIDA

```json
{
  "profundidad": { "ganador": "A|B|EMPATE", "nota": "1-2 frases justificando" },
  "originalidad": { "ganador": "A|B|EMPATE", "nota": "..." },
  "rigor_evidencial": { "ganador": "A|B|EMPATE", "nota": "..." },
  "calibracion": { "ganador": "A|B|EMPATE", "nota": "..." },
  "red_team": { "ganador": "A|B|EMPATE", "nota": "..." },
  "decision": { "ganador": "A|B|EMPATE", "nota": "..." },
  "peticion_fuentes": { "ganador": "A|B|EMPATE", "nota": "..." },
  "veredicto_global": "A|B|EMPATE",
  "confianza_0_1": 0.7,
  "resumen": "Parrafo breve con el veredicto global y las diferencias mas importantes."
}
```

Reglas:
- `ganador` es "A" o "B" (referidos al directorio, no al nombre del modelo).
- `veredicto_global` se decide por mayoria simple de las 7 dimensiones. Si hay empate 3-3-1 o similar, usar juicio sobre las dimensiones mas criticas (rigor_evidencial y decision pesan mas).
- `confianza_0_1` refleja cuanta separacion hay entre los dos modelos. 0.5 = basicamente iguales. 0.9 = uno es claramente superior.

## 7. PROCESO

1. Leer output de `benchmark_comparator.py` (metricas objetivas).
2. Leer los artefactos de ambos directorios (TruthPack, ImpliedExpectations, AgentReports, DecisionPacket).
3. Para cada dimension D1-D7, comparar y asignar ganador + nota.
4. Calcular veredicto global.
5. Presentar resultado al usuario para revision.
6. El orquestador registra el JSON en `_benchmark/comparaciones.json`.

## 8. ESQUEMAS
- `BenchmarkComparisons_v1.json` (registro acumulativo — donde se inserta el output)
- `AgentReport_v1.json`, `DecisionPacket_v2.json`, `TruthPack_v1.json`, etc. (inputs)
