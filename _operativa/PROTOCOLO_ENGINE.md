# PROTOCOLO ENGINE — 3_0-ELSIAN-INVEST

> Reemplaza: ENTRY_POINT.md + PROTOCOLO_AUTONOMO.md de 2_0
> Principio rector: El orquestador gasta 0 tokens. Python puro para lo determinista. LLM solo para razonamiento.

## 1. ARRANQUE

El engine se invoca desde terminal:
```bash
python -m engine.engine <COMANDO> [OPCIONES]
```

### Comandos disponibles:
| Comando | Descripción |
|---------|-------------|
| `pipeline <TICKER> [--date YYYY-MM-DD] [--model MODEL]` | Pipeline completo para un ticker |
| `continue <TICKER> [--date YYYY-MM-DD]` | Continuar pipeline incompleto |
| `step <TICKER> <STEP_NAME> [--date YYYY-MM-DD]` | Ejecutar un step específico |
| `dashboard` | Mostrar estado global de todos los casos |
| `validate <TICKER> [--date YYYY-MM-DD]` | Validar artefactos de un caso |
| `scanner` | Ejecutar scanner diario |
| `monitor <TICKER>` | Ejecutar monitor para un caso |

## 2. FLUJO DE EJECUCIÓN (PIPELINE)

1. `config.py` → Cargar y validar engine_config.json
2. `state.py` → Inicializar _estado.json del caso
3. `router.py` → Recorrer DAG del pipeline:
   - Para cada step según dependencias:
     a. Si backend="python" → ejecutar runner directamente (subprocess)
     b. Si backend=LLM → prompt_builder → dispatcher → backend CLI
     c. Si multi=true → dispatch a N backends → fusión
     d. Si parallel_by="filing" → dispatch N filings en paralelo → merger
   - Validar output contra schema (validator.py)
   - Guardar artefacto en case_dir
   - Actualizar _estado.json (state.py)
   - Registrar en CHANGELOG (changelog.py)
4. `case_quality_audit.py` → Auditoría final
5. `git_utils.py` → Preparar commit

## 3. REGLAS DE EJECUCIÓN

R1) CERO TOKENS EN ORQUESTACIÓN: El engine.py, router.py, dispatcher.py y todos los
    módulos de control son Python puro. No consumen tokens LLM.
R2) LLM SOLO PARA RAZONAMIENTO: Solo los steps que requieren juicio cualitativo
    usan backends LLM (codex, gemini, claude).
R3) DETERMINISMO: Los runners Python (tp_calculator, tp_validator, tp_extractor_merger,
    market_data, sources_compiler) producen resultados idénticos dado el mismo input.
R4) FAIL-FAST: Si un step crítico falla, el pipeline se detiene. No hay retries
    automáticos salvo los configurados en execution.retry_on_failure.
R5) ESTADO ATÓMICO: Escrituras a _estado.json son atómicas (write-tmp + rename).
R6) VALIDACIÓN OBLIGATORIA: Todo artefacto se valida contra su schema antes de
    marcarse como DONE.

## 4. CONVENCIONES DE NAMING

- Caso ID: `CASE_YYYYMMDD_TICKER_MODEL`
- Directorio: `casos/{TICKER}/{YYYY-MM-DD}_{MODEL}/`
- Artefactos: `{Schema}_{Ticker}_{Date}_{Model}.json`
- Logs temporales: `tmp/{caso_id}_{step}.log`

## 5. MANEJO DE ERRORES

| Error | Acción |
|-------|--------|
| Backend no disponible | Intentar fallback binary → fail si ninguno |
| Timeout | Marcar step FAILED, log motivo |
| JSON parse error | Guardar raw output en tmp/, marcar FAILED |
| Schema validation fail | Guardar output con sufijo `_INVALID`, marcar FAILED |
| Step dependency not met | Skip step, log warning |

## 6. MULTI-MODELO (FUSION)

Cuando step_routing indica `multi: true`:
1. Despachar prompt a TODOS los backends listados (en paralelo)
2. Recoger outputs {backend_name: json_output}
3. Construir fusion prompt (instrucciones_fusion_V1.md)
4. Despachar fusion a backend de FUSION (normalmente codex)
5. Validar resultado fusionado contra schema
6. Guardar con _meta.fusion documentando conflictos

## 7. PARALLEL FILINGS (TP_EXTRACTOR)

Cuando step_routing indica `parallel_by: "filing"`:
1. Leer SourcesPack → listar filings disponibles
2. Por cada filing → build_filing_prompt (instrucciones_tp_extractor_filing_V1.md)
3. Despachar en paralelo (max_parallel_filings del config)
4. Recoger partial TruthPacks
5. Ejecutar tp_extractor_merger.py para fusionar
6. Continuar con TP_CALCULATOR
