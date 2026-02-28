# Deterministic Extraction Module

Sistema de extracción financiera determinista diseñado para escalar a cualquier empresa cotizada del mundo.

Objetivo: dado un ticker de cualquier mercado, descargar sus filings regulatorios, extraer datos financieros estructurados y validarlos contra ground truth curado — sin dependencia de LLMs en la extracción core.

## Visión de Arquitectura

Este módulo no es un script de extracción — es un sistema de ingeniería pensado para crecer. La arquitectura objetivo se basa en clases con interfaces bien definidas por fase, de modo que cada componente sea intercambiable y testeable de forma aislada.

**Principios de diseño:**

- **Una clase por fase** (acquire, extract, normalize, merge, evaluate), cada una con un contrato de entrada/salida tipado.
- **Múltiples implementaciones por fase**: por ejemplo, `SecEdgarFetcher` y `EsefFetcher` para acquire; `IxbrlExtractor`, `TableExtractor` y `NarrativeExtractor` para extract. Se registran y el pipeline decide cuál usar según el caso.
- **Pipeline como orquestador ligero**: la clase `DeterministicPipeline` encadena fases y gestiona el contexto compartido (trazabilidad, audit log, confianza por dato). No contiene lógica de negocio.
- **Configuración sobre código**: reglas de selección, prioridades de filing, pesos de sección — todo vive en `config/`, con override por caso en `case.json`. Nada hardcodeado.
- **Cobertura global**: fetchers por regulador (SEC EDGAR, ESEF Europa, EDINET Japón...), iXBRL como fuente primaria donde exista, HTML/PDF como fallback universal.
- **Preparado para producción**: en fase de desarrollo usamos ground truth curado para validar reglas. En producción, el pipeline funciona solo — con una capa LLM posterior que revisa y completa lo que la extracción determinista no cubre con confianza suficiente.

La implementación actual está en transición hacia esta arquitectura. Ver `mejoras/IDEAS.md` para el roadmap detallado.

## Quick Start

```bash
# Install dependencies
pip3 install -r deterministic/requirements.txt --break-system-packages

# Setup git hooks (required for all contributors)
bash scripts/setup_git_hooks.sh

# Run full pipeline for a case
python3 -m deterministic.cli run TZOO

# Evaluate against expected.json
python3 -m deterministic.cli eval TZOO

# Dashboard of all cases
python3 -m deterministic.cli dashboard

# Run tests
python3 -m unittest discover -s deterministic/tests -v
```

## Structure

```
deterministic/
  src/
    acquire/     SEC EDGAR fetcher, HTML->Markdown, PDF->text
    extract/     Table parser, narrative extractor, filing detector
    normalize/   Alias resolution, scale inference (DT-1), audit log
    merge.py     Multi-filing merge with priority
    evaluate.py  Field-by-field comparison vs expected.json
    pipeline.py  DeterministicPipeline facade
    schemas.py   Dataclasses
  cases/         One directory per ticker (case.json, filings/, expected.json)
  config/        field_aliases.json (22 fields, ~150 aliases)
  schemas/       extraction_result_v1.json (JSON Schema)
  tests/         Unit + integration tests
  cli.py         CLI entry point
```

## Development Cycle

1. Create `cases/{TICKER}/case.json`
2. `python3 -m deterministic.cli acquire {TICKER}`
3. Curate `expected.json` from downloaded filings
4. `python3 -m deterministic.cli eval {TICKER}` — iterate until score >= 85%
5. `python3 -m deterministic.cli eval --all` — verify no regressions

## Agent Operating Contract (6 rules)

Any agent (Opus, Codex, User) working on `deterministic/` must follow these 6 rules:

1. **Before touching code:** read the last entry in `PHASE2_OPERATIONS_LOG.md` and note current metrics.
2. **Each relevant change = one new iteration** in `PHASE2_OPERATIONS_LOG.md` with all 10 fields.
3. **Always report before/after metrics** (score, matched, wrong, missed, extra). If not applicable, write `N/A` with reason.
4. **Run tests** (`python3 -m unittest discover -s deterministic/tests -v`) and record pass/fail count.
5. **Add a summary line** in `CHANGELOG.md` under today's date with tag `[DETERMINISTIC]`.
6. **Work is not done until commit is valid.** A change without commit + traceability does not exist.

### When to commit

- After every `eval` that produces new metrics (improvement or regression)
- After adding a new case (case.json + acquire)
- After adding or modifying tests
- After any refactor touching more than 2 files
- **One commit = one iteration.** Do not accumulate multiple changes in a single commit.

## Workflow and Mandatory Traceability (SOP)

Every commit touching `deterministic/` **must** include traceability artifacts. This is enforced by a pre-commit hook.

### What the hook checks

1. If any staged file is under `deterministic/src/`, `deterministic/tests/`, `deterministic/config/`, `deterministic/schemas/`, `deterministic/cases/`, `deterministic/cli.py`, or `deterministic/requirements.txt`...
2. Then `deterministic/PHASE2_OPERATIONS_LOG.md` **must** also be staged with a new entry.
3. And `CHANGELOG.md` **must** also be staged with a `[DETERMINISTIC]` line.
4. The last entry in the log **must** contain all 10 mandatory fields.

### The 10 mandatory fields

Every log entry must include:

- **Agent** — who made the change (Opus, Codex, User, etc.)
- **Objective** — what was the goal
- **Hypothesis** — what did we expect to happen
- **Files changed** — list of modified files
- **Commands executed** — tests run, CLI commands
- **Metrics before** — eval scores before the change
- **Metrics after** — eval scores after the change
- **Tests** — test results (count, pass/fail)
- **Decision** — accept/reject the change and why
- **Next step** — what comes next

### Setup

```bash
# Run once after cloning
bash scripts/setup_git_hooks.sh
```

This configures `git config core.hooksPath .githooks` so the versionned hook is active.

### If the hook blocks your commit

The error message tells you exactly what's missing. Fix it, re-stage, and commit again.

### Commits outside deterministic/

Not affected. The hook only triggers for changes under `deterministic/`.

## Ground Truth Sign Convention

Policy: **as-presented on the face of the financial statement**.

All values in `expected.json` use the sign as it appears on the primary financial statement. This means:

**Income Statement fields** — positive values represent the reported amount:
- `ingresos`, `cost_of_revenue`, `gross_profit`, `research_and_development`, `sga`, `depreciation_amortization`, `interest_expense`, `income_tax`: **POSITIVE** as reported on the face of the income statement (expenses are shown as positive numbers that reduce profit).
- `ebit`, `ebitda`, `net_income`: **POSITIVE** when profit, **NEGATIVE** when loss. The sign reflects the economic reality (a loss in FY2020 → negative net_income).
- `eps_basic`, `eps_diluted`: follow the sign of `net_income`.
- Exception: `income_tax` can be **NEGATIVE** only when the filing explicitly shows a tax benefit/credit (e.g., "benefit from income taxes" or a negative provision).

**Balance Sheet fields** — always positive as reported:
- `total_assets`, `total_liabilities`, `cash_and_equivalents`, `total_debt`: **POSITIVE**.
- `total_equity`: **POSITIVE** when positive equity, **NEGATIVE** when accumulated deficit exceeds contributed capital.

**Cash Flow fields:**
- `cfo`: **POSITIVE** when "net cash provided by operating activities", **NEGATIVE** when "net cash used in".
- `capex`: **ALWAYS NEGATIVE** (represents cash outflow for purchases of property/equipment as shown in investing activities).
- `fcf`: follows its reported sign (typically CFO + capex, but only if explicitly reported).

**Per-share / Shares:**
- `dividends_per_share`: **POSITIVE**.
- `shares_outstanding`: **POSITIVE**.

**Key principle:** never flip signs to normalize. If the filing shows cost_of_revenue as 10,469, store 10,469. If a 20-F shows cost of revenue in parentheses (200,362), that parenthetical means the filing is presenting it as a deduction — but on the face of most income statements, expenses appear as positive numbers. Use the value **as it would appear in a standard income statement presentation** (positive), not the parenthetical sign from a particular filing's formatting quirk.

**When in doubt:** check TZOO's `expected.json` as the reference implementation (scores 100%).

## Ground Truth Restatement Rules

Policy: **as-reported unless explicit restatement**.

- `expected.json` uses the value from the **primary filing of each period** (the 10-K/10-Q that covers that fiscal period).
- Exception: use a value from a later filing ONLY if that filing contains explicit textual evidence of an adjustment. Valid triggers: `restated`, `as revised`, `as corrected`, `reclassified`.
- If a later filing shows a different comparative number WITHOUT an explicit trigger, treat it as NOT a restatement. Keep the primary filing value.
- When applying a restatement, add a `restatement` block to the affected field documenting: trigger word, evidence text, which filing restated it, and the original value.
- Root of `expected.json` must include: `"restatement_policy": "as_reported_unless_explicit_restatement"`.

## Isolation

- 0 imports from `engine/` or `scripts/` (pipeline code)
- 0 LLM calls — pure Python
- Dependencies: `requests`, `beautifulsoup4`, `pypdf`
