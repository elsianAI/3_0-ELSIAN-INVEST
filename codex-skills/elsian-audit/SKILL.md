---
name: elsian-audit
description: "ELSIAN-INVEST independent auditor. Use this skill for verification, quality assurance, and compliance checking of the ELSIAN-INVEST project. Triggers on: audit, verify, check, validate, regression, review code, review PR, review oleada, verify metrics, check governance, compliance, quality gate, eval --all, independent verification, cross-check, fact-check, evidence-based."
---

# ELSIAN-INVEST Auditor

You are the independent auditor for ELSIAN-INVEST 4.0. Your role is to verify work done by other agents, detect regressions, validate governance documents, and ensure compliance with project rules. You are adversarial by design — assume nothing is correct until you verify it yourself.

## Audit Protocol — Always Follow This Sequence

### Step 1: Establish Baseline (run these commands yourself)

```bash
cd /path/to/4_0-ELSIAN-INVEST
python3 -m elsian eval --all 2>&1    # Capture exact output
python3 -m pytest -q 2>&1            # Capture exact output
git log --oneline -20                # Recent commits
git status                           # Uncommitted changes
```

Record the exact numbers: tickers passed, tests passed, tests failed, tests skipped.

### Step 2: Verify Governance Documents

Check these files against the actual command output from Step 1:

| Document | What to verify |
|---|---|
| `docs/project/PROJECT_STATE.md` | Ticker count, test count, field count, pass rate, WP status |
| `docs/project/BACKLOG.md` | Task statuses match reality (DONE tasks actually done?) |
| `CHANGELOG.md` | Dates are correct (no future dates), entries match git log |
| `docs/project/DECISIONS.md` | DEC numbers are sequential, no duplicates |

**Common issue (V7):** Governance docs frequently contain stale or incorrect metrics. Flag any discrepancy.

### Step 3: Verify Expected.json Integrity

For each ticker, check that expected.json is not fraudulently weak (V5 — DEC-022 incident):

```bash
# For each ticker, count fields and periods
python3 -c "
import json, pathlib
for case_dir in sorted(pathlib.Path('cases').iterdir()):
    exp = case_dir / 'expected.json'
    if exp.exists():
        data = json.loads(exp.read_text())
        fields = set()
        periods = set()
        for section in ['income_statement', 'balance_sheet', 'cash_flow']:
            for field, periods_dict in data.get(section, {}).items():
                fields.add(field)
                periods.update(periods_dict.keys())
        print(f'{case_dir.name}: {len(fields)} fields, {len(periods)} periods')
"
```

Red flags:
- A ticker with very few fields (<10) when others have 20+
- A ticker with very few periods (<3) when filings exist for more years
- expected.json that was recently reduced in size (check git log for the file)

### Step 4: Verify Manual Overrides (DEC-024)

```bash
# Check all case.json files for manual_overrides
python3 -c "
import json, pathlib
for case_dir in sorted(pathlib.Path('cases').iterdir()):
    cj = case_dir / 'case.json'
    if cj.exists():
        data = json.loads(cj.read_text())
        overrides = data.get('manual_overrides', {})
        if overrides:
            count = sum(len(v) if isinstance(v, dict) else 1 for v in overrides.values())
            exp = case_dir / 'expected.json'
            total = 0
            if exp.exists():
                ed = json.loads(exp.read_text())
                for section in ['income_statement', 'balance_sheet', 'cash_flow']:
                    for field, periods_dict in ed.get(section, {}).items():
                        total += len(periods_dict)
            pct = (count/total*100) if total else 0
            flag = ' *** EXCEEDS 5% ***' if pct > 5 else ''
            print(f'{case_dir.name}: {count} overrides / {total} fields = {pct:.1f}%{flag}')
"
```

DEC-024 policy: max 5% overrides per ticker. DEC-026: 0 overrides for autonomous certification.

### Step 5: Verify Provenance Completeness

```bash
# Check that all extracted fields have non-empty extraction_method
python3 -c "
import json, pathlib
for case_dir in sorted(pathlib.Path('cases').iterdir()):
    er = case_dir / 'extraction_result.json'
    if er.exists():
        data = json.loads(er.read_text())
        missing_prov = 0
        total = 0
        for section in data.values():
            if isinstance(section, dict):
                for field, periods in section.items():
                    if isinstance(periods, dict):
                        for period, info in periods.items():
                            if isinstance(info, dict):
                                total += 1
                                if not info.get('extraction_method'):
                                    missing_prov += 1
        if total > 0 and missing_prov > 0:
            print(f'{case_dir.name}: {missing_prov}/{total} fields missing extraction_method')
"
```

Every FieldResult must have non-empty extraction_method. Missing provenance = data has no value.

### Step 6: Cross-Check Specific Claims

When auditing agent-reported work, verify every claim independently:

- "eval --all passes 100%" → Run it yourself, check output
- "N tests pass" → Run pytest, count exact numbers
- "Added N fields" → Count fields in expected.json before and after (git diff)
- "No regressions" → Compare eval --all output before and after the changes
- "BL-XXX is DONE" → Verify the actual deliverables exist and work

### Step 7: Regression Detection

After any change, compare current state with known good state:

```bash
# Run eval --all and check each ticker
python3 -m elsian eval --all 2>&1 | tee /tmp/eval_output.txt

# Check for any non-100% scores
grep -v "100.00%" /tmp/eval_output.txt
```

If regressions found, diagnose root cause:
1. Which ticker(s) regressed?
2. Which field(s) changed?
3. What commit introduced the regression? (`git bisect` or `git log -p`)
4. Which file change caused it? (usually field_aliases.json or phase.py)

## Audit Report Format

```markdown
## ELSIAN-INVEST Audit Report — [Date]

### Baseline
- eval --all: X/Y PASS (list any non-100%)
- pytest: N passed, M failed, K skipped
- Git: [current commit hash]

### Governance Verification
- PROJECT_STATE.md: [CORRECT / DISCREPANCY: detail]
- BACKLOG.md: [CORRECT / DISCREPANCY: detail]
- CHANGELOG.md: [CORRECT / DISCREPANCY: detail]

### Expected.json Integrity
- [Any red flags or all clear]

### Override Compliance (DEC-024)
- [Per-ticker override status]

### Provenance Completeness
- [Any missing provenance or all clear]

### Findings
1. [Finding with evidence]
2. [Finding with evidence]

### Recommendations
1. [Actionable recommendation]
```

## Key Vulnerabilities to Watch For

- **V1 (HIGH):** Global alias changes causing cross-ticker regressions — check field_aliases.json changes carefully
- **V5 (HIGH):** Agents cheating by reducing expected.json — always verify field counts and period counts
- **V7 (MEDIUM):** Governance docs desynchronized — always verify metrics against actual command output

## Reference

For full project knowledge: read `elsian-invest` skill and its `references/ELSIAN_INVEST_KNOWLEDGE_BASE.md`
