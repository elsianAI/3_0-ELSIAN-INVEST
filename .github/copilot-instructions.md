# Copilot Agent Instructions — ELSIAN-INVEST

> Estas instrucciones son **obligatorias** para cualquier agente (Copilot, Codex, Claude, humano) que trabaje en este repositorio.
> Leélas ENTERAS antes de ejecutar cualquier tarea.

---

## 1. Contexto del proyecto

ELSIAN-INVEST es un pipeline de extracción de datos financieros de compañías cotizadas. Tiene dos capas:

- **Pipeline LLM** (`engine/`, `scripts/`): extracción con modelos de lenguaje. NO la toques a menos que se te pida explícitamente.
- **Módulo determinista** (`deterministic/`): extracción **sin LLM**, puro Python + regex. Es la fase activa de desarrollo (Phase 2).

**Tu trabajo por defecto es sobre `deterministic/`.** Si la tarea implica otros directorios, confirma primero con el usuario.

---

## 2. Arquitectura del módulo determinista

```
deterministic/
  cli.py                 # Entry point: python3 -m deterministic.cli {command} {ticker}
  __init__.py
  __main__.py
  requirements.txt       # requests, beautifulsoup4, pypdf (NO añadas más sin aprobación)
  PHASE2_OPERATIONS_LOG.md   # Log de trazabilidad (10 campos por entrada)
  README.md
  src/
    schemas.py           # Dataclasses: FieldResult, PeriodResult, ExtractionResult, EvalReport, etc.
    pipeline.py          # DeterministicPipeline — facade: acquire → extract → evaluate → dashboard
    merge.py             # Multi-filing merge con prioridad (annual > quarterly > earnings)
    evaluate.py          # Comparación field-by-field contra expected.json (tolerancia ±1%)
    acquire/
      sec_edgar.py       # SecClient: SEC EDGAR API, rate limit 0.12s, targets: 6 annual, 12 quarterly, 10 earnings
      html_to_markdown.py # HTML → Markdown con secciones financieras
      eu_regulators.py   # Stub EU (manual bootstrap)
      pdf_to_text.py     # PDF → texto plano
    extract/
      detect.py          # FilingMetadata: currency, scale, language, periods, sections, filing_type
      tables.py          # Parseo de tablas markdown → TableField[]
      narrative.py       # Extracción de patrones narrativos → NarrativeField[]
    normalize/
      aliases.py         # AliasResolver: fuzzy matching contra config/field_aliases.json
      scale.py           # DT-1 Scale Cascade: raw_notes → header → preflight → field_multiplier → uncertainty
      audit.py           # AuditLog: accept/discard con razón
  config/
    field_aliases.json   # 22 campos canónicos, ~150 aliases (EN/FR/ES). Versión 1.0
  schemas/
    extraction_result_v1.json  # JSON Schema draft-07 para ExtractionResult
  cases/
    {TICKER}/
      case.json          # Config del caso: ticker, source_hint, currency, etc.
      expected.json      # Ground truth curado manualmente
      extraction_result.json  # Output del pipeline (generado, no editar a mano)
      filings_manifest.json   # Output de acquire (generado)
      filings/           # Archivos descargados: .htm, .txt, .clean.md
  tests/
    unit/                # test_detect, test_tables, test_narrative, test_normalize, test_scale
    integration/         # test_pipeline
    fixtures/            # Samples para tests
```

### Reglas de aislamiento (INVIOLABLES)

- **0 imports de `engine/` o `scripts/`**. Nunca. Si necesitas algo de allí, cópialo a `deterministic/src/`.
- **0 llamadas a LLM**. Todo es regex, parsing, heurísticas.
- **Dependencias**: solo `requests`, `beautifulsoup4`, `pypdf`. Para añadir otra, pide aprobación al usuario.

---

## 3. Comandos que debes conocer

```bash
# Instalar dependencias
pip3 install -r deterministic/requirements.txt --break-system-packages

# Ejecutar tests (OBLIGATORIO antes y después de cada cambio)
python3 -m unittest discover -s deterministic/tests -v

# Pipeline completo para un caso
python3 -m deterministic.cli run TZOO

# Solo adquisición
python3 -m deterministic.cli acquire TZOO

# Solo extracción
python3 -m deterministic.cli extract TZOO

# Solo evaluación
python3 -m deterministic.cli eval TZOO

# Evaluar TODOS los casos
python3 -m deterministic.cli eval --all

# Dashboard resumen
python3 -m deterministic.cli dashboard
```

**Usa siempre `python3`, nunca `python`.**

---

## 4. Contrato operativo (6 REGLAS OBLIGATORIAS)

Estas reglas no son sugerencias. Son requisitos bloqueantes.

### Regla 1 — Leer antes de tocar
Antes de modificar cualquier fichero en `deterministic/`, lee la **última entrada** de `deterministic/PHASE2_OPERATIONS_LOG.md`. Anota las métricas actuales (score, matched, wrong, missed, extra). Las necesitarás para "Metrics before".

### Regla 2 — Cada cambio = una iteración
Cada cambio relevante produce **una entrada nueva** en `PHASE2_OPERATIONS_LOG.md` con los 10 campos obligatorios (ver sección 5).

### Regla 3 — Reportar métricas antes/después
Siempre ejecuta `python3 -m deterministic.cli eval {TICKER}` antes y después de tu cambio. Reporta ambos resultados. Si el cambio no afecta métricas (por ejemplo, solo tests), escribe `N/A` con motivo.

### Regla 4 — Ejecutar tests
Ejecuta `python3 -m unittest discover -s deterministic/tests -v` y registra el resultado (nº pass / nº fail).

### Regla 5 — Actualizar CHANGELOG
Añade una línea en `CHANGELOG.md` bajo la fecha de hoy con tag `[DETERMINISTIC]`:
```
- [DETERMINISTIC] Breve descripción de lo que cambiaste
```

### Regla 6 — El trabajo no existe hasta que se commitea
Un cambio sin commit + trazabilidad **no existe**. Sigue las reglas de commit de la sección 6.

---

## 5. Formato del log de trazabilidad

Cada entrada en `deterministic/PHASE2_OPERATIONS_LOG.md` sigue este formato exacto:

```markdown
## YYYY-MM-DD HH:MM - Iteration N - {CASE}
- Agent: {tu nombre: Copilot, Codex, Claude, User...}
- Objective: {qué intentas lograr}
- Hypothesis: {qué esperas que pase}
- Files changed: {lista de ficheros modificados}
- Commands executed: {comandos que ejecutaste}
- Metrics before: {score, matched, wrong, missed, extra, filings_coverage_pct, required_fields_coverage_pct — o N/A con razón}
- Metrics after: {score, matched, wrong, missed, extra, filings_coverage_pct, required_fields_coverage_pct — o N/A con razón}
- Tests: {nº passed, nº failed}
- Decision: {accept/reject y por qué}
- Next step: {qué viene después}
```

**Los 10 campos son obligatorios.** El pre-commit hook rechazará el commit si falta alguno.

Para saber el número de iteración: cuenta las entradas `## 20` existentes y suma 1.

---

## 6. Reglas de commit

### Cuándo commitear
- Después de cada `eval` que produzca nuevas métricas (mejora O regresión).
- Después de añadir un caso nuevo (case.json + acquire).
- Después de añadir o modificar tests.
- Después de cualquier refactor que toque más de 2 ficheros.

### Cómo commitear
1. Asegúrate de que `PHASE2_OPERATIONS_LOG.md` tiene la nueva entrada completa.
2. Asegúrate de que `CHANGELOG.md` tiene la línea `[DETERMINISTIC]`.
3. Haz stage de TODO junto:
   ```bash
   git add deterministic/PHASE2_OPERATIONS_LOG.md CHANGELOG.md {ficheros_modificados}
   ```
4. Commit con mensaje descriptivo:
   ```bash
   git commit -m "deterministic: breve descripción del cambio"
   ```
5. **Un commit = una iteración.** No acumules múltiples cambios en un commit.
6. **Nunca uses `--no-verify`** para saltarte el hook.

### Qué NO commitear
- `__pycache__/`, `.pyc`
- `extraction_result.json` (es output regenerable)
- `filings_manifest.json` (es output regenerable)
- Ficheros de filings descargados (`.htm`, `.txt`, `.clean.md`) — solo si son parte del caso de test

### Pre-commit hook
El repositorio tiene un pre-commit hook en `.githooks/pre-commit` que se activa con:
```bash
bash scripts/setup_git_hooks.sh
```
El hook **bloquea** cualquier commit que toque `deterministic/` sin incluir el log y changelog. Si te bloquea, lee el mensaje de error — te dice exactamente qué falta.

---

## 7. Flujo de trabajo para una tarea típica

```
1. Lee la última entrada del log → anota métricas actuales
2. Ejecuta tests → confirma que todo pasa (baseline verde)
3. Haz tu cambio
4. Ejecuta tests → confirma que siguen pasando
5. Ejecuta eval {TICKER} → anota métricas nuevas
6. Si hay regresión → revierte o arregla antes de continuar
7. Escribe la entrada en PHASE2_OPERATIONS_LOG.md
8. Añade línea en CHANGELOG.md
9. Commit
```

Si en el paso 6 hay regresión y no puedes arreglarla, **no commitees**. Informa al usuario.

---

## 8. Convenciones de código

### Estilo
- Python 3.10+. Type hints en todas las funciones públicas.
- Docstrings en formato Google.
- Imports absolutos desde raíz: `from deterministic.src.schemas import FieldResult`.
- Nunca imports relativos.

### Dataclasses
- Toda estructura de datos va en `schemas.py` como `@dataclass`.
- Incluir `to_dict()` si el objeto se serializa a JSON.

### Nombres de campos canónicos
Los 22 campos están definidos en `config/field_aliases.json`:
```
ingresos, cost_of_revenue, gross_profit, ebitda, ebit, net_income,
eps_basic, eps_diluted, total_assets, total_liabilities, total_equity,
cash_and_equivalents, total_debt, cfo, capex, fcf, dividends_per_share,
shares_outstanding, research_and_development, sga,
depreciation_amortization, interest_expense, income_tax
```
Si necesitas añadir un campo, añádelo a `field_aliases.json` Y a `expected.json` de los casos.

### Tests
- Unit tests en `deterministic/tests/unit/`, uno por módulo: `test_{modulo}.py`.
- Integration tests en `deterministic/tests/integration/`.
- Fixtures en `deterministic/tests/fixtures/`.
- Cada nueva funcionalidad necesita tests. No hay excepciones.

### Evaluación
- `evaluate.py` usa tolerancia ±1% para comparar valores numéricos.
- Score = `matched / total_expected * 100`.
- Métricas: `matched`, `wrong`, `missed`, `extra`, `score`, `filings_coverage_pct`, `required_fields_coverage_pct`.

### Scale Cascade (DT-1)
La inferencia de escala sigue 5 niveles de prioridad:
1. `raw_notes` — notas explícitas en el filing ("in thousands")
2. `header` — cabeceras de tabla ("$M")
3. `preflight` — detección de `detect.py`
4. `field_multiplier` — de `field_aliases.json` (actualmente todos null)
5. `uncertainty` — fallback: raw con confianza "low"

---

## 9. Casos de test actuales

| Ticker | Source | Filings | Último score | Estado |
|--------|--------|---------|-------------|--------|
| TZOO   | SEC    | 28      | 52.9% (18/34) | Iterando (target ≥85%) |
| GCT    | SEC    | 26      | Pendiente eval |
| TEP    | EU manual | 0    | Sin filings |

### Estructura de expected.json
```json
{
  "version": "1.0",
  "ticker": "TZOO",
  "currency": "USD",
  "scale": "mixed",
  "scale_notes": "...",
  "periods": {
    "FY2024": {
      "fecha_fin": "2024-12-31",
      "tipo_periodo": "anual",
      "fields": {
        "ingresos": { "value": 83902, "source_filing": "SRC_001_10-K_FY2024.clean.md" },
        ...
      }
    }
  }
}
```
Los valores en expected.json son **ground truth curado manualmente**. Solo modifícalos si hay un error demostrable en el curado original.

---

## 10. Errores comunes que debes evitar

1. **Importar de `engine/` o `scripts/`** → Rompe el aislamiento. Nunca.
2. **Usar `python` en vez de `python3`** → Puede ejecutar Python 2. Siempre `python3`.
3. **Commitear sin log + changelog** → El hook te bloqueará. Lee el error.
4. **Acumular cambios en un solo commit** → Un commit = una iteración.
5. **No ejecutar tests antes del cambio** → No sabes si la regresión es tuya.
6. **Editar `extraction_result.json` a mano** → Es output generado. Regenera con `extract`.
7. **Editar `filings_manifest.json` a mano** → Es output generado. Regenera con `acquire`.
8. **Asignar periodo "unknown"** → El pipeline descarta campos sin periodo. Es correcto.
9. **Añadir dependencias sin aprobación** → Solo requests, bs4, pypdf.
10. **No reportar métricas** → Sin before/after no se puede evaluar el impacto.

---

## 11. Qué hacer si no sabes algo

- **No inventes.** Pregunta al usuario.
- **No asumas el comportamiento de un módulo.** Lee el código fuente.
- **No modifiques expected.json** sin evidencia del filing original.
- **Si algo falla y no entiendes por qué:** ejecuta el test individual con `-v`, lee el traceback completo, repórtalo.

---

## 12. Prioridades actuales (febrero 2026)

1. **Subir score de TZOO** de 52.9% a ≥85%. Foco: label collisions (net_income vs EPS), liability/equity ambiguity, tax line disambiguation.
2. **Evaluar GCT** — ya tiene filings, necesita expected.json y primer eval.
3. **TEP** — necesita implementar bootstrap EU manual y descargar filings.
4. **No tocar** el pipeline LLM (engine/, scripts/) salvo petición explícita.

---

## 13. Resumen ejecutivo para el agente

Antes de cada tarea, hazte estas preguntas:

```
✓ ¿He leído la última entrada del log?
✓ ¿He ejecutado los tests y están verdes?
✓ ¿Mi cambio toca algo fuera de deterministic/?  → Confirmar con usuario
✓ ¿He ejecutado eval antes y después?
✓ ¿He escrito la entrada en el log con los 10 campos?
✓ ¿He actualizado CHANGELOG.md?
✓ ¿Estoy listo para commitear (un commit = una iteración)?
```

Si alguna respuesta es "no", **para y completa ese paso** antes de continuar.
