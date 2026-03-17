# ELSIAN-INVEST 4.0 — Knowledge Base Completa

> Este documento contiene TODO el conocimiento acumulado sobre el proyecto ELSIAN-INVEST 4.0.
> Diseñado para ser consumido por un agente especializado (skill) que necesita contexto completo
> del proyecto sin depender de historial de conversación.
> Fecha: 5 marzo 2026. Autor: Elsian (propietario del proyecto).

---

## 1. QUÉ ES ELSIAN-INVEST

ELSIAN-INVEST es un sistema de inversión personal construido por Elsian (Ismael Sánchez García, gestion@elsian.es). No es un producto comercial. Es una herramienta privada para análisis de inversión fundamentale. El objetivo final es tener un sistema que, dado cualquier empresa cotizada del mundo, pueda extraer todos sus datos financieros, calcular métricas derivadas, analizar cualitativamente sus filings, y producir una decisión de inversión informada.

El sistema se construye de forma modular. Cada módulo es independiente y funcional por sí solo.

### Repositorios

- **4_0-ELSIAN-INVEST** (activo): El repositorio principal. ~18,000 líneas de código Python + ~12,500 líneas de tests. 15 tickers validados al 100%.
- **3_0-ELSIAN-INVEST** (congelado): El laboratorio anterior. ~30,000 líneas (engine LLM 14.6K + scripts/runners 11.6K + deterministic 3.8K). Se usa solo como referencia de lectura. Todo conocimiento útil del 3.0 está portado al 4.0.

### Historia del proyecto

El 3.0 fue un laboratorio donde se descubrió: qué fuentes de datos existen, cómo se estructuran los filings de cada regulador, qué reglas de extracción funcionan, cómo evaluar calidad, cómo manejar restatements y colisiones entre filings. Pero el código era un desorden: un engine de orquestación LLM (~14,600 líneas) que nadie entendía, scripts sueltos (~11,600 líneas), y un módulo deterministic (~3,800 líneas) que nació para resolver que ningún ticker tenía datos correctamente extraídos.

La decisión de crear el 4.0 (documentada en IDEAS.md, Idea #11) fue reemplazarlo completamente con un sistema modular, con clases Python, desde cero. El 3.0 está congelado.

---

## 2. VISIÓN Y REGLA DE ORO

El documento canónico es `VISION.md` en la raíz del repo 4.0. Todo agente que trabaje en el proyecto debe leerlo primero. Si algo contradice VISION.md, VISION.md prevalece.

### La regla de oro

**No se trabaja en ningún módulo futuro, ni en infraestructura de producto, ni en API, ni en visor web, ni en análisis, hasta que el Pipeline de Extracción Financiera (Módulo 1) funcione de forma irrefutable.** Cualquier desvío hacia fases comerciales, capas de LLM, o funcionalidad de análisis sin que el módulo de extracción esté completo y maduro es una pérdida de foco y una repetición del error que ya cometimos.

### Error histórico: la deriva estratégica

En sesiones anteriores, tanto los agentes como las conversaciones tendían a derivar hacia "producto comercial" (API REST, visor web, LLM analysis, scheduler de actualización). Elsian tuvo que corregir esto explícitamente: "Necesito que recuperes la cordura. Lo importante es construir el pipeline de principio a fin, totalmente modular, con clases de Python. Todo lo de API, visor web, etc solo se planteará una vez que el pipeline esté totalmente funcional en 4.0."

Se creó VISION.md y se actualizó el agente Director para prevenir que esto vuelva a ocurrir. ROADMAP.md es aspiracional, no operativo. VISION.md es la realidad.

---

## 3. ARQUITECTURA DEL MÓDULO 1

### Principios de diseño (7 principios fundamentales)

1. **Módulos independientes.** Cada módulo tiene responsabilidad clara, CLI propio, tests autónomos.
2. **Arquitectura de clases desde el día uno.** ABCs, `run(context) → result`. Composición e inyección de dependencias. Añadir nuevo fetcher/extractor/regulador = nueva clase + registro.
3. **Código reutilizable y escalable.** SecEdgarFetcher y AsxFetcher comparten interfaz Fetcher. HtmlTableExtractor y PdfTableExtractor comparten interfaz Extractor.
4. **Zero-LLM en extracción cuantitativa.** 100% determinista: regex, tablas, normalización por reglas, evaluación por gates. Reproducible, auditable, sin coste por ejecución.
5. **Testing como ciudadano de primera.** Cada ticker al 100% = test de regresión permanente. `eval --all` debe pasar al 100% ante cualquier cambio.
6. **Provenance como principio fundacional.** Cada dato trazable hasta su origen exacto: fichero fuente, tabla, fila, columna, texto original.
7. **Configuración sobre código.** Aliases, reglas de selección, prioridades — todo en JSON.

### Pipeline: Acquire → Convert → Extract → Normalize → Merge → Evaluate → Assemble

#### Acquire (adquisición de filings)
Fetchers por regulador. Cada mercado = una clase Fetcher nueva.

| Fetcher | Mercado | Mecanismo |
|---|---|---|
| SecEdgarFetcher | SEC (US) | EDGAR EFTS API. CIK lookup. Descarga 10-K/10-Q/20-F/6-K/8-K. Exhibit 99.1 para 6-K y 8-K. |
| EuRegulatorsFetcher | Euronext (FR, NL, BE, etc.) | IR crawler integrado. Descubre URLs de annual/interim reports desde web_ir. |
| AsxFetcher | ASX (Australia) | API genérica con ventanas de 1 día, escaneo hacia atrás. |
| ManualFetcher | Fallback | Lee filings de filings_sources hardcodeadas en case.json. |
| MarketDataFetcher | Todos | Finviz (US), Stooq (OHLCV), Yahoo Finance (non-US). |
| TranscriptFinder | Todos | Fintool transcripts + IR presentations. |
| SourcesCompiler | Todos | Merge multi-fetcher con dedup por hash SHA-256. |

Ficheros: `elsian/acquire/sec_edgar.py` (508L), `eu_regulators.py` (484L), `asx.py`, `manual.py`, `ir_crawler.py` (919L), `market_data.py` (830L), `transcripts.py` (1085L), `sources_compiler.py` (749L).

#### Convert (transformación de formatos)
- HTML → Markdown con detección de secciones (IS/BS/CF/Notes/MD&A). Fichero: `elsian/convert/html_to_markdown.py`
- PDF → texto con pdfplumber. Fichero: `elsian/convert/pdf_to_text.py`
- Quality gates sobre clean.md: `elsian/convert/clean_md_quality.py` (242L)

#### Extract (extracción de datos — el músculo del sistema)
Múltiples extractores que producen FieldCandidate objects.

| Extractor | Líneas | Qué hace |
|---|---|---|
| HtmlTableExtractor | 2,256 | Regex + estructura de tablas HTML/Markdown. Multilingüe. Multi-formato. |
| IxbrlExtractor | 294 | Extractor de producción para iXBRL. Máxima prioridad (sort key -9999). |
| PdfTableExtractor | 648 | pdfplumber structured tables para PDFs. |
| NarrativeExtractor | 304 | Patrones de texto en MD&A y notas. |
| VerticalBSExtractor | (en vertical.py) | Balance sheets con layout no tabular. |

El parser iXBRL base (`ixbrl.py`, 589L) es compartido entre IxbrlExtractor (producción) y `elsian curate` (herramienta de desarrollo).

**IxbrlExtractor diseño clave:**
- `has_ixbrl(filepath)`: Detecta iXBRL leyendo primeros 8KB buscando `xmlns:ix=` o `<ix:header`.
- `extract(filepath, fiscal_year_end_month)`: Parse → deduplicate → map concepts → normalize sign/scale.
- Sort key: `(filing_rank, affinity, -1, -9999)` — iXBRL siempre gana vs table/narrative.
- Dominant scale: Detecta escala mayoritaria del filing. Tags con escala distinta se convierten y marcan `was_rescaled=True`, lo que debilita el sort key para que la tabla pueda ganar con datos más precisos.
- Provenance: `extraction_method="ixbrl"`, `row_label=concept`, `raw_text=displayed_value`.

Fichero orquestador: `elsian/extract/phase.py` (1,415L). ExtractPhase.extract() orquesta todos los extractores por filing, resuelve colisiones por sort key, y produce extraction_result.json.

#### Normalize (normalización de datos)
- **AliasResolver** (`aliases.py`): 150+ aliases multilingüe (EN/FR/ES/DE) por campo canónico. Config: `config/field_aliases.json`.
- **ScaleCascade** (`scale.py`): 5 niveles de inferencia de escala (preflight units_by_section → filing header → table context → raw value → fallback).
- **SignEnforcement** (`signs.py`): capex siempre negativo, revenue siempre positivo. _ALWAYS_POSITIVE fields.
- **SanityChecks** (`sanity.py`): 4 reglas post-extracción no bloqueantes (capex_positive auto-fix, revenue_negative, gp>revenue, YoY jump >10x).
- **AuditLog** (`audit.py`): Trazabilidad de cada decisión de normalización.

#### Merge (fusión multi-filing)
`elsian/merge/merger.py`. Prioridad: 10-K/20-F > 10-Q/6-K > 8-K/earnings. Resolución de colisiones por (filing_rank, affinity, src_type_rank, semantic_rank). Deduplicación por (campo, periodo).

#### Evaluate (validación y evaluación)
- **Autonomous Validator** (`validation.py`, 708L): 9 quality gates intrínsecos que NO necesitan expected.json: BALANCE_IDENTITY (±2%), CASHFLOW_IDENTITY (±5%), UNIDADES_SANITY (1000x), EV_SANITY, MARGIN_SANITY (20 sectores), TTM_SANITY, TTM_CONSECUTIVE, RECENCY_SANITY, DATA_COMPLETENESS.
- **CoverageAudit** (`coverage_audit.py`): Clasificación issuer (Domestic_US/FPI_ADR/NonUS_Local), thresholds por clase.
- **ValidateExpected** (`validate_expected.py`): 8 errores estructurales + 2 sanity warnings sobre expected.json.
- **Evaluator** (`evaluator.py`): Comparación extractado vs ground truth. Tolerance 0.5%.
- **Dashboard** (`dashboard.py`): Reportes visuales.

#### Assemble (ensamblaje del output final)
`elsian/assemble/truth_pack.py` (295L). TruthPackAssembler combina:
- extraction_result.json (datos financieros)
- _market_data.json (precios, shares outstanding)
- Métricas derivadas (TTM, FCF, EV, márgenes, retornos, múltiplos)
- Autonomous validation (9 gates summary)
→ Produce `truth_pack.json` (TruthPack_v1 schema). Este es el "producto" del Módulo 1.

### Componentes de soporte

- **Calculadora de métricas derivadas** (`calculate/derived.py`, 714L): TTM (cascade 4Q → semestral → FY0), Q4 sintético, FCF, EV, márgenes (gross/op/net/FCF), retornos (ROIC/ROE/ROA), múltiplos (EV/EBIT, EV/FCF, P/FCF), net_debt, per-share. Null propagation.
- **Filing Preflight** (`analyze/preflight.py`, 319L): Detección determinista de idioma, estándar contable, moneda, secciones financieras, unidades por sección, restatement, año fiscal. <1ms por filing.
- **Auto-discovery** (`discover/discover.py`, 564L): Dado un ticker symbol, detecta mercado, regulador, moneda, estándar contable, CIK, web_ir, fiscal_year_end_month. SEC vía EDGAR API, non-US vía Yahoo Finance.

### CLI Commands

| Comando | Qué hace |
|---|---|
| `elsian eval {TICKER}` | Evalúa un ticker contra expected.json |
| `elsian eval --all` | Evalúa todos los tickers validados |
| `elsian run {TICKER}` | Pipeline completo: Convert→Extract→Evaluate→Assemble |
| `elsian run --all` | Pipeline completo para todos los tickers |
| `elsian acquire {TICKER}` | Descarga filings del regulador |
| `elsian curate {TICKER}` | Genera expected_draft.json desde iXBRL |
| `elsian discover {TICKER}` | Auto-genera case.json para un ticker nuevo |
| `elsian assemble {TICKER}` | Genera truth_pack.json |
| `elsian dashboard {TICKER}` | Reporte visual de extracción |
| `elsian coverage {TICKER}` | Auditoría de cobertura |
| `elsian compile {TICKER}` | Compila fuentes de datos |
| `elsian market {TICKER}` | Descarga datos de mercado |
| `elsian transcripts {TICKER}` | Busca earnings call transcripts |

### Modelos de datos clave

```python
@dataclass
class Provenance:
    source_filing: str       # "SRC_001_10-K_FY2024.htm"
    source_location: str     # "SRC_001:ixbrl:ctx_001:us-gaap:Revenue"
    table_index: int | None  # Tabla # en el documento
    table_title: str         # "CONSOLIDATED STATEMENTS OF INCOME"
    row_label: str           # "Total net revenue"
    col_label: str           # "FY2024"
    row: int | None          # Fila en la tabla
    col: int | None          # Columna en la tabla
    raw_text: str            # "1,234,567" (texto original de la celda)
    extraction_method: str   # "table" | "narrative" | "ixbrl" | "manual"

@dataclass
class FieldResult:
    value: float             # Valor numérico normalizado
    provenance: Provenance   # Trazabilidad completa
    scale: str               # "thousands" | "millions" | "raw"
    confidence: str          # "high" | "medium" | "low"
```

### Estructura de un caso (ticker)

```
cases/{TICKER}/
├── case.json              # Configuración del ticker (mercado, moneda, CIK, etc.)
├── expected.json          # Ground truth curado para evaluación
├── filings/               # Filings descargados (.htm, .pdf, .txt)
│   ├── SRC_001_10-K_FY2024.htm
│   ├── SRC_001_10-K_FY2024.clean.md
│   └── ...
├── extraction_result.json # Resultado de extracción (generado)
├── truth_pack.json        # Output final (generado, en .gitignore)
└── filings_manifest.json  # Inventario de filings (generado)
```

### Configuración (config/)

- **field_aliases.json**: Mapa de aliases multilingüe por campo canónico. Cada campo tiene aliases en EN, FR, ES, DE, reject patterns, y priority rules.
- **ixbrl_concept_map.json**: Mapa de conceptos iXBRL (US-GAAP + IFRS) a campos canónicos.
- **selection_rules.json**: Reglas de selección de filings por tipo y prioridad.

### 26 campos canónicos actuales

**Income Statement:** revenue, cost_of_revenue, gross_profit, sga, research_and_development, operating_income, interest_expense, interest_income, income_tax, net_income, ebitda, depreciation_amortization, eps_basic, eps_diluted, dividends_per_share, shares_outstanding

**Balance Sheet:** total_assets, total_liabilities, total_equity, total_debt, cash_and_equivalents

**Cash Flow:** operating_cash_flow, capex, cfi (investing), cff (financing), delta_cash

**Pendientes (BL-047b):** accounts_receivable, inventories, accounts_payable

---

## 4. ESTADO ACTUAL (5 marzo 2026)

### Métricas clave
- **15/15 PASS 100%** (eval --all)
- **1,254 tests passed**, 5 skipped, 0 failed
- **3,333 campos validados** con provenance completa
- **26 campos canónicos** (IS + BS + CF)
- **5 reguladores cubiertos**: SEC, Euronext, ASX, LSE/AIM, HKEX
- **18,089 líneas de código** + 12,450 líneas de tests
- **57 ficheros Python** en el módulo elsian

### 15 tickers validados

| Ticker | Campos | Mercado | Formato | Scope |
|---|---|---|---|---|
| TZOO | 288 | SEC (US) | 10-K/10-Q HTML | FULL (6A+12Q) |
| NVDA | 336 | SEC (US) | 10-K/10-Q HTML | FULL (6A+12Q) |
| SONO | 311 | SEC (US) | 10-K HTML | FULL (6A+12Q) |
| GCT | 252 | SEC (US) | 20-F→10-K HTML | FULL (6A+9Q) |
| TALO | 183 | SEC (US) | 10-K/10-Q HTML | FULL (5A+7Q) |
| PR | 141 | SEC (US) | 10-K/10-Q HTML | FULL (3A+6Q) |
| IOSP | 338 | SEC (US) | 10-K/10-Q HTML | FULL (5A+17Q) |
| NEXN | 153 | SEC (US) | 20-F/6-K HTML | FULL (4A+6Q) |
| ACLS | 375 | SEC (US) | 10-K/10-Q HTML | FULL (6A+15Q) |
| INMD | 210 | SEC (US) | 20-F/6-K HTML (IFRS) | FULL (6A+6Q) |
| CROX | 294 | SEC (US) | 10-K/10-Q HTML | FULL |
| TEP | 80 | Euronext (FR) | PDF (IFRS, EUR) | FULL (6A+2H) — 6 overrides† |
| KAR | 49 | ASX (AU) | PDF (IFRS, USD) | ANNUAL_ONLY (3A) |
| SOM | 179 | LSE/AIM (GB) | PDF (US-GAAP, USD) | ANNUAL_ONLY (16A) — 2 overrides |
| 0327 | 59 | HKEX (HK) | PDF (HKFRS, HKD) | ANNUAL_ONLY (3A) |

### Manual overrides (DEC-024)
- **TEP**: 6 overrides (7.5% > límite 5%). Campos: ingresos FY2022/FY2021, fcf FY2022/FY2021/FY2019, dps FY2021. Los datos existen en los PDFs pero el PdfTableExtractor no los extrae.
- **SOM**: 2 overrides (1.1%). dividends_per_share FY2024/FY2023. DPS solo aparece en narrativa dispersa en formato cents, no en tabla.
- **Total**: 8 overrides / 3,333 campos = 0.24% global.
- **Criterio de autonomía (DEC-026)**: NO alcanzado. Requiere 0 overrides.

---

## 5. FLUJO DE TRABAJO PARA AÑADIR UN TICKER NUEVO

1. `elsian discover {TICKER}` → genera case.json automáticamente
2. `elsian acquire {TICKER}` → descarga filings del regulador
3. `elsian curate {TICKER}` → genera expected_draft.json (desde iXBRL para SEC, esqueleto para otros)
4. **Revisión humana/agente** → depura el draft → expected.json final
5. `elsian run {TICKER}` → Convert → Extract → Evaluate → Assemble
6. **Iterar** si score < 100% → diagnosticar gaps, mejorar extractores, re-run
7. **Registrar** en VALIDATED_TICKERS en test_regression.py

El paso 4 es el que no se puede automatizar al 100%. Para SEC, curate genera un draft muy bueno (~100% campos con tag iXBRL). Para no-SEC, es semi-manual.

---

## 6. MÓDULOS FUTUROS (NO ACTIVOS)

Listados para contexto. No se trabaja en ellos ahora:

- **Módulo 2 — Extracción cualitativa (LLM-assisted):** MD&A, risk factors, guidance. Requiere LLM con trazabilidad al párrafo.
- **Módulo 3 — LLM fallback cuantitativo:** Completar datos que la capa determinista no pudo extraer. El ground truth curado del Módulo 1 valida que el fallback sea correcto.
- **Módulo 4 — Análisis y decisión:** IMPLIED expectations, CATALYST detection, BULL/RED_TEAM analysis, ARBITRO.
- **Infraestructura de producto:** API REST, PostgreSQL, visor web, scheduler.

Arquitectura de 4 capas (de IDEAS.md):
- Layer 0: Sources (filings descargados)
- Layer 1: Deterministic/zero-LLM (extracción cuantitativa) ← **MÓDULO 1, foco actual**
- Layer 2: Qualitative/LLM (extracción cualitativa)
- Layer 3: LLM fallback cuantitativo
- Layer 4: Analysis & Decision

---

## 7. METODOLOGÍA DE TRABAJO

### Organización por agentes
- **Elsian (humano)**: Propietario del proyecto. Define visión, aprueba decisiones, lanza oleadas.
- **Project Director (agente Claude)**: Coordina, prioriza BACKLOG, lanza sub-agentes, revisa governance. Lee VISION.md obligatoriamente al inicio de cada sesión.
- **elsian-4 (agente Claude)**: Ejecuta tareas técnicas del BACKLOG. Lee las primeras 3-5 tareas y trabaja de arriba a abajo.
- **Copilot (Claude en Cowork)**: Estrategia, diseño de arquitectura, revisión de código, planificación de oleadas.
- **Codex (OpenAI)**: Auditoría independiente, verificación de evidencia, validación de governance.

### Documentos de proyecto
| Documento | Qué es | Quién lo mantiene |
|---|---|---|
| VISION.md | Referencia canónica del proyecto | Elsian (solo lectura para agentes) |
| PROJECT_STATE.md | Estado actual con métricas reales | Director |
| BACKLOG.md | Cola de tareas priorizadas | Director |
| DECISIONS.md | Registro de decisiones estratégicas | Director |
| CHANGELOG.md | Log de cambios técnicos | elsian-4 |
| ROADMAP.md | Visión a largo plazo (aspiracional) | Elsian |

### Oleadas de trabajo
Las tareas se agrupan en oleadas para ejecución paralela. Criterios de paralelización:
1. **Sin dependencias lógicas** entre tareas de la misma oleada
2. **Sin conflictos de ficheros** — cada tarea toca directorios distintos
3. **Verificación post-oleada**: eval --all + pytest + Codex audit

### Oleadas completadas
- **Oleada 1 (cierre Módulo 1)**: BL-042 SOM + BL-049 Truth Pack + BL-051 Auto-discovery. 3 en paralelo. Resultado: 14/14 PASS.
- **Oleada 2 (cierre Módulo 1)**: BL-048 IxbrlExtractor + BL-050 elsian run + BL-043 0327 HKEX + BL-056 gitignore. 4 en paralelo. Resultado: 15/15 PASS tras hotfix de 4 regresiones.

---

## 8. VULNERABILIDADES CONOCIDAS

### V1 — Aliases globales causan regresiones cruzadas
**Severidad: ALTA.** Cada vez que se modifica `field_aliases.json` o la lógica de prioridad en `phase.py`, hay probabilidad alta de regresión en otros tickers. Esto ya ha ocurrido múltiples veces:
- BL-042 (SOM): cambio en income_tax sign → regresión en TEP
- BL-043 (0327): aliases D&A sub-componentes → regresión en TEP + SOM
- BL-048 (IxbrlExtractor): sort key iXBRL → regresión en SONO + ACLS

**Mitigación actual**: eval --all como gate obligatorio. Hotfixes inmediatos.
**Mitigación necesaria**: Case-scoping de aliases (ya existe `additive_fields` per-case). Más tests de no-regresión específicos.

### V2 — Fiscal year no-calendario en iXBRL
**Severidad: MEDIA.** SONO tiene fiscal year ending en octubre. El IxbrlExtractor mapeaba periodos asumiendo calendario. Fix aplicado (calendar quarter del end date), pero cualquier ticker con fiscal year atípico es un edge case a vigilar.

### V3 — TEP tiene 6 overrides (7.5%)
**Severidad: MEDIA.** El PdfTableExtractor no cubre los formatos de tabla/KPI dashboard de annual reports franceses. Los datos existen en los filings pero no se extraen. BL-054 pendiente.

### V4 — Curación de expected.json para no-SEC es semi-manual
**Severidad: MEDIA.** Para tickers sin iXBRL (Euronext, ASX, LSE, HKEX), los agentes crean expected.json manualmente. Esto es lento y propenso a error/trampa (incidente SOM DEC-022). BL-052 pendiente.

### V5 — Agentes hacen trampa
**Severidad: ALTA.** Incidente documentado en DEC-022: el agente declaró SOM al 100% (36/36) pero había reducido deliberadamente expected.json a solo 18 campos/2 periodos cuando existían 16 años de datos. Mitigación: auditoría independiente con Codex, regla de mínimo campos por ticker, Provenance como requisito.

### V6 — html_tables.py es monolítico (2,256 líneas)
**Severidad: BAJA.** Es el fichero más grande del proyecto y concentra mucha lógica. Cualquier cambio tiene blast radius grande. Refactoring deseable pero no urgente.

### V7 — Governance docs se desactualizan
**Severidad: MEDIA.** PROJECT_STATE, CHANGELOG y BACKLOG frecuentemente contienen datos desactualizados o fechas incorrectas. Codex ha detectado esto múltiples veces. Mitigación: auditoría post-oleada obligatoria.

---

## 9. FORTALEZAS DEL PROYECTO

### F1 — Zero-LLM determinístico
Todo es reproducible. Ejecutar el pipeline hoy y mañana con los mismos filings produce exactamente los mismos números. Sin costes por ejecución. Sin alucinaciones.

### F2 — Provenance completa (Level 2)
Cada uno de los 3,333 campos es trazable hasta tabla, fila, columna y texto original del filing. Esto es diferenciador — la mayoría de servicios de datos financieros son cajas negras.

### F3 — Suite de regresión verde
1,254 tests. eval --all 15/15 100%. Cualquier commit que rompa un ticker es detectado inmediatamente.

### F4 — Multi-mercado real
SEC (US), Euronext (FR), ASX (AU), LSE/AIM (GB), HKEX (HK). 4 idiomas (EN/FR/ES/DE). 3 estándares (US-GAAP, IFRS, HKFRS). HTML + PDF + iXBRL.

### F5 — Arquitectura extensible
Añadir un nuevo mercado = crear una clase Fetcher. Añadir un nuevo formato = crear una clase Extractor. El pipeline no cambia.

### F6 — Métricas derivadas completas
TTM, FCF, EV, márgenes, retornos, múltiplos, per-share. Todo con null propagation (si un input falta, el output es null, no un número inventado).

### F7 — Auditoría cruzada
Combinación de Claude (Director, elsian-4, Copilot) y Codex (OpenAI) para verificar trabajo. Esto evita que un solo modelo pueda hacer trampa sin ser detectado.

---

## 10. BACKLOG ACTUAL (TODO)

### Prioridad ALTA
- **BL-054**: Eliminar 6 overrides de TEP. Mejorar PdfTableExtractor para formatos franceses.

### Prioridad MEDIA
- **BL-047**: Mejorar HTML extractor: interest_income + capex (gaps en NVDA).
- **BL-047b**: Working capital fields: accounts_receivable, inventories, accounts_payable (campos 27-29).
- **BL-055**: Clasificar overrides SOM DPS: ¿fixable o permanent exception?
- **BL-052**: Auto-curate para tickers no-SEC (expected.json desde PDF).
- **BL-005**: Expandir cobertura de tickers (diversidad: financiero, REIT, utility, alemán, español).

### Prioridad BAJA
- **BL-057**: Discovery automático LSE/AIM (CDNs corporativos UK).
- **BL-053**: Provenance Level 3 (source_map.json para "click to source").

---

## 11. DECISIONES CLAVE (resumen)

| DEC | Qué decide |
|---|---|
| DEC-004 | Convención de signos: capex negativo, revenue positivo |
| DEC-008 | Fetchers pueden usar filings_sources manuales como excepción |
| DEC-009 | Portar desde 3.0, no reimplementar |
| DEC-010 | Parser iXBRL reutilizable: un parser, dos consumidores (curate + producción) |
| DEC-011 | Plan de ejecución WP-1 a WP-6 |
| DEC-015 | Tickers ANNUAL_ONLY cuentan como FULL si no hay quarterly disponible |
| DEC-020 | Scope creep de sub-agentes = bug |
| DEC-022 | SOM fraudulentamente débil — reconstruir desde cero |
| DEC-024 | Política de overrides: límite 5% por ticker, transparencia obligatoria |
| DEC-025 | SOM aprobado con filings_sources manuales (CDN no crawleable) |
| DEC-026 | Criterio de autonomía: 0 overrides para certificar "autónomo suficiente" |

---

## 12. ESTRUCTURA DEL REPOSITORIO

```
4_0-ELSIAN-INVEST/
├── VISION.md                          # Referencia canónica
├── ROADMAP.md                         # Visión a largo plazo (aspiracional)
├── CHANGELOG.md                       # Log de cambios técnicos
├── pyproject.toml                     # Python >=3.11
├── .github/
│   ├── agents/
│   │   └── project-director.agent.md  # Instrucciones del Director
│   └── workflows/
│       └── ci.yml                     # GitHub Actions: pytest en Python 3.11
├── config/
│   ├── field_aliases.json             # Aliases multilingüe (150+)
│   ├── ixbrl_concept_map.json         # Mapa conceptos iXBRL → canónicos
│   └── selection_rules.json           # Reglas de selección de filings
├── cases/                             # 15 tickers (case.json + expected.json + filings/)
│   ├── TZOO/
│   ├── NVDA/
│   ├── ...
│   └── 0327/
├── elsian/                            # Módulo principal (~18,000L)
│   ├── cli.py                         # Entry point CLI
│   ├── pipeline.py                    # Pipeline orchestrator
│   ├── context.py                     # PipelineContext
│   ├── config.py                      # CaseConfig loader
│   ├── markets.py                     # Exchange/country/regulator awareness
│   ├── models/                        # Dataclasses: FieldResult, Provenance, CaseConfig
│   ├── acquire/                       # Fetchers por regulador + market data + transcripts
│   ├── convert/                       # HTML→MD, PDF→text, quality gates
│   ├── extract/                       # Extractores + phase orchestrator
│   ├── normalize/                     # Aliases, scale, signs, sanity, audit
│   ├── merge/                         # Multi-filing merger
│   ├── evaluate/                      # Validator, evaluator, coverage, dashboard
│   ├── analyze/                       # Filing preflight
│   ├── calculate/                     # Métricas derivadas
│   ├── assemble/                      # Truth Pack assembler
│   └── discover/                      # Auto-discovery de ticker
├── tests/                             # ~12,450L, 1,254 tests
│   ├── unit/                          # Tests unitarios por módulo
│   └── integration/                   # Tests de integración + regresión
└── docs/project/                      # Governance
    ├── PROJECT_STATE.md
    ├── BACKLOG.md
    ├── DECISIONS.md
    └── FIELD_DEPENDENCY_MATRIX.md
```

---

## 13. CÓMO INTERACTUAR CON EL PROYECTO

### Para auditar el estado
```bash
python3 -m elsian eval --all          # 15/15 PASS?
python3 -m pytest -q                   # Tests verdes?
git log --oneline -10                  # Commits recientes
git status                             # Ficheros sin commitear
```

### Para ejecutar el pipeline en un ticker
```bash
python3 -m elsian run TZOO             # Pipeline completo
python3 -m elsian run --all            # Todos los tickers
```

### Para añadir un ticker nuevo
```bash
python3 -m elsian discover AAPL        # Genera case.json
python3 -m elsian acquire AAPL         # Descarga filings
python3 -m elsian curate AAPL          # Genera expected_draft.json
# ... revisar draft → expected.json ...
python3 -m elsian run AAPL             # Pipeline + evaluación
```

### Para diagnosticar un fallo
```bash
python3 -m elsian eval TICKER          # Ver qué campos fallan
python3 -m elsian dashboard TICKER     # Reporte detallado
# Revisar extraction_result.json para ver provenance de cada campo
```

---

## 14. REGLAS PARA AGENTES QUE TRABAJEN EN ESTE PROYECTO

1. **Leer VISION.md antes de cualquier otra cosa.**
2. **No trabajar en módulos futuros, API, visor web, ni análisis.** Solo Módulo 1.
3. **eval --all debe pasar al 100% tras cualquier cambio.** Si introduces regresión, arréglala antes de commitear.
4. **No reducir expected.json para pasar tests.** Eso es hacer trampa (DEC-022).
5. **No usar manual_overrides excepto como último recurso** y con documentación completa (DEC-024).
6. **Provenance completa en cada FieldResult.** extraction_method ≠ "" siempre.
7. **Aliases nuevos deben ser case-scoped si son específicos de un formato/mercado.** No contaminar aliases globales.
8. **Tests para cada nueva funcionalidad.** Unit + integration.
9. **Un commit atómico por tarea.**
10. **Reportar métricas reales, no estimaciones.** Ejecutar pytest y eval --all, reportar números exactos.
