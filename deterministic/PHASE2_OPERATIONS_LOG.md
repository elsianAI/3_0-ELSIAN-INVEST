# Deterministic Phase 2 - Operations Log

Purpose: single source of truth for the python-only iteration loop in Phase 2.
Scope: deterministic module only (`deterministic/`), no LLM production pipeline events.

## Entry Template

```md
## YYYY-MM-DD HH:MM - Iteration N - {CASE}
- Agent:
- Objective:
- Hypothesis:
- Files changed:
- Commands executed:
- Metrics before:
- Metrics after:
- Tests:
- Decision:
- Next step:
```

## 2026-02-27 12:53 - Iteration 0 - TZOO
- Agent: Codex + User
- Objective: restart TZOO from zero and validate clean bootstrap path.
- Hypothesis: recreating case and re-running acquire/extract/eval from scratch will expose true parser issues.
- Files changed: `deterministic/cases/TZOO/case.json`
- Commands executed:
  - `rm -rf deterministic/cases/TZOO`
  - recreate `case.json`
- Metrics before: N/A (case removed).
- Metrics after: case scaffold created, source_hint=`sec`.
- Tests: none.
- Decision: continue with acquire first, then extract, then eval.
- Next step: run `python3 -m deterministic.cli acquire TZOO`.

## 2026-02-27 13:04 - Iteration 1 - TZOO
- Agent: User
- Objective: validate filing acquisition coverage.
- Hypothesis: SEC fetcher should reach 100% of expected filings by policy (`expected=min(available,target)`).
- Files changed:
  - `deterministic/cases/TZOO/filings/`
  - `deterministic/cases/TZOO/filings_manifest.json`
- Commands executed:
  - `python3 -m deterministic.cli acquire TZOO`
- Metrics before: no filings downloaded.
- Metrics after:
  - filings_downloaded=28
  - filings_failed=0
  - filings_coverage_pct=100.0
  - annual=6/6, quarterly=12/12, earnings=10/10
- Tests: none.
- Decision: acquisition stage accepted.
- Next step: run `python3 -m deterministic.cli extract TZOO`.

## 2026-02-27 13:15 - Iteration 2 - TZOO
- Agent: Opus + User + Codex review
- Objective: create first ground truth (`expected.json`) for FY2024/FY2023 and measure baseline.
- Hypothesis: short, high-quality GT slice enables fast parser iteration before full GT expansion.
- Files changed:
  - `deterministic/cases/TZOO/expected.json`
- Commands executed:
  - `python3 -m deterministic.cli extract TZOO`
  - `python3 -m deterministic.cli eval TZOO`
- Metrics before: no expected file -> eval 0/0.
- Metrics after (baseline with first expected):
  - score=8.8% (3/34)
  - wrong=19
  - missed=12
  - extra=179
  - required_fields_coverage_pct=64.7
- Tests: existing suite (83) had been green previously.
- Decision: parser quality too low; prioritize table/alias/period fixes before widening GT coverage.
- Next step: patch extraction for percent rows, sparse table columns, unknown period handling, and alias fuzzy hardening.

## 2026-02-27 14:00 - Iteration 3 - TZOO
- Agent: Opus (implementation) + Codex (validation)
- Objective: apply first high-impact parser hardening patch.
- Hypothesis: better table parsing + safer aliasing + no unknown-period fallback will materially raise score.
- Files changed:
  - `deterministic/src/extract/tables.py`
  - `deterministic/src/pipeline.py`
  - `deterministic/src/normalize/aliases.py`
  - `deterministic/tests/unit/test_tables.py`
  - `deterministic/tests/unit/test_normalize.py`
- Commands executed:
  - `python3 -m unittest discover -s deterministic/tests -v`
  - `python3 -m deterministic.cli eval TZOO`
- Metrics before:
  - score=8.8% (3/34)
  - wrong=19
  - missed=12
  - extra=179
- Metrics after:
  - score=52.9% (18/34)
  - wrong=9
  - missed=7
  - extra=90
  - required_fields_coverage_pct=79.4
- Tests: 90 passed (up from 83).
- Decision: patch accepted; keep iterating in python-only mode.
- Next step: fix label collisions (`net_income` vs EPS rows, liability/equity row ambiguity, tax line disambiguation), then re-eval TZOO.

## 2026-02-27 16:30 - Iteration 4 - TZOO
- Agent: Copilot (Claude Opus 4.6)
- Objective: fix 5 semantic mapping errors (net_income↔EPS, total_liabilities↔equity, cash restricted, income_tax lines, shares_outstanding nominal vs weighted) and add collision resolution with max-value tiebreaker.
- Hypothesis: context-based rejection patterns in AliasResolver + row-level table filtering + priority-based collision resolution will eliminate the 9 wrong fields and recover the 7 missed fields.
- Files changed:
  - `deterministic/src/normalize/aliases.py` — added `_REJECT_PATTERNS`, `_PRIORITY_PATTERNS`, `_is_rejected()`, `label_priority()` methods; integrated rejection into `resolve()`.
  - `deterministic/src/extract/tables.py` — added row-level ignore for "total liabilities and stockholders' equity" rows.
  - `deterministic/src/pipeline.py` — added collision resolution: priority-based with max-absolute-value tiebreaker.
  - `deterministic/config/field_aliases.json` — added aliases for eps_basic/eps_diluted ("net income per share—basic/diluted"), shares_outstanding ("shares used in per share calculation", "weighted average common shares"), research_and_development ("product development"); removed "diluted shares outstanding" from shares_outstanding.
  - `deterministic/tests/unit/test_normalize.py` — 20 new tests for disambiguation rules.
  - `deterministic/tests/unit/test_tables.py` — 2 new tests for row filtering and EPS label preservation.
- Commands executed:
  - `python3 -m unittest discover -s deterministic/tests -v`
  - `python3 -m deterministic.cli eval TZOO`
- Metrics before:
  - score=52.9% (18/34)
  - wrong=9
  - missed=7
  - extra=90
  - filings_coverage_pct=100.0
  - required_fields_coverage_pct=79.4
- Metrics after:
  - score=100.0% (34/34)
  - wrong=0
  - missed=0
  - extra=106
  - filings_coverage_pct=100.0
  - required_fields_coverage_pct=100.0
- Tests: 110 passed, 0 failed (up from 90).
- Decision: accept — all 5 targeted errors fixed plus R&D alias gap closed; score jumped from 52.9% to 100%.
- Next step: evaluate GCT case; reduce `extra` field count via tighter alias boundaries.

## 2026-02-28 11:08 - Iteration 6 - TZOO
- Agent: Copilot
- Objective: Phase A — update expected.json with FY2019 restatement (8 fields, policy as_reported_unless_explicit_restatement) and FY2022 total_equity NCI-inclusive fix. Phase B — eliminate all 18 wrong values (target wrong=0) by fixing pipeline disambiguation (aliases, narrative context rejection, section-based priority, Unicode normalizer).
- Hypothesis: Updating expected.json with restated FY2019 values will resolve 5 wrongs (explicit restatement). Fixing pipeline label disambiguation (reject/priority patterns), Non-GAAP/comparative narrative context rejection, sub-section priority bonus, and Unicode apostrophe normalization will resolve the remaining 13 wrongs.
- Files changed:
  - `deterministic/cases/TZOO/expected.json` — FY2019: 7 restated fields (ingresos, cost_of_revenue, gross_profit, ebit, income_tax, research_and_development, cash_and_equivalents) with restatement metadata; FY2019/net_income reverted to 4155 (total unchanged by disc-ops reclassification); FY2022/total_equity changed to 8851 (NCI-inclusive, consistent with FY2024/FY2023); root-level restatement_policy added.
  - `deterministic/src/normalize/aliases.py` — added 3 reject patterns (net_income: "before income tax"; ebit: "non-gaap"; ingresos: "non-gaap"), 3 priority patterns (ebit: "^operating income"; net_income: exact match; income_tax: "(benefit)" suffix). Fixed Unicode normalizer: added U+2018/U+2019/U+201C/U+201D/U+2014/U+2013 to strip class.
  - `deterministic/src/extract/narrative.py` — added _NON_GAAP_CONTEXT and _COMPARATIVE_CONTEXT regex patterns; applied both as prefix checks in Pattern 1 and Pattern 3 extraction loops.
  - `deterministic/src/extract/tables.py` — extract_tables_from_clean_md now splits by ### sub-section headers within ## sections, producing section labels like "income_statement:operating_income_(loss)".
  - `deterministic/src/pipeline.py` — added _section_bonus() with _PRIMARY_IS_SECTION (+5) and _DEPRIORITIZED_SECTION (-5) regex patterns; collision resolution now uses label_priority + section_bonus.
  - `deterministic/tests/unit/test_normalize.py` — 3 new tests: reject "before income tax" for net_income, prefer "Operating income" for ebit priority, prefer exact "Net income" over qualified.
  - `deterministic/tests/unit/test_narrative.py` — 2 new tests: block Non-GAAP narrative context, block comparative narrative context.
- Commands executed:
  - `python3 -m unittest discover -s deterministic/tests -v`
  - `python3 -m deterministic.cli eval TZOO`
- Metrics before:
  - score=100.0% (34/34) [previous scope, iteration 5]
  - After expected.json expanded to 270 fields (18 periods): score=31.9% (86/270), wrong=18, missed=166, extra=36
  - filings_coverage_pct=100.0
  - required_fields_coverage_pct=100.0 → 31.9%
- Metrics after:
  - score=37.0% (100/270)
  - wrong=0
  - missed=170
  - extra=36
  - filings_coverage_pct=100.0
  - required_fields_coverage_pct=37.0
- Tests: 115 passed, 0 failed (up from 110).
- Decision: accept — wrong dropped from 18 to 0 (target achieved). Score rose from 31.9% to 37.0% (+14 net matched). 170 missed fields remain (mostly quarterly periods from 10-Q multi-header table parsing not yet implemented). 5 new unit tests added.
- Next step: fix 10-Q multi-header table parsing to recover quarterly fields (target: reduce missed from 170); evaluate GCT case.

