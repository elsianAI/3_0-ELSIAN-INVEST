---
name: elsian-invest
description: "ELSIAN-INVEST 4.0 project knowledge base. Use this skill whenever working on the ELSIAN-INVEST project, financial data extraction pipeline, or any task involving the 4_0-ELSIAN-INVEST repository. Triggers on: ELSIAN, elsian-invest, financial extraction pipeline, Module 1, ticker validation, expected.json, extraction_result, truth_pack, field_aliases, iXBRL extractor, HTML table extractor, PDF extractor, eval --all, elsian CLI commands, filing pipeline, provenance, quality gates. This is the foundational skill — all other elsian-* skills depend on this knowledge."
---

# ELSIAN-INVEST 4.0 — Project Knowledge

This skill provides comprehensive knowledge about the ELSIAN-INVEST 4.0 project. Read this before doing any work on the project.

## First Steps — Always

1. Read `VISION.md` in the repo root. It is the canonical reference. If anything contradicts VISION.md, VISION.md wins.
2. Read `docs/project/PROJECT_STATE.md` for current metrics.
3. Read `docs/project/BACKLOG.md` for pending tasks.

## What This Project Is

ELSIAN-INVEST is a personal investment system built by Elsian (Ismael Sanchez Garcia). Not a commercial product. A private tool for fundamental investment analysis. The goal: given any publicly traded company in the world, extract all financial data, calculate derived metrics, qualitatively analyze filings, and produce an informed investment decision.

The system is modular. Each module is independent and functional on its own.

## The Golden Rule

**Do NOT work on any future module, product infrastructure, API, web viewer, or analysis until Module 1 (Financial Extraction Pipeline) works irrefutably.** Any drift toward commercial phases, LLM layers, or analysis features without the extraction module being complete and mature is a loss of focus.

Module 1 is the sole current focus. Everything else is deferred.

## Architecture — Module 1 Pipeline

```
Acquire → Convert → Extract → Normalize → Merge → Evaluate → Assemble
```

For detailed architecture, read `references/ELSIAN_INVEST_KNOWLEDGE_BASE.md` sections 3 and 12.

### Key Design Principles

1. **Independent modules** — each with clear responsibility, own CLI, own tests
2. **Class architecture from day one** — ABCs, `run(context) → result`, composition over inheritance
3. **Reusable and scalable** — new market = new Fetcher class, new format = new Extractor class
4. **Zero-LLM in quantitative extraction** — 100% deterministic: regex, tables, rule-based normalization
5. **Testing as first-class citizen** — every 100% ticker = permanent regression test
6. **Provenance as foundational principle** — every datum traceable to source file, table, row, column, raw text
7. **Configuration over code** — aliases, rules, priorities all in JSON config files

### Pipeline Stages

| Stage | What it does | Key files |
|---|---|---|
| Acquire | Download filings per regulator | `elsian/acquire/` (sec_edgar.py, eu_regulators.py, asx.py) |
| Convert | HTML→Markdown, PDF→text | `elsian/convert/` |
| Extract | Parse financial data from documents | `elsian/extract/` (phase.py orchestrator, html_tables.py, ixbrl_extractor.py, pdf_tables.py) |
| Normalize | Aliases, scale, signs, sanity | `elsian/normalize/` (aliases.py, scale.py, signs.py) |
| Merge | Multi-filing fusion with collision resolution | `elsian/merge/merger.py` |
| Evaluate | 9 quality gates + comparison vs expected.json | `elsian/evaluate/` |
| Assemble | Build truth_pack.json | `elsian/assemble/truth_pack.py` |

### 26 Canonical Fields

**IS:** revenue, cost_of_revenue, gross_profit, sga, research_and_development, operating_income, interest_expense, interest_income, income_tax, net_income, ebitda, depreciation_amortization, eps_basic, eps_diluted, dividends_per_share, shares_outstanding

**BS:** total_assets, total_liabilities, total_equity, total_debt, cash_and_equivalents

**CF:** operating_cash_flow, capex, cfi, cff, delta_cash

### Key Config Files

- `config/field_aliases.json` — 150+ multilingual aliases per canonical field
- `config/ixbrl_concept_map.json` — iXBRL concepts → canonical fields
- `config/selection_rules.json` — filing selection rules by type/priority

## CLI Commands

| Command | Purpose |
|---|---|
| `elsian eval {TICKER}` | Evaluate ticker against expected.json |
| `elsian eval --all` | Evaluate all validated tickers |
| `elsian run {TICKER}` | Full pipeline: Convert→Extract→Evaluate→Assemble |
| `elsian discover {TICKER}` | Auto-generate case.json |
| `elsian acquire {TICKER}` | Download filings |
| `elsian curate {TICKER}` | Generate expected_draft.json from iXBRL |
| `elsian assemble {TICKER}` | Generate truth_pack.json |
| `elsian dashboard {TICKER}` | Visual extraction report |

## Rules for All Agents

1. Read VISION.md before anything else
2. Only work on Module 1
3. `eval --all` must pass at 100% after any change — regressions are bugs, not acceptable tradeoffs
4. Never reduce expected.json to pass tests (that's cheating — DEC-022)
5. Never use manual_overrides except as last resort with full documentation (DEC-024, max 5% per ticker)
6. Complete provenance on every FieldResult (extraction_method never empty)
7. New aliases must be case-scoped if format/market-specific — do not contaminate global aliases
8. Tests for every new feature (unit + integration)
9. One atomic commit per task
10. Report real metrics, not estimates — run pytest and eval --all, report exact numbers

## Known Vulnerabilities

Read `references/ELSIAN_INVEST_KNOWLEDGE_BASE.md` section 8 for details. Key risks:

- **V1 (HIGH):** Global alias changes cause cross-ticker regressions
- **V5 (HIGH):** Agents cheat (DEC-022 incident — agent reduced expected.json to fake 100%)
- **V2-V4 (MEDIUM):** Non-calendar fiscal years in iXBRL, TEP overrides, semi-manual curation for non-SEC

## Reference Files

For comprehensive project knowledge, read:
- `references/ELSIAN_INVEST_KNOWLEDGE_BASE.md` — Complete 500-line knowledge base covering all 14 sections: architecture, state, workflow, vulnerabilities, strengths, BACKLOG, decisions, repo structure, commands, agent rules
