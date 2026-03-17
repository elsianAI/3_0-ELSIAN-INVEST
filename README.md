# 3_0-ELSIAN-INVEST

**Python orchestrator for multi-backend LLM investment analysis pipeline.**

Zero-token orchestration layer that dispatches analytical work to LLM backends (Codex CLI, Gemini CLI, Claude Code CLI) via subprocess. Built for the ELSIAN INVEST investment research system.

---

## Quick Start

### Prerequisites

- Python 3.9+ (tested on 3.9.6)
- At least one LLM CLI backend:
  - **Codex**: `brew install codex` or download from [Codex.app](https://codex.app)
  - **Gemini**: `brew install gemini-cli` (or equivalent for your platform)
  - **Claude Code**: `npm install -g @anthropic-ai/claude-code`

### Installation

```bash
# Clone/navigate to project
cd 3_0-ELSIAN-INVEST

# Install Python dependencies
pip install -r requirements.txt

# Verify setup
python3 -m engine --help
```

### Basic Usage

```bash
# Show dashboard (scan all cases)
python3 -m engine dashboard

# Show arbitro decisions summary
python3 -m engine decisions              # compact table
python3 -m engine decisions -v           # + sizing, model, agent confidences
python3 -m engine decisions -vv          # + racional, riesgos, next steps
python3 -m engine decisions ACVA         # filter by ticker
python3 -m engine decisions ACVA -vv     # full detail for one ticker

# Run full pipeline for a ticker
python3 -m engine pipeline AAPL --date 2026-02-15
# Execute a single step
python3 -m engine step AAPL SOURCES --date 2026-02-15

# Continue an incomplete pipeline
python3 -m engine continue AAPL --date 2026-02-15

# Model defaults (persistentes)
python3 -m engine defaults show
python3 -m engine defaults set --pipeline-models "gpt-5.4,claude-opus-4.6,gemini-3.1-pro-preview" --fusion-model claude-opus-4.6 --single-model gpt-5.4
python3 -m engine defaults step set --step BULL --models gpt-5.4,claude-opus-4.6 --fusion-model claude-sonnet-4.6
python3 -m engine defaults edit   # asistente interactivo TTY

# Validate artifacts in a case
python3 -m engine validate AAPL --date 2026-02-15

# Use alternate config file
python3 -m engine --config /path/to/engine_config.json defaults show
```

# Usuario Codex
```bash
cat ~/.codex/auth.json | jq -r '.tokens.id_token | split(".")[1] | @base64d | fromjson | "Usuario: \(.email)"'
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              python -m engine [cmd]                  │
│              (0 tokens consumed)                     │
└────────────────────┬────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │   engine/engine.py     │  CLI entry point
         │   engine/router.py     │  Pipeline DAG + flow control
         │   engine/state.py      │  Per-case _estado.json
         └───────────┬────────────┘
                     │
         ┌───────────┴────────────┐
         │  engine/dispatcher.py   │  Backend dispatch
         └───────────┬────────────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼───┐      ┌────▼────┐     ┌────▼────┐
│ Codex │      │ Gemini  │     │ Claude  │
│  CLI  │      │   CLI   │     │Code CLI │
└───────┘      └─────────┘     └─────────┘
  (subprocess)   (subprocess)    (subprocess)
```

### Core Modules (13)

| Module | Purpose | Tokens |
|--------|---------|--------|
| `config.py` | Load `engine_config.json`, resolve binaries, validate versions | 0 |
| `state.py` | Read/write per-case `_estado.json` (pipeline state machine) | 0 |
| `dashboard.py` | Generate 0-token dashboard (scan `casos/` directory) | 0 |
| `validator.py` | JSON schema validation against `_schemas/` | 0 |
| `prompt_builder.py` | Assemble prompts (instructions + schemas + artifacts) | 0 |
| `dispatcher.py` | Dispatch to LLM backends, multi-dispatch + fusion | 0 |
| `router.py` | Pipeline DAG, dependency resolution, step execution | 0 |
| `engine.py` | CLI entry point (argparse) | 0 |
| `changelog.py` | Append entries to `CHANGELOG.md` | 0 |
| `git_utils.py` | Stage cases, prepare commit messages (no push) | 0 |
| `backends/base.py` | ABC for LLM backends (`DispatchResult` dataclass) | 0 |
| `backends/codex.py` | Codex backend (`--output-last-message` for robust capture) | 0 |
| `backends/gemini.py` | Gemini backend (JSON extraction from stdout) | 0 |
| `backends/claude.py` | Claude Code backend (JSON envelope parsing) | 0 |

### Pipeline Steps

**Main Pipeline:**
`SOURCES` → `TRUTH_PACK` → `IMPLIED` → (`CATALYST` ∥ `FORENSIC`) → `BULL` → `RED_TEAM` → `ARBITRO`

**Sub-steps:**

- **SOURCES**: `PREFETCH` (runs sec_fetcher, market_data, transcript_finder in parallel) → `SOURCES_COMPILER`
- **TRUTH_PACK**: `TP_EXTRACTOR_FILING` (per-filing LLM extraction) → `TP_EXTRACTOR_MERGER` → `TP_CALCULATOR` → `TP_VALIDATOR`
- **CATALYST**: `CATALYST_DETECTION` → `CATALYST_SCORING`
- **FORENSIC**: `FORENSIC_DETECTION` → `FORENSIC_SCORING`

## CLI Commands

Principales comandos:

- `python3 -m engine dashboard`
- `python3 -m engine decisions [TICKER] [-v|-vv]`
- `python3 -m engine pipeline TICKER --date YYYY-MM-DD`
- `python3 -m engine continue TICKER --date YYYY-MM-DD`
- `python3 -m engine step TICKER STEP_NAME --date YYYY-MM-DD`
- `python3 -m engine rehacer TICKER STEP_NAME --date YYYY-MM-DD`
- `python3 -m engine monitor|scanner|scout|outcome|evaluar|benchmark|validate`
- `python3 -m engine defaults show`
- `python3 -m engine defaults set --pipeline-models ...`
- `python3 -m engine defaults step set --step ...`
- `python3 -m engine defaults edit`

---

## Configuration

### `engine_config.json` (v2)

```json
{
  "version": "2.0.0",
  "model_catalog": {
    "gpt-5.4": { "...": "..." },
    "claude-opus-4.6": { "...": "..." },
    "gemini-3.1-pro-preview": { "...": "..." }
  },
  "pipeline_models": [
    "gpt-5.4",
    "claude-opus-4.6",
    "gemini-3.1-pro-preview"
  ],
  "fusion_model": "claude-opus-4.6",
  "default_single_model": "gpt-5.4",
  "step_overrides": {
    "TP_EXTRACTOR_FILING": {
      "models": ["gpt-5.4"]
    },
    "BULL": {
      "fusion_model": "claude-opus-4.6"
    }
  },
  "execution": {
    "max_parallel_filings": 4,
    "max_parallel_backends": 3,
    "fail_fast": true
  }
}
```

- **Modelo canónico**: ahora usa `model_profile` (ej. `claude-opus-4.6`) y resuelve transporte (`codex` / `claude` / `gemini`).
- **GPT-5.4 en Codex**: verificado en local con `codex-cli 0.111.0`; el `model_id` soportado por la cuenta ChatGPT es `gpt-5.4`.
- **Defaults persistentes**:
  - `pipeline_models`: perfiles para pasos multi-modelo por defecto.
  - `fusion_model`: fusión por defecto para multi-modelo.
  - `default_single_model`: perfil por defecto para pasos single.
  - `step_overrides`: overrides persistentes por step (modelos/fusión).
- **Comandos de defaults**:
  - `defaults show`: visualizar estado actual.
  - `defaults set`: actualizar valores globales.
  - `defaults step set`: actualizar override de un step.
  - `defaults edit`: editar de forma guiada (interactivo).
- **Flag global**:
  - `--config /ruta/engine_config.json` permite apuntar a otra configuración antes de cualquier subcomando.
- **Binary resolution**: `binary` → `binary_fallback` → unavailable.
- **Parallel filings**: `TP_EXTRACTOR_FILING` with DAG type `"llm_per_filing"` processes each filing concurrently
- **Quality voting (v1)**: deterministic, report-only metrics are documented in `_docs/QUALITY_VOTING.md`

---

## Project Structure

```
3_0-ELSIAN-INVEST/
├── engine/                    # Core orchestrator (13 modules)
│   ├── __init__.py
│   ├── __main__.py           # python -m engine entry
│   ├── config.py             # Load engine_config.json
│   ├── state.py              # _estado.json per case
│   ├── dashboard.py          # 0-token dashboard
│   ├── validator.py          # Schema validation
│   ├── prompt_builder.py     # Prompt assembly
│   ├── dispatcher.py         # Backend dispatch
│   ├── router.py             # Pipeline DAG
│   ├── engine.py             # CLI (argparse)
│   ├── changelog.py          # CHANGELOG.md writer
│   ├── git_utils.py          # Git staging (no push)
│   └── backends/
│       ├── __init__.py
│       ├── base.py           # LLMBackend ABC
│       ├── codex.py
│       ├── gemini.py
│       └── claude.py
├── scripts/
│   └── runners/              # Python-only runners (0 LLM)
│       ├── market_data_v1_runner.py
│       ├── sec_fetcher_v2_runner.py
│       ├── sources_compiler_runner.py
│       ├── transcript_finder_v2_runner.py
│       ├── tp_calculator.py
│       ├── tp_validator.py
│       └── tp_extractor_merger.py
├── _schemas/                 # JSON schemas (24)
│   ├── artefactos/
│   ├── benchmark/
│   ├── estado/
│   ├── evaluacion/
│   ├── monitoring/
│   ├── payloads/
│   ├── remediation/
│   └── scanner/
├── _instrucciones/           # Agent instructions (30)
│   └── activas/
├── casos/                    # Per-ticker case directories
│   └── {TICKER}/
│       ├── _raw_filings/     # Cached SEC filings
│       └── {DATE}_{MODEL}/   # Pipeline execution
│           ├── _estado.json  # State machine
│           └── *.json        # Artifacts
├── tmp/                      # Temp files (gitignored)
├── engine_config.json        # Main configuration
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

---

## State Machine

Each case has a `_estado.json` file tracking pipeline progress:

```json
{
  "caso_id": "CASE_20260215_AAPL_Codex",
  "ticker": "AAPL",
  "fecha": "2026-02-15",
  "modelo": "Codex",
  "estado_pipeline": "IN_PROGRESS",
  "pipeline": {
    "SOURCES": {"estado": "DONE", "modelo": "python"},
    "TRUTH_PACK": {"estado": "IN_PROGRESS"},
    "IMPLIED": {"estado": "PENDING"},
    ...
  }
}
```

- **Main states**: `PENDING`, `IN_PROGRESS`, `DONE`
- **Sub-steps** propagate completion to parent steps
- Atomic writes via tempfile + rename

---

## Development

### Run Tests

```bash
python3 tmp/_test_engine.py
```

Tests cover:
- Config loading (3 backends)
- State init + roundtrip
- Validator (with/without jsonschema)
- Dashboard generation
- Changelog append/read
- Router DAG dependencies
- TP Calculator (deterministic formulas)
- TP Validator (7 quality gates)
- TP Extractor Merger (multi-filing fusion)
- Backend instantiation
- CLI help

### Add a New Backend

1. Create `engine/backends/my_backend.py`:
   ```python
   from .base import LLMBackend, DispatchResult
   
   class MyBackend(LLMBackend):
       @property
       def name(self) -> str:
           return "my_backend"
       
       def dispatch(self, prompt, output_schema=None, cwd=None, timeout=600):
           # Your implementation
           return DispatchResult(...)
   ```

2. Register in `engine/backends/__init__.py`
3. Add to `engine_config.json` binaries + step_routing
4. Add to `BACKEND_CLASSES` in `engine/dispatcher.py`

### Add a New Pipeline Step

1. Add instruction file: `_instrucciones/activas/instrucciones_{step}_V1.md`
2. Add output schema: `_schemas/artefactos/{Schema}_v1.json`
3. Update `PIPELINE_STEPS` in `engine/state.py`
4. Update `PIPELINE_DAG` in `engine/router.py`
5. Add routing in `engine_config.json` `step_routing`
6. Add to `INSTRUCTION_MAP` in `engine/prompt_builder.py`

---

## Backends Status

Tested on macOS with:
- ✅ **Codex** v0.101.0 (`/opt/homebrew/bin/codex`)
- ✅ **Gemini** v0.28.2 (`/opt/homebrew/bin/gemini`)
- ✅ **Claude Code** v2.1.42 (`~/.local/bin/claude`)

All 3 backends instantiate and pass smoke tests.

---

## Compatibility

- **Python**: 3.9.6+ (uses `from __future__ import annotations` for type hints)
- **OS**: macOS (primary), Linux (should work), Windows (untested)
- **Python 3.10+**: Native union types `X | None` work without `__future__` import

---

## Known Issues

1. **`jsonschema` not installed** — validation gracefully skips. Install with `pip install jsonschema`
2. **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code` required for claude backend

---

## License

Internal project. Not for public distribution.

---

## Version

**v1.0.0** — Initial release (2026-02-15)

- 13 engine modules functional
- 3 LLM backends (Codex, Gemini, Claude Code)
- 24 schemas, 30 instructions, 8 runners
- CLI with 6 commands (incl. `decisions` with 3 verbosity levels)
- 10/11 functional tests passing
