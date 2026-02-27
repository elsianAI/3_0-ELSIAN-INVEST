# Plan Fase 2: Módulo de Extracción Determinista End-to-End

> **Estado:** V6 — governance/SOP de trazabilidad integrado.
> **Rama:** `codex/python-only-deterministic-phase2`
> **Última revisión:** 27 Feb 2026 (V6)

---

## 1. Qué estamos haciendo y por qué

### El problema

El pipeline actual de ELSIAN-INVEST extrae datos financieros de filings usando LLMs como motor principal. Esto tiene tres consecuencias:

1. **Coste alto.** Cada ejecución consume miles de tokens en modelos caros (gpt-5.3-codex para extracción, claude-opus-4.6 para arbitraje). El benchmark A/B mostró que el coste por caso ronda los 0.8-1.0x del baseline, y el baseline ya es caro.

2. **Opacidad.** Cuando un dato es incorrecto (FY2022 de TEP: 1.2B en vez de 8.154B), es difícil saber si falló la descarga del filing, el parseo, la extracción LLM, la normalización o el merge. Todo está mezclado en un pipeline monolítico.

3. **No se puede mejorar sin gastar.** Para saber si un cambio en el código mejora los resultados, hay que lanzar el pipeline completo (tokens). Los P0 fixes de Phase 2 demostraron que las mejoras más valiosas eran Python puro (normalizer, merger, calculator), pero las descubrimos después de gastar tokens en benchmarks fallidos.

### La solución

Construir un módulo Python completamente aislado que haga el mismo trabajo sin LLMs: dado un ticker, obtiene los filings, los parsea y extrae datos financieros. Se desarrolla y valida offline (0 tokens). Cuando esté maduro, se integra al pipeline — el LLM pasa de ser "el extractor" a ser "el que rellena lo que Python no pudo".

### Por qué aislado del pipeline actual

- **Sin riesgo de romper producción.** El pipeline sigue funcionando tal cual mientras se desarrolla el módulo.
- **Sin tentación de atajos.** Si el módulo importa de `engine/` o `scripts/`, se crean dependencias invisibles que dificultan la separación. Aislado = portable.
- **Medible desde el día 1.** Cada caso tiene un `expected.json` que define qué datos deberían extraerse. El score te dice exactamente cuánto falta.
- **Iteración sin coste.** Cambias una regex, ejecutas `eval --all`, ves si mejora. Cero tokens.

### Relación con `casos/` del pipeline — NO hay duplicación

`casos/` (pipeline actual) y `deterministic/cases/` son mundos separados con propósitos distintos:

| | `casos/` (pipeline) | `deterministic/cases/` (módulo) |
|---|---|---|
| **Contenido** | TruthPacks, provenance, artefactos LLM, _estado.json | Filings crudos descargados, expected.json curado a mano |
| **Quién lo genera** | Pipeline completo (LLM + arbitraje) | Módulo Python solo |
| **Para qué sirve** | Evaluar el pipeline LLM end-to-end | Desarrollar y medir el extractor determinista |
| **Moneda** | USD (convertida) | Original del filing (EUR, USD, etc.) |

No comparten datos ni estructura. En integración futura, `deterministic/cases/` desaparece: el pipeline alimenta el módulo directamente y los resultados van a `casos/`.

### Por qué reutilizamos código existente

El pipeline actual ya tiene piezas que funcionan bien para obtener filings:

- `sec_fetcher_v2_runner.py` (2660 líneas) descarga de SEC EDGAR: busca CIK, selecciona filings por tipo, descarga HTML/PDF, extrae texto.
- `clean_md_extractor.py` (330 líneas) convierte tablas HTML de filings SEC a markdown estructurado.

Reimplementar esto desde cero sería duplicar esfuerzo sin valor. La estrategia es **copiar** estos ficheros al módulo y refactorizarlos: eliminar imports de `engine/`/`scripts/`, simplificar la interfaz, y adaptarlos a la estructura del módulo. El resultado es código que funciona desde el día 1 pero sin dependencia alguna del pipeline.

---

## 2. Estructura del módulo

```
deterministic/
│
├── src/
│   ├── __init__.py
│   ├── pipeline.py                  ← DeterministicPipeline (clase fachada)
│   │
│   ├── acquire/                     ← OBTENCIÓN DE FILINGS
│   │   ├── __init__.py
│   │   ├── sec_edgar.py             ← copiado y refactorizado de sec_fetcher_v2_runner.py
│   │   ├── eu_regulators.py         ← stub inicial para AMF/CNMV/FCA (se desarrolla después)
│   │   ├── pdf_to_text.py           ← extraído de sec_fetcher_v2_runner.py (funciones pypdf)
│   │   └── html_to_markdown.py      ← copiado y refactorizado de clean_md_extractor.py
│   │
│   ├── extract/                     ← EXTRACCIÓN DE DATOS FINANCIEROS
│   │   ├── __init__.py
│   │   ├── narrative.py             ← patrones para prosa ("revenue amounted to €10,280M")
│   │   ├── tables.py                ← extracción de tablas markdown
│   │   └── detect.py                ← detección de moneda, escala, periodos, secciones
│   │
│   ├── normalize/                   ← NORMALIZACIÓN Y AUDITORÍA
│   │   ├── __init__.py
│   │   ├── aliases.py               ← mapeo de nombres de campo desde config/field_aliases.json
│   │   ├── scale.py                 ← inferencia y corrección de escala (cascada DT-1)
│   │   └── audit.py                 ← logging de campos reconocidos/descartados/inciertos
│   │
│   ├── merge.py                     ← combinar extracciones de múltiples filings
│   ├── evaluate.py                  ← comparar resultado vs expected.json
│   └── schemas.py                   ← dataclasses (FieldResult, PeriodResult, etc.)
│
├── config/
│   └── field_aliases.json           ← aliases versionados, editables sin tocar código
│
├── cases/                           ← UN DIRECTORIO POR CASO
│   ├── TEP/
│   │   ├── case.json                ← input: ticker, exchange, moneda, source_hint
│   │   ├── filings/                 ← poblado por acquire (empieza vacío)
│   │   ├── filings_manifest.json    ← generado por acquire: qué se descargó, qué falta
│   │   └── expected.json            ← curado a mano: el "100%" de extracción
│   ├── GCT/
│   ├── TZOO/
│   └── ...
│
├── tests/
│   ├── unit/                        ← tests de patrones, aliases, parseo
│   │   ├── test_narrative.py
│   │   ├── test_tables.py
│   │   ├── test_normalize.py
│   │   ├── test_scale.py
│   │   └── test_detect.py
│   ├── integration/
│   │   └── test_pipeline.py         ← ejecuta eval sobre todos los cases/
│   └── fixtures/                    ← fragmentos cortos para unit tests
│       ├── narrative_eu_sample.txt
│       └── table_10k_sample.md
│
├── schemas/
│   └── extraction_result_v1.json    ← JSON Schema versionado del contrato de salida
│
├── cli.py                           ← punto de entrada
└── requirements.txt                 ← requests, beautifulsoup4, pypdf
```

### Qué se copia del pipeline actual y cómo se refactoriza

| Fichero original | Destino en módulo | Qué se cambia |
|-----------------|-------------------|---------------|
| `scripts/runners/sec_fetcher_v2_runner.py` | `src/acquire/sec_edgar.py` | Eliminar imports de `engine/`, `scripts/`. Eliminar lógica de `_estado.json`, commits git, state management. Mantener: SecClient, lógica de selección de filings, descarga, retry. Simplificar interfaz a una función `fetch(ticker, output_dir) -> manifest`. |
| `scripts/runners/sec_fetcher_v2_runner.py` (funciones PDF) | `src/acquire/pdf_to_text.py` | Extraer funciones de pypdf a módulo separado. |
| `scripts/runners/clean_md_extractor.py` | `src/acquire/html_to_markdown.py` | Eliminar import de `clean_md_quality`. Mantener: detección de secciones, parseo de tablas HTML, conversión a markdown. Simplificar a función `convert(html_path) -> markdown_str`. |

**Subfases del copy/refactor** (para no asumir las 2660 líneas de golpe):

1. **Subfase A (primer caso TZOO):** Copiar solo lo mínimo de `sec_fetcher_v2_runner.py`: `SecClient` (rate limiter + retry), resolución ticker→CIK, descarga de 10-K/10-Q HTML. Sin PDF, sin 8-K earnings, sin EU. Copiar `clean_md_extractor.py` completo (330 líneas, manejable).
2. **Subfase B (caso GCT):** Añadir soporte 8-K earnings (Exhibit 99), soporte PDF vía `pdf_to_text.py`.
3. **Subfase C (caso TEP — EU):** Implementar bootstrap manual (`filings/` se puebla a mano). El stub `eu_regulators.py` detecta contenido existente y genera manifest sin descargar.

Lo que NO se copia: nada de `engine/dispatcher.py`, `engine/router.py`, `engine/prompt_builder.py`, `tp_normalizer.py`, `tp_extractor_merger.py`. La extracción y normalización se escriben desde cero dentro del módulo, aprovechando las lecciones aprendidas (DT-1 escala EUR, aliases con cascada, auditoría).

---

## 3. Las tres fases del módulo

### Fase A: Obtener (acquire)

**Input:** `case.json` con ticker, exchange, source_hint
**Output:** `filings/` poblado + `filings_manifest.json`

Para US (SEC EDGAR):
1. Ticker → CIK vía `https://www.sec.gov/files/company_tickers.json`
2. CIK → listado de filings vía `https://data.sec.gov/submissions/CIK{cik}.json`
3. Seleccionar: ≤6 annual (10-K/20-F), ≤12 quarterly (10-Q/6-K), ≤10 earnings (8-K con Exhibit 99)
4. Descargar HTML/PDF, convertir a markdown/texto
5. Guardar en `cases/{TICKER}/filings/`

Para EU: stub inicial. Los filings se pueden poner manualmente en `filings/` como bootstrap. El módulo detecta contenido existente y salta la descarga. Los fetchers de reguladores EU (AMF, CNMV, FCA) se añaden incrementalmente cuando haya caso que los necesite.

`filings_manifest.json`:
```json
{
  "ticker": "TZOO",
  "source": "sec_edgar",
  "cik": "0001133311",
  "filings_expected": {
    "annual": {"target": 6, "reason": "≤6 annual (10-K/20-F) per SEC selection policy"},
    "quarterly": {"target": 12, "reason": "≤12 quarterly (10-Q/6-K)"},
    "earnings": {"target": 10, "reason": "≤10 earnings (8-K with Exhibit 99)"}
  },
  "filings_downloaded": 25,
  "filings_failed": 0,
  "filings_coverage_pct": 100.0,
  "coverage": {
    "annual": {"available_in_index": 5, "target": 6, "expected": 5, "downloaded": 5, "years": [2020, 2021, 2022, 2023, 2024]},
    "quarterly": {"available_in_index": 12, "target": 12, "expected": 12, "downloaded": 12},
    "earnings": {"available_in_index": 8, "target": 10, "expected": 8, "downloaded": 8}
  },
  "gaps": [],
  "notes": "expected = min(available_in_index, target). TZOO only has 5 annual and 8 earnings in EDGAR. All available filings downloaded successfully.",
  "download_date": "2026-02-27"
}
```

### Fase B: Extraer (extract + normalize + merge)

**Input:** filings en `filings/`
**Output:** `ExtractionResult` con periodos, campos, trazabilidad

1. **Detectar** (`detect.py`): por cada filing → idioma, moneda, escala, secciones, periodos visibles
2. **Extraer** según formato:
   - Tablas markdown → `tables.py` (parseo de filas/columnas, mapping a campos por label)
   - Prosa narrativa → `narrative.py` (patrones: `{label} {verbo} {moneda}{valor} {escala}`, comparativos `versus X in Y`)
3. **Normalizar** (`normalize/`): mapear aliases, inferir escala por cascada, auditar descartes
4. **Combinar** (`merge.py`): cruzar datos de múltiples filings, resolver conflictos (annual > quarterly > earnings), tomar el valor más reciente por tipo

### Fase C: Evaluar (evaluate)

**Input:** `ExtractionResult` + `expected.json`
**Output:** `EvalReport` con score

Compara campo a campo, periodo a periodo. Tolerancia ±1% para numéricos. Reporta: matched, missed, wrong, extra, score total.

---

## 4. Los casos

Cada caso es una carpeta que contiene todo lo necesario para ejecutar y evaluar una empresa:

### `case.json` — Configuración de entrada
```json
{
  "ticker": "TEP",
  "exchange": "EURONEXT",
  "country": "FR",
  "currency": "EUR",
  "cik": null,
  "source_hint": "eu_manual",
  "filings_expected_count": 4,
  "notes": "European narrative, AMF regulatory filings, mixed EN/FR. 4 filings: FY2024, FY2023, H1-2024, H1-2023"
}
```
`source_hint` indica al módulo qué fetcher usar: `"sec"` para EDGAR, `"eu_manual"` para bootstrap manual, `"amf"` cuando exista el fetcher AMF.

### `filings/` — Poblado por el módulo
Empieza vacío. `acquire` lo llena. Si se puebla manualmente para EU, `acquire` lo respeta.

### `filings_manifest.json` — Generado por acquire
Inventario de lo que se descargó: cuántos filings, qué tipos, qué años, qué gaps.

### `expected.json` — Curado manualmente
```json
{
  "version": "1.0",
  "ticker": "TEP",
  "currency": "EUR",
  "scale": "millions",
  "periods": {
    "FY2024": {
      "fecha_fin": "2024-12-31",
      "tipo_periodo": "anual",
      "fields": {
        "ingresos": {"value": 10280, "source_filing": "regulatory_fy2024.md"},
        "ebit": {"value": 1082},
        "net_income": {"value": 523},
        "cfo": {"value": 1813},
        "capex": {"value": -214}
      }
    },
    "FY2023": {
      "fecha_fin": "2023-12-31",
      "tipo_periodo": "anual",
      "fields": {
        "ingresos": {"value": 8345},
        "ebit": {"value": 998}
      }
    }
  }
}
```
Solo incluye campos que REALMENTE están en los filings disponibles. El 100% es "todo lo extraíble", no "todos los campos llenos".

---

## 5. El CLI

```bash
# Descargar filings para un caso
python3 -m deterministic.cli acquire TEP

# Extraer datos de filings ya descargados
python3 -m deterministic.cli extract TEP

# Evaluar resultado contra expected.json
python3 -m deterministic.cli eval TEP

# Todo junto: acquire + extract + evaluate
python3 -m deterministic.cli run TEP

# Todos los casos
python3 -m deterministic.cli run --all

# Dashboard resumen
python3 -m deterministic.cli dashboard
```

Dashboard:
```
DETERMINISTIC PIPELINE DASHBOARD
=================================
Case  | Source | Filings | Periods | Expected | Matched | Score
------|--------|---------|---------|----------|---------|------
TZOO  | sec    |   28    |    6    |    38    |   35    | 92.1%
GCT   | sec    |   32    |    8    |    58    |   51    | 87.9%
TEP   | manual |    4    |    5    |    32    |   28    | 87.5%
KAR   | sec    |   25    |    7    |    45    |   38    | 84.4%
------|--------|---------|---------|----------|---------|------
TOTAL |        |   89    |   26    |   173    |  152    | 87.9%
```

---

## 6. Ciclo de desarrollo

```
1. CREAR CASO
   → Crear cases/{TICKER}/case.json
   → Ejecutar: python3 -m deterministic.cli acquire {TICKER}
   → Filings descargados a cases/{TICKER}/filings/

2. CURAR EXPECTED
   → Leer los filings descargados
   → Crear expected.json con datos reales verificados

3. PRIMERA EXTRACCIÓN
   → python3 -m deterministic.cli eval {TICKER}
   → Ver score, qué campos se extraen, cuáles fallan

4. ITERAR
   → Mejorar patrón narrativo / regla de tabla / alias
   → Re-ejecutar eval → ver si mejora
   → Repetir hasta ≥85%

5. REGRESIÓN
   → python3 -m deterministic.cli eval --all
   → Verificar que casos anteriores no se rompen

6. SIGUIENTE CASO → volver a 1
```

**Orden sugerido:**
1. **TZOO** — small cap US, 10-K con tablas limpias, el caso más simple para arrancar
2. **GCT** — mid cap US, más filings, iXBRL, consolida extracción de tablas
3. **TEP** — EU narrativa, desarrolla extractor de prosa, bootstrap manual de filings
4. **KAR, 0327, EVER** — ampliar robustez, cubrir edge cases

---

## 7. La clase DeterministicPipeline

```python
class DeterministicPipeline:

    def __init__(self, config_dir: str = "config"):
        """Carga field_aliases.json y configuración."""

    def acquire(self, case_dir: str) -> AcquisitionResult:
        """
        Lee case.json → descarga filings a filings/ → genera filings_manifest.json.
        Si filings/ ya tiene contenido, no redescarga (cache).
        Usa sec_edgar.py para US, eu_regulators.py para EU (stub).
        """

    def extract(self, case_dir: str) -> ExtractionResult:
        """
        Lee filings de filings/.
        Por cada filing: detect → extract (narrative/tables) → normalize.
        Luego merge de todos los filings.
        Devuelve ExtractionResult con periodos, campos, trazabilidad, auditoría.
        """

    def evaluate(self, case_dir: str) -> EvalReport:
        """
        Ejecuta extract() y compara contra expected.json.
        Tolerancia ±1%. Score = matched / total_expected.
        """

    def run(self, case_dir: str) -> tuple[AcquisitionResult, ExtractionResult, EvalReport]:
        """acquire + extract + evaluate."""

    def dashboard(self, cases_dir: str = "cases") -> DashboardReport:
        """run sobre todos los casos, resumen tabular."""
```

---

## 8. Baseline actual (referencia para medir mejora)

Medido el 27 Feb 2026 sobre 5 canary cases del pipeline actual (TEP, GCT, KAR, 0327, EVER):

| Métrica | Valor | Fórmula |
|---------|-------|---------|
| **Contribución determinista** | **17.78%** (72/405) | `(match + deterministic_fill) / total_fields` |
| Deterministic selected source | 4.69% (19/405) | `deterministic_selected_source / total_fields` |
| Conflicto material | 50.62% (205/405) | `material_conflict / total_fields` |

Desglose por caso:

| Caso | Fields | Det contrib. | Conflicto |
|------|--------|-------------|-----------|
| TEP | 76 | 11.8% | 47.4% |
| GCT | 129 | 20.9% | 53.5% |
| KAR | 53 | 3.8% | 39.6% |
| 0327 | 63 | 4.8% | 76.2% |
| EVER | 84 | 36.9% | 36.9% |

El objetivo del módulo es que, cuando se integre, la contribución determinista suba de 17.78% a >60%, reduciendo proporcionalmente la dependencia del LLM.

---

## 9. Decisiones técnicas (heredadas del V3, aplican al módulo)

- **DT-1 (Escala EUR):** `normalize/scale.py` implementa cascada de inferencia: raw_notes → header de filing → preflight → incertidumbre. Aliases con `multiplier: null` no asumen escala.
- **DT-3 (KPIs):** `evaluate.py` reporta 3 métricas (ver sección 14):
  - **Primaria:** `score = matched / total_expected` (gate de cierre ≥85%)
  - **Secundaria obligatoria:** `filings_coverage_pct` y `required_fields_coverage_pct`
- **Sin pandas.** Solo stdlib + requests + bs4 + pypdf.
- **Aliases en JSON.** `config/field_aliases.json` editable.
- **Moneda original.** No se convierte EUR→USD. El módulo extrae en moneda del filing.

---

## 10. Contrato de salida (ExtractionResult)

El módulo produce un JSON con schema estable. No es un TruthPack, pero está diseñado para que un adapter futuro pueda transformarlo fácilmente:

```json
{
  "schema_version": "1.0",
  "ticker": "TZOO",
  "currency": "USD",
  "extraction_date": "2026-02-27",
  "filings_used": 25,
  "periods": {
    "FY2024": {
      "fecha_fin": "2024-12-31",
      "tipo_periodo": "anual",
      "fields": {
        "ingresos": {
          "value": 185.2,
          "scale": "millions",
          "source_filing": "10-K_2024.md",
          "source_location": "table:income_statement:row3",
          "confidence": "high"
        }
      }
    }
  },
  "audit": {
    "fields_extracted": 35,
    "fields_discarded": 3,
    "discarded_reasons": ["scale_uncertain", "duplicate_conflict", "label_ambiguous"]
  }
}
```

Campos clave del schema: `value` (número), `scale` (raw/thousands/millions/billions), `source_filing` (de qué filing viene), `source_location` (tabla/narrativa/sección), `confidence` (high/medium/low).

**Versionado:** El schema formal vive en `schemas/extraction_result_v1.json` (JSON Schema draft-07). Política de compatibilidad:
- **v1.x (minor):** Se pueden añadir campos opcionales. No se eliminan ni renombran campos existentes. Compatible hacia atrás.
- **v2 (major):** Cambios breaking requieren nuevo fichero `extraction_result_v2.json` y adapter de migración.
- `ExtractionResult` incluye `"schema_version": "1.0"` en el JSON de salida para que el consumidor sepa qué versión parsear.

Este schema es el contrato para la integración futura: el pipeline importará este JSON y lo transformará a hints o a campos directos.

---

## 11. Qué NO es (ahora)

- **No es parte del pipeline.** Cero imports de `engine/` o `scripts/`. El código copiado se refactoriza para ser independiente.
- **No llama LLMs.** Cero tokens, cero APIs de IA.
- **No produce TruthPack.** Produce `ExtractionResult` (sección 10). Un adapter futuro puede convertirlo.
- **No convierte moneda.** Trabaja en moneda original.

---

## 12. Integración futura (no es ahora)

Cuando el módulo tenga score ≥85% en ≥5 casos:
- `acquire/` puede complementar o reemplazar a `sec_fetcher_v2_runner.py`
- `extract/` + `normalize/` alimentan hints enriquecidos al prompt LLM
- `evaluate.py` se usa como gate de calidad post-extracción
- El pipeline actual importa DESDE este módulo, nunca al revés

---

## 13. Dependencias

```
# requirements.txt
requests>=2.28
beautifulsoup4>=4.12
pypdf>=4.0
```

---

## 14. Criterios de éxito

### Gate de cierre (obligatorio)

| Métrica | 1 caso | 3 casos | 5 casos |
|---------|--------|---------|---------|
| **Score de extracción** (matched/expected) | ≥80% | ≥80% cada uno | **≥85% media, ninguno <75%** |
| **Filings coverage** (descargados/esperados†) | ≥90% | ≥90% | ≥90% |
| **Required fields coverage** (campos con valor/campos en expected) | ≥80% | ≥80% | ≥85% |
| Escala incorrecta | 0 | 0 | 0 |
| Campos descartados sin log | 0 | 0 | 0 |
| Regresión al añadir caso | — | 0 rotos | 0 rotos |
| Imports del pipeline actual | 0 | 0 | 0 |

† **Cómo se calcula `filings_coverage_pct`:** `expected` se determina por fuente:
- **SEC EDGAR (US):** El EDGAR submissions index dice cuántos filings existen por tipo. `expected = min(available, target)` donde target es 6 annual, 12 quarterly, 10 earnings.
- **EU manual:** `expected` se define en `case.json` campo `filings_expected_count` (el usuario sabe cuántos filings regulatorios existen para esa empresa).
- **Excepciones:** Filings que existen en el índice pero no son descargables (404, paywall) se restan de `expected` y se documentan en `gaps[]` del manifest con `reason`.

### Objetivo stretch (no bloquea)

| Métrica | Objetivo |
|---------|----------|
| Score de extracción | 100% en cada caso |
| Contribución determinista post-integración | >60% (vs 17.78% actual) |

---

## 15. Governance: SOP de trazabilidad obligatoria

Todo commit que toque `deterministic/` requiere trazabilidad. Enforcement bloqueante vía pre-commit hook.

### Artefactos obligatorios por commit

1. **`deterministic/PHASE2_OPERATIONS_LOG.md`** — 1 entrada nueva con 10 campos: Agent, Objective, Hypothesis, Files changed, Commands executed, Metrics before, Metrics after, Tests, Decision, Next step.
2. **`CHANGELOG.md`** — 1 línea `[DETERMINISTIC]` bajo la fecha actual.

### Enforcement

- Hook versionado en `.githooks/pre-commit`. Detecta cambios staged en `deterministic/`, verifica que log + changelog estén staged, valida los 10 campos.
- Setup: `bash scripts/setup_git_hooks.sh` (configura `core.hooksPath .githooks`).
- Sin excepciones por tamaño de cambio.

### Alcance

Aplica si se tocan ficheros bajo: `deterministic/src/`, `deterministic/tests/`, `deterministic/config/`, `deterministic/schemas/`, `deterministic/cases/`, `deterministic/cli.py`, `deterministic/requirements.txt`. No aplica a cambios fuera de `deterministic/`.

### Contrato Operativo de Agentes (6 reglas)

Todo agente (Opus, Codex, User) que trabaje en `deterministic/` debe cumplir estas 6 reglas:

1. **Antes de tocar código:** leer la última entrada de `PHASE2_OPERATIONS_LOG.md` y anotar métricas actuales.
2. **Cada cambio relevante = una iteración nueva** en `PHASE2_OPERATIONS_LOG.md` con los 10 campos obligatorios.
3. **Siempre reportar métricas antes/después** (score, matched, wrong, missed, extra). Si no aplica, escribir `N/A` con razón.
4. **Ejecutar tests** (`python3 -m unittest discover -s deterministic/tests -v`) y registrar resultado (pass/fail count).
5. **Añadir línea resumen** en `CHANGELOG.md` bajo la fecha actual con tag `[DETERMINISTIC]`.
6. **El trabajo no está hecho hasta que el commit sea válido.** Un cambio sin commit + trazabilidad no existe.

### Cuándo commitear

- Después de cada `eval` que produzca nuevas métricas (mejora o regresión).
- Después de añadir un caso nuevo (case.json + acquire).
- Después de añadir o modificar tests.
- Después de cualquier refactor que toque más de 2 ficheros.
- **Un commit = una iteración.** No acumular múltiples cambios en un solo commit.

---

## 16. Para arrancar (Subfase A — caso TZOO)

> Alineado con Subfase A (sección 2). Solo se copia lo mínimo para que TZOO funcione.

1. Crear rama `codex/python-only-deterministic-phase2`
2. Crear estructura `deterministic/` (dirs, `__init__.py`, `cli.py`, `requirements.txt`, `schemas/extraction_result_v1.json`)
3. Copiar de `sec_fetcher_v2_runner.py` **solo**: `SecClient` (rate limiter + retry), resolución ticker→CIK, descarga HTML de 10-K/10-Q. Resultado: `src/acquire/sec_edgar.py` (~300 líneas, no 2660). Sin PDF, sin 8-K earnings.
4. Copiar `clean_md_extractor.py` → `src/acquire/html_to_markdown.py` (330 líneas, refactorizar: quitar import `clean_md_quality`)
5. Implementar `src/extract/tables.py` mínimo (parseo de tablas markdown de 10-K)
6. Implementar `src/normalize/aliases.py` con `config/field_aliases.json`
7. Crear `cases/TZOO/case.json`
8. Ejecutar `acquire TZOO`, verificar filings descargados, curar `expected.json`
9. Ejecutar `eval TZOO`, iterar hasta score ≥80%

### Subfases siguientes (no arrancar hasta cerrar TZOO)

- **Subfase B (GCT):** Añadir 8-K earnings + `pdf_to_text.py` a `sec_edgar.py`. Crear caso GCT, iterar.
- **Subfase C (TEP — EU):** Implementar bootstrap manual en `eu_regulators.py`. Desarrollar `narrative.py`. Crear caso TEP, iterar.
