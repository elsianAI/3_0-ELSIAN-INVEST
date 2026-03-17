---
name: elsian-develop
description: "ELSIAN-INVEST technical development agent. Use this skill for any coding task on the 4_0-ELSIAN-INVEST repository: adding new tickers, fixing extractors, writing tests, improving the pipeline, resolving regressions, implementing BACKLOG tasks. Triggers on: add ticker, fix extractor, write test, regression, BACKLOG task, BL-*, expected.json, extraction_result, html_tables.py, phase.py, field_aliases.json, ixbrl_extractor.py, pdf_tables.py, elsian eval, elsian run, pipeline fix, alias, scale cascade, sign enforcement, merge collision, provenance."
---

# ELSIAN-INVEST Developer Agent

You are the technical execution agent for ELSIAN-INVEST 4.0. You implement BACKLOG tasks, add tickers, fix extractors, write tests, and resolve regressions.

## Before Starting Any Work

1. Read the `elsian-invest` skill first if you haven't already — it has the full project context
2. Read `VISION.md` in the repo root
3. Read `docs/project/BACKLOG.md` — work on the first 3-5 TODO tasks, top to bottom
4. Run `python3 -m pytest -q` and `python3 -m elsian eval --all` to know the baseline

## Adding a New Ticker — Step by Step

```bash
# 1. Auto-discover (generates case.json)
python3 -m elsian discover {TICKER}

# 2. Download filings
python3 -m elsian acquire {TICKER}

# 3. Generate expected_draft.json (iXBRL-based for SEC, skeleton for others)
python3 -m elsian curate {TICKER}

# 4. Review and finalize expected.json
# - For SEC: draft is usually ~100% complete, verify values
# - For non-SEC: manually fill from filing PDFs with full provenance
# - NEVER reduce fields to fake 100% (DEC-022)

# 5. Run the pipeline
python3 -m elsian run {TICKER}

# 6. If score < 100%, diagnose and iterate:
python3 -m elsian eval {TICKER}      # See which fields fail
python3 -m elsian dashboard {TICKER}  # Detailed report

# 7. Register in tests/integration/test_regression.py VALIDATED_TICKERS
```

### Case Structure

```
cases/{TICKER}/
├── case.json              # Config (market, currency, CIK, fiscal_year_end_month, etc.)
├── expected.json          # Ground truth for evaluation
├── filings/               # Downloaded filings (.htm, .pdf)
│   ├── SRC_001_10-K_FY2024.htm
│   ├── SRC_001_10-K_FY2024.clean.md
│   └── ...
├── extraction_result.json # Pipeline output (generated)
└── truth_pack.json        # Final product (generated)
```

## Fixing Extractors — Diagnosis Protocol

When a ticker fails or has wrong values:

1. **Check extraction_result.json** — find the failing field, look at its provenance
2. **Check the clean.md** — find the filing section where the value should appear
3. **Identify which extractor is responsible** — table (html_tables.py), iXBRL (ixbrl_extractor.py), PDF (pdf_tables.py), narrative (narrative.py)
4. **Root cause analysis:**
   - Missing alias? → Add to `config/field_aliases.json` (CAREFUL: scope it!)
   - Wrong scale? → Check `elsian/normalize/scale.py` cascade
   - Wrong sign? → Check `elsian/normalize/signs.py` enforcement
   - Collision? → Check sort key in `elsian/extract/phase.py`
   - iXBRL mapping? → Check `config/ixbrl_concept_map.json`

### CRITICAL: Alias Changes Are High-Risk

Every modification to `config/field_aliases.json` or priority logic in `elsian/extract/phase.py` has HIGH probability of cross-ticker regression. This has happened multiple times:

- BL-042: income_tax sign change → TEP regression
- BL-043: D&A sub-component aliases → TEP + SOM regression
- BL-048: iXBRL sort key → SONO + ACLS regression

**Mitigation:** Always run `python3 -m elsian eval --all` after any alias or priority change. Fix regressions before committing.

**Best practice:** Use case-scoped aliases (`additive_fields` in case.json) instead of global aliases when the alias is specific to a format, market, or ticker.

## Extractor Architecture

### Collision Resolution (phase.py)

Extractors produce `FieldCandidate` objects. When multiple candidates exist for the same (field, period) pair, the winner is chosen by sort key:

```python
sort_key = (filing_rank, affinity, src_type_rank, semantic_rank)
# Lower = wins
# iXBRL: src_type_rank = -1, semantic_rank = -9999 (always wins unless was_rescaled)
# Table: src_type_rank = 0
# Narrative: src_type_rank = 1
```

### IxbrlExtractor Key Design

- `has_ixbrl(filepath)`: Reads first 8KB looking for `xmlns:ix=` or `<ix:header`
- Dominant scale normalization: detects majority monetary scale, converts outliers
- `was_rescaled=True` weakens sort key so table extractor can win with more precise values
- Calendar quarter detection from period end date (important for non-calendar fiscal years like SONO)

### Data Models

```python
@dataclass
class Provenance:
    source_filing: str       # "SRC_001_10-K_FY2024.htm"
    table_index: int | None  # Table number in document
    table_title: str         # "CONSOLIDATED STATEMENTS OF INCOME"
    row_label: str           # "Total net revenue"
    col_label: str           # "FY2024"
    row: int | None
    col: int | None
    raw_text: str            # "1,234,567" (original cell text)
    extraction_method: str   # "table" | "narrative" | "ixbrl" | "manual"

@dataclass
class FieldCandidate:
    canonical_name: str      # "revenue"
    value: float
    period: str              # "FY2024" | "Q3_2024"
    provenance: Provenance
    scale: str               # "raw" | "thousands" | "millions"
    confidence: str          # "high" | "medium" | "low"
    source_type: str         # "table" | "ixbrl" | "narrative"

@dataclass
class FieldResult:
    value: float
    provenance: Provenance
    scale: str
    confidence: str
```

## Writing Tests

- **Unit tests:** `tests/unit/` — test individual functions/classes in isolation
- **Integration tests:** `tests/integration/` — test pipeline stages end-to-end
- **Regression tests:** `tests/integration/test_regression.py` — VALIDATED_TICKERS list, each must eval 100%

Every new feature requires tests. Every new ticker gets added to VALIDATED_TICKERS.

## Commit Protocol

- One atomic commit per task
- Run `python3 -m pytest -q` and `python3 -m elsian eval --all` before committing
- If either fails, fix before committing
- Report exact metrics in commit message and in BACKLOG/CHANGELOG updates

## Reference

For full project knowledge: read `elsian-invest` skill and its `references/ELSIAN_INVEST_KNOWLEDGE_BASE.md`
