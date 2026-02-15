"""Engine entry point — orquestador principal de 3_0-ELSIAN-INVEST.

Implements §3.4 of PLAN COMPLETO.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from .config import load_config, validate_backends
from .state import load_state, get_next_step, init_state, mark_pipeline_status
from .router import execute_pipeline, execute_step, is_step_ready
from .dashboard import generate_dashboard, build_dashboard, render_dashboard, show_menu
from .changelog import append_entry
from .git_utils import stage_case, prepare_commit_message, commit


def main():
    parser = argparse.ArgumentParser(
        description="3_0-ELSIAN-INVEST Engine — Python orchestrator",
        prog="engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # pipeline
    p_pipeline = subparsers.add_parser("pipeline", help="Execute full pipeline for a ticker")
    p_pipeline.add_argument("ticker", type=str, help="Stock ticker (e.g., CRCT)")
    p_pipeline.add_argument("--date", type=str, default=None, help="Date (YYYY-MM-DD)")

    # continue
    p_continue = subparsers.add_parser("continue", help="Continue an incomplete pipeline")
    p_continue.add_argument("ticker", type=str)
    p_continue.add_argument("--date", type=str, default=None)

    # step
    p_step = subparsers.add_parser("step", help="Execute a single step")
    p_step.add_argument("ticker", type=str)
    p_step.add_argument("step_name", type=str)
    p_step.add_argument("--date", type=str, default=None)

    # rehacer
    p_rehacer = subparsers.add_parser("rehacer", help="Redo a step (resets and re-executes)")
    p_rehacer.add_argument("ticker", type=str)
    p_rehacer.add_argument("step_name", type=str)
    p_rehacer.add_argument("--date", type=str, default=None)

    # dashboard
    subparsers.add_parser("dashboard", help="Show global status dashboard")

    # interactive
    subparsers.add_parser("interactive", help="Interactive menu mode")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate case artifacts")
    p_validate.add_argument("ticker", type=str)
    p_validate.add_argument("--date", type=str, default=None)

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="Run monitoring update")
    p_monitor.add_argument("ticker", type=str)
    p_monitor.add_argument("--date", type=str, default=None)

    # scanner
    p_scanner = subparsers.add_parser("scanner", help="Run market scanner")
    p_scanner.add_argument("--date", type=str, default=None)

    # scout
    p_scout = subparsers.add_parser("scout", help="Run scout for new candidates")
    p_scout.add_argument("--type", type=str, default="Q", choices=["Q", "E"], help="Scout type (Q=quantitative, E=exploratory)")

    # outcome
    p_outcome = subparsers.add_parser("outcome", help="Record outcome for a case")
    p_outcome.add_argument("ticker", type=str)
    p_outcome.add_argument("--date", type=str, default=None)

    # evaluar
    p_evaluar = subparsers.add_parser("evaluar", help="Evaluate case quality with voting")
    p_evaluar.add_argument("ticker", type=str)
    p_evaluar.add_argument("--date", type=str, default=None)

    # benchmark
    p_benchmark = subparsers.add_parser("benchmark", help="Compare models on a case")
    p_benchmark.add_argument("ticker", type=str)
    p_benchmark.add_argument("--date", type=str, default=None)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Load config
    config_path = Path.cwd() / "engine_config.json"
    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"[engine] ERROR: Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Print binary status
    for name, binary in config.binaries.items():
        status = "✓" if binary.available else "✗"
        version = binary.version or "?"
        print(f"[engine] {status} {name}: {binary.path or 'NOT FOUND'} (v{version})")

    # Route to command
    if args.command == "dashboard":
        print(generate_dashboard(config.workspace))

    elif args.command == "interactive":
        _run_interactive(config)

    elif args.command == "pipeline":
        _cmd_pipeline(config, args)

    elif args.command == "continue":
        _cmd_continue(config, args)

    elif args.command == "step":
        _cmd_step(config, args)

    elif args.command == "rehacer":
        _cmd_rehacer(config, args)

    elif args.command == "validate":
        _cmd_validate(config, args)

    elif args.command in ("monitor", "scanner", "scout", "outcome", "evaluar", "benchmark"):
        _cmd_operation(config, args)


# ── Command implementations ────────────────────────────────

def _cmd_pipeline(config, args):
    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()

    case_dir = config.get_path("casos") / ticker / date_str
    case_dir.mkdir(parents=True, exist_ok=True)

    raw_dir = config.get_path("casos") / ticker / "_raw_filings"
    raw_dir.mkdir(parents=True, exist_ok=True)

    result = execute_pipeline(config, case_dir, ticker, date_str)

    stage_case(case_dir, config.workspace)
    msg = prepare_commit_message(ticker, "PIPELINE", "COMPLETO", date_str)
    commit(config.workspace, msg)

    print(f"\n[engine] Pipeline finished. Status: {result['state']['estado_pipeline']}")


def _cmd_continue(config, args):
    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()

    case_dir = config.get_path("casos") / ticker / date_str
    if not (case_dir / "_estado.json").exists():
        print(f"[engine] ERROR: No state file in {case_dir}", file=sys.stderr)
        sys.exit(1)

    next_step = get_next_step(case_dir)
    if next_step is None:
        print("[engine] Pipeline already complete!")
        return

    print(f"[engine] Continuing from: {next_step}")
    result = execute_step(config, case_dir, next_step, ticker)
    print(f"[engine] Step result: {'success' if result.get('success') else 'failed'}")


def _cmd_step(config, args):
    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()
    step_name = args.step_name.upper()

    case_dir = config.get_path("casos") / ticker / date_str
    if not (case_dir / "_estado.json").exists():
        init_state(case_dir, ticker, date_str)

    result = execute_step(config, case_dir, step_name, ticker)
    print(f"[engine] Step {step_name}: {'success' if result.get('success') else 'failed'}")


def _cmd_rehacer(config, args):
    """Reset step to PENDING and re-execute."""
    from .state import save_state

    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()
    step_name = args.step_name.upper()

    case_dir = config.get_path("casos") / ticker / date_str
    if not (case_dir / "_estado.json").exists():
        print(f"[engine] ERROR: No state file in {case_dir}", file=sys.stderr)
        sys.exit(1)

    state = load_state(case_dir)
    # Reset step
    if step_name in state.get("pipeline", {}):
        state["pipeline"][step_name] = {"estado": "PENDING", "artefacto": None, "artefacto_previo": None}
        state["estado_pipeline"] = "INCOMPLETO"
        save_state(case_dir, state)

    print(f"[engine] Redoing step: {step_name}")
    result = execute_step(config, case_dir, step_name, ticker)
    print(f"[engine] Step {step_name}: {'success' if result.get('success') else 'failed'}")


def _cmd_validate(config, args):
    from .validator import validate_file
    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()
    case_dir = config.get_path("casos") / ticker

    schemas_dir = config.get_path("schemas")
    if case_dir.exists():
        for sub in sorted(case_dir.iterdir()):
            if sub.is_dir() and sub.name != "_raw_filings":
                print(f"\n[validate] Case: {sub.name}")
                for f in sorted(sub.glob("*.json")):
                    if f.name.startswith("_"):
                        continue
                    is_valid, errors = validate_file(f, schemas_dir)
                    status = "✓" if is_valid else "✗"
                    print(f"  {status} {f.name}")
                    for err in errors[:3]:
                        print(f"      {err}")


def _cmd_operation(config, args):
    """Execute DAG-based operations (MONITOR, SCANNER, SCOUT, OUTCOME, EVALUAR, BENCHMARK)."""
    op = args.command.upper()
    dag = config.get_dag(op)
    if not dag:
        print(f"[engine] Operation {op} not found in pipeline_dag config")
        return

    print(f"[engine] Running operation: {op}")
    for step_def in dag:
        step = step_def.get("step", "?")
        step_type = step_def.get("type", "llm")
        print(f"[engine]   → {step} ({step_type})")

        if step_type == "python":
            from .router import _run_python_step
            # Build a temporary case_dir context
            ticker = getattr(args, "ticker", "SYSTEM")
            case_dir = config.get_path("tmp")
            result = _run_python_step(config, case_dir, step, ticker.upper() if isinstance(ticker, str) else "SYSTEM")
        else:
            ticker = getattr(args, "ticker", "SYSTEM")
            date_str = getattr(args, "date", None) or date.today().isoformat()
            model = getattr(args, "model", "Codex")
            case_dir = config.get_path("casos") / ticker.upper() / f"{date_str}_{model}"
            if not case_dir.exists():
                case_dir.mkdir(parents=True, exist_ok=True)
            result = execute_step(config, case_dir, step, ticker.upper())

        status = "✓" if result.get("success") else "✗"
        print(f"[engine]   {status} {step}: {result.get('error', 'OK')}")


def _run_interactive(config):
    """Interactive loop: show dashboard + menu."""
    while True:
        print(generate_dashboard(config.workspace))
        cmd = show_menu()
        if cmd is None or cmd == "exit":
            break
        elif cmd == "pipeline":
            ticker = input("Ticker: ").strip().upper()
            if ticker:
                from types import SimpleNamespace
                _cmd_pipeline(config, SimpleNamespace(
                    ticker=ticker,
                    date=date.today().isoformat(),
                    model="Codex",
                ))
        elif cmd == "continue":
            ticker = input("Ticker: ").strip().upper()
            if ticker:
                from types import SimpleNamespace
                _cmd_continue(config, SimpleNamespace(
                    ticker=ticker,
                    date=date.today().isoformat(),
                    model="Codex",
                ))
        elif cmd == "validate":
            ticker = input("Ticker: ").strip().upper()
            if ticker:
                from types import SimpleNamespace
                _cmd_validate(config, SimpleNamespace(
                    ticker=ticker,
                    date=date.today().isoformat(),
                ))
        else:
            print(f"[engine] Command '{cmd}' — use CLI for full options")


if __name__ == "__main__":
    main()
