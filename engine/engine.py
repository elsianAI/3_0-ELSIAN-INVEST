"""Engine entry point — orquestador principal de 3_0-ELSIAN-INVEST.

Implements §3.4 of PLAN COMPLETO.
"""

from __future__ import annotations

import argparse
import textwrap
import sys
from datetime import date
from pathlib import Path

from .config import EngineConfig, load_config
from .dispatcher import check_model_profiles_availability, preflight_backends
from .state import (
    load_state,
    get_next_step,
    init_state,
    mark_pipeline_status,
    mark_step_done,
    mark_step_failed,
    resolve_empresa_hints,
    persist_empresa_hints,
)
from .router import execute_pipeline, execute_step, is_step_ready, get_parallel_group
from .dashboard import generate_dashboard, generate_decisions, build_dashboard, render_dashboard, show_menu
from .changelog import append_entry
from .git_utils import stage_case, prepare_commit_message, commit
from .diagnostics import format_failure_block, save_failure_artifact
from .model_defaults import (
    collect_persistent_defaults_snapshot,
    build_global_updates,
    coerce_profile_or_empty,
    format_defaults_snapshot,
    build_step_override_updates,
    ensure_v2,
    load_config_raw,
    make_config_diff,
    resolve_model_list,
    write_engine_config_atomic,
)


def _add_empresa_hint_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--exchange",
        type=str,
        default="",
        help="Exchange code (LSE, SEHK, ASX, TSX, EPA...)",
    )
    parser.add_argument(
        "--country",
        type=str,
        default="",
        help="ISO country code (GB, HK, AU...)",
    )
    parser.add_argument(
        "--web-ir",
        type=str,
        default="",
        help="Investor Relations base URL",
    )


def main():
    parser = argparse.ArgumentParser(
        description="3_0-ELSIAN-INVEST Engine — Python orchestrator",
        prog="engine",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=textwrap.dedent(
            """
Examples:
  python3 -m engine pipeline ACVA --date 2026-02-21
  python3 -m engine continue ACVA --date 2026-02-21
  python3 -m engine defaults show
  python3 -m engine defaults set --pipeline-models 1,3 --fusion-model claude-opus-4.6
  python3 -m engine defaults step set --step BULL --models all --fusion-model claude-sonnet-4.6
  python3 -m engine defaults edit
  python3 -m engine dashboard
            """
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.cwd() / "engine_config.json",
        help="Path to engine_config.json",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        title="comandos",
        description="Comandos disponibles",
        metavar="COMMAND",
        help="Comando a ejecutar",
    )

    # pipeline
    p_pipeline = subparsers.add_parser(
        "pipeline",
        help="Ejecuta el pipeline completo para un ticker.",
        description="Ejecuta el pipeline completo para un ticker específico.",
    )
    p_pipeline.add_argument("ticker", type=str, help="Stock ticker (e.g., CRCT)")
    p_pipeline.add_argument("--date", type=str, default=None, help="Date (YYYY-MM-DD)")
    p_pipeline.add_argument(
        "--no-plan",
        action="store_true",
        help="Skip interactive model plan (use defaults)",
    )
    p_pipeline.add_argument(
        "--save-raw-on-failure",
        action="store_true",
        help="Persist full failure context to _diagnostics/failures on error",
    )
    _add_empresa_hint_args(p_pipeline)

    # continue
    p_continue = subparsers.add_parser(
        "continue",
        help="Reanuda un pipeline incompleto.",
        description="Continúa un pipeline desde el último paso pendiente.",
    )
    p_continue.add_argument("ticker", type=str)
    p_continue.add_argument("--date", type=str, default=None)
    p_continue.add_argument(
        "--no-plan",
        action="store_true",
        help="Skip interactive model plan (use defaults)",
    )
    p_continue.add_argument(
        "--save-raw-on-failure",
        action="store_true",
        help="Persist full failure context to _diagnostics/failures on error",
    )
    _add_empresa_hint_args(p_continue)

    # step
    p_step = subparsers.add_parser(
        "step",
        help="Ejecuta un único paso (modo avanzado).",
        description="Ejecuta exactamente un paso del pipeline para diagnóstico o reintentos puntuales.",
    )
    p_step.add_argument("ticker", type=str)
    p_step.add_argument("step_name", type=str)
    p_step.add_argument("--date", type=str, default=None)
    _add_empresa_hint_args(p_step)

    # rehacer
    p_rehacer = subparsers.add_parser(
        "rehacer",
        help="Rehace un paso existente (resetea estado y vuelve a ejecutar).",
        description="Útil para reintentos de paso cuando se conoce el fallo concreto.",
    )
    p_rehacer.add_argument("ticker", type=str)
    p_rehacer.add_argument("step_name", type=str)
    p_rehacer.add_argument("--date", type=str, default=None)
    _add_empresa_hint_args(p_rehacer)

    # dashboard
    p_dashboard = subparsers.add_parser(
        "dashboard",
        help="Resumen global de estado de casos.",
        description="Genera el dashboard de estado global sin consumir tokens.",
    )
    p_dashboard.add_argument(
        "--quality",
        action="store_true",
        help="Include deterministic quality-voting metrics",
    )

    # decisions
    p_decisions = subparsers.add_parser(
        "decisions",
        help="Resumen de decisiones de arbitraje.",
        description="Muestra las decisiones agregadas; añade -v o -vv para más detalle.",
    )
    p_decisions.add_argument("ticker", nargs="?", default=None, help="Filter by ticker (optional)")
    p_decisions.add_argument("-v", "--verbose", action="count", default=0,
                             help="Verbosity: -v = detailed, -vv = full DecisionPacket")

    # defaults
    p_defaults = subparsers.add_parser(
        "defaults",
        help="Gestiona defaults persistentes de modelos.",
        description="Gestiona los defaults de ejecución (pipeline/models/fusión) persistentes en engine_config.json.",
    )
    defaults_sub = p_defaults.add_subparsers(
        dest="defaults_command",
        required=True,
        title="acción",
        description="Sub-comandos para defaults",
        metavar="ACTION",
    )

    defaults_show = defaults_sub.add_parser(
        "show",
        help="Muestra defaults persistentes actuales.",
        description="Muestra los valores guardados en engine_config.json para el plan por defecto.",
    )
    defaults_show.add_argument(
        "--check",
        action="store_true",
        help="Chequea disponibilidad de perfiles antes de mostrarla.",
    )

    defaults_set = defaults_sub.add_parser(
        "set",
        help="Actualiza defaults globales (pipeline_models, fusion_model, single-model).",
        description="Actualiza defaults persistentes globales (sin tocar model_catalog).",
    )
    defaults_set.add_argument(
        "--pipeline-models",
        dest="pipeline_models",
        help="Comma/range/list of model profiles (e.g. 1,3,gemini-3-pro)",
    )
    defaults_set.add_argument(
        "--fusion-model",
        dest="fusion_model",
        help="Global fusion model profile",
    )
    defaults_set.add_argument(
        "--single-model",
        dest="single_model",
        help="Default single-step model profile",
    )
    defaults_set.add_argument(
        "--dry-run",
        action="store_true",
        help="Show diff and skip writing",
    )
    defaults_set.add_argument("--yes", action="store_true", help="Skip confirmation")
    defaults_set.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup creation",
    )

    defaults_step = defaults_sub.add_parser(
        "step",
        help="Actualiza overrides de un paso concreto.",
        description="Actualiza overrides persistentes para un step concreto del pipeline.",
    )
    defaults_step_sub = defaults_step.add_subparsers(dest="action", required=True)
    defaults_step_set = defaults_step_sub.add_parser(
        "set",
        help="Actualiza defaults persistentes de un paso.",
        description="Actualiza `models` y/o `fusion_model` para un paso llm.",
    )
    defaults_step_set.add_argument("--step", required=True, help="Step name (e.g. BULL)")
    defaults_step_set.add_argument(
        "--models",
        dest="models",
        help="Comma/range/list of model profiles",
    )
    defaults_step_set.add_argument(
        "--fusion-model",
        dest="fusion_model",
        help="Fusion model for multi step",
    )
    defaults_step_set.add_argument(
        "--reset",
        action="store_true",
        help="Clear all overrides for this step",
    )
    defaults_step_set.add_argument(
        "--dry-run",
        action="store_true",
        help="Show diff and skip writing",
    )
    defaults_step_set.add_argument("--yes", action="store_true", help="Skip confirmation")
    defaults_step_set.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup creation",
    )

    defaults_edit = defaults_sub.add_parser(
        "edit",
        help="Abre un asistente interactivo para editar defaults persistentes.",
        description="Wizard para editar defaults de pipeline y steps con confirmación y diff final.",
    )
    defaults_edit.add_argument("--dry-run", action="store_true", help="Show diff and skip writing")
    defaults_edit.add_argument("--yes", action="store_true", help="Skip confirmation")
    defaults_edit.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup creation",
    )

    # interactive
    subparsers.add_parser(
        "interactive",
        help="Abre el menú interactivo de ejecución.",
        description="Menú interactivo para operaciones guiadas de casos y pipeline.",
    )

    # validate
    p_validate = subparsers.add_parser(
        "validate",
        help="Valida artefactos de un caso tras ejecución.",
        description="Revisar estructura y consistencia de artefactos generados para un ticker.",
    )
    p_validate.add_argument("ticker", type=str)
    p_validate.add_argument("--date", type=str, default=None)

    # monitor
    p_monitor = subparsers.add_parser(
        "monitor",
        help="Ejecuta monitor de mercado.",
        description="Recupera señales de monitor para el ticker solicitado.",
    )
    p_monitor.add_argument("ticker", type=str)
    p_monitor.add_argument("--date", type=str, default=None)

    # scanner
    p_scanner = subparsers.add_parser(
        "scanner",
        help="Ejecuta scanner de candidatos.",
        description="Escaneo de nuevos candidatos/alertas de mercado.",
    )
    p_scanner.add_argument("--date", type=str, default=None)

    # scout
    p_scout = subparsers.add_parser(
        "scout",
        help="Ejecuta scout de candidatos (Q/E).",
        description="Busca señales en transcripciones y eventos para generar candidatos.",
    )
    p_scout.add_argument("--type", type=str, default="Q", choices=["Q", "E"], help="Scout type (Q=quantitative, E=exploratory)")

    # outcome
    p_outcome = subparsers.add_parser(
        "outcome",
        help="Registra outcome manual de un caso.",
        description="Añade un outcome de usuario para seguimiento interno.",
    )
    p_outcome.add_argument("ticker", type=str)
    p_outcome.add_argument("--date", type=str, default=None)

    # evaluar
    p_evaluar = subparsers.add_parser(
        "evaluar",
        help="Evalúa calidad de caso con sistema de votos.",
        description="Lanza evaluación automática de calidad (puntuaciones y bloqueos).",
    )
    p_evaluar.add_argument("ticker", type=str)
    p_evaluar.add_argument("--date", type=str, default=None)

    # benchmark
    p_benchmark = subparsers.add_parser(
        "benchmark",
        help="Compara modelos sobre un caso.",
        description="Ejecución comparativa para caracterizar comportamiento de modelos.",
    )
    p_benchmark.add_argument("ticker", type=str)
    p_benchmark.add_argument("--date", type=str, default=None)

    raw_argv = list(sys.argv[1:])
    parsed_argv: list[str] = []
    config_path: Path | None = None
    i = 0
    while i < len(raw_argv):
        arg = raw_argv[i]
        if arg == "--config":
            if i + 1 >= len(raw_argv):
                print("[engine] ERROR: --config requiere una ruta", file=sys.stderr)
                sys.exit(1)
            config_path = Path(raw_argv[i + 1])
            i += 2
            continue
        if arg.startswith("--config="):
            config_path = Path(arg.split("=", 1)[1])
            i += 1
            continue
        parsed_argv.append(arg)
        i += 1

    args = parser.parse_args(parsed_argv)

    if not args.command:
        parser.print_help()
        return

    # Load config
    if config_path is None:
        config_path = args.config
    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"[engine] ERROR: Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize prompt builder with truncation limits from config
    from .prompt_builder import set_truncation_limits
    set_truncation_limits(config.raw.get("truncation_limits"))

    # Print binary status
    for name, binary in config.binaries.items():
        status = "✓" if binary.available else "✗"
        version = binary.version or "?"
        print(f"[engine] {status} {name}: {binary.path or 'NOT FOUND'} (v{version})")

    # Route to command
    if args.command == "dashboard":
        print(
            generate_dashboard(
                config.workspace,
                include_quality=args.quality,
                quality_config=config.raw.get("quality_voting", {}),
            )
        )

    elif args.command == "decisions":
        ticker = args.ticker.upper() if args.ticker else None
        print(generate_decisions(config.workspace, verbosity=args.verbose, filter_ticker=ticker))

    elif args.command == "defaults":
        _cmd_defaults(config, args)

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


def _run_model_plan_assistant(
    config: EngineConfig,
    *,
    no_plan: bool = False,
    step_names: list[str] | None = None,
) -> EngineConfig:
    """Ask the user to confirm or override model-profile plan before execution."""
    if not config.is_v2:
        return config
    if no_plan or not sys.stdin.isatty():
        return config

    from .model_plan import (
        build_effective_model_set,
        parse_step_overrides,
        render_plan_table,
        resolve_model_list,
    )

    plan = config.snapshot_pipeline_model_plan(step_names)
    if not plan:
        return config

    # Initial availability check for the baseline plan.
    checked: set[str] = build_effective_model_set(plan)
    availability = check_model_profiles_availability(config, checked)
    profile_catalog = sorted(config.model_catalog.keys())
    profile_set = set(profile_catalog)

    def _parse_model_selection(raw: str) -> tuple[list[str] | None, str | None]:
        """Parse model tokens (indices, ranges or profile names)."""
        raw = raw.strip()
        if not raw:
            return None, None

        resolved, errors = resolve_model_list(raw, profile_catalog)
        if errors:
            return None, ", ".join(errors)
        return resolved, None

    def _parse_step_indexes(
        raw: str,
        max_count: int = -1,
    ) -> tuple[list[int] | None, str | None]:
        """Parse step selectors from assistant input."""
        raw = raw.strip()
        if max_count < 0:
            max_count = len(plan)
        if not raw:
            return None, None
        if raw == "*":
            return list(range(1, max_count + 1)), None
        selected: list[int] = []
        seen: set[int] = set()
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                parts = token.split("-", 1)
                if len(parts) != 2:
                    return None, f"Rango inválido: {token}"
                a_raw, b_raw = parts
                if not a_raw.isdigit() or not b_raw.isdigit():
                    return None, f"Rango inválido: {token}"
                a, b = int(a_raw), int(b_raw)
                if a < 1 or b < 1 or a > max_count or b > max_count or a > b:
                    return None, f"Rango inválido: {token}"
                for i in range(a, b + 1):
                    if i not in seen:
                        selected.append(i)
                        seen.add(i)
                continue

            if not token.isdigit():
                return None, f"Paso inválido: {token}"
            idx = int(token)
            if idx < 1 or idx > max_count:
                return None, f"Paso inválido: {idx}"
            if idx not in seen:
                selected.append(idx)
                seen.add(idx)
        return selected, None

    def _resolve_profile_choice(raw: str) -> tuple[str | None, str | None]:
        """Resolve profile index or profile name."""
        token = raw.strip()
        if not token:
            return None, "vacío"
        if token.isdigit():
            idx = int(token)
            if idx < 1 or idx > len(profile_catalog):
                return None, f"Índice inválido de fusión: {idx}"
            return profile_catalog[idx - 1], None
        if token not in profile_set:
            return None, f"Perfil desconocido: {token}"
        return token, None

    while True:
        print("\n=== Plan de modelos para esta corrida ===")
        print(render_plan_table(plan, availability))

        unavailable = [name for name, (ok, _) in availability.items() if not ok]
        if unavailable:
            print(f"\n⚠  Modelos no disponibles: {', '.join(unavailable)}")

        warnings = []
        for entry in plan:
            if (
                entry.is_multi
                and entry.min_backends is not None
                and len(entry.models) < entry.min_backends
            ):
                warnings.append(
                    f"{entry.step_name}: mínimo {entry.min_backends} modelos (configurado {len(entry.models)})"
                )
        if warnings:
            print("\n⚠ Avisos de configuración:")
            for warning in warnings:
                print(f"  - {warning}")

        print("\n[Enter]=Confirmar | [m]=Modificar plan (modo asistido) | [t]=Modificar por texto | [q]=Salir")
        choice = input("> ").strip().lower()

        if choice in ("", "y", "s", "ok", "sí"):
            return config
        if choice in ("q", "quit", "exit"):
            print("[engine] Ejecución cancelada por el usuario.")
            sys.exit(0)

        if choice not in ("m", "t"):
            print("Entrada no válida. Usa Enter, m, t o q.")
            continue

        if choice == "m":
            editable_steps = []
            selectable_idx = 1
            for plan_idx, entry in enumerate(plan, start=1):
                if entry.step_type == "python":
                    continue
                editable_steps.append((selectable_idx, plan_idx, entry))
                selectable_idx += 1
            if not editable_steps:
                print("  No hay pasos LLM para modificar en este plan.")
                continue

            print("\nPasos modificables en esta corrida:")
            for selectable_idx, _plan_idx, entry in editable_steps:
                print(
                    f"  [{selectable_idx:>2}] #{_plan_idx:>2} {entry.step_name} "
                    f"({entry.step_type}{' multi' if entry.is_multi else ' single'})"
                )
            print(
                "  Tip: usa índice de la fila anterior (1-{}) o rango (1-3), '*' para todos."\
                    .format(len(editable_steps))
            )
            print("  (Usando índice 1 te devuelve el paso mostrado 1, sin importar su número real en la tabla.)")
            step_input = input("  Pasos a editar: ").strip()
            if not step_input:
                print("  (Sin cambios: no se introdujeron pasos.)")
                continue
            step_indexes, error = _parse_step_indexes(
                step_input,
                max_count=len(editable_steps),
            )
            if error:
                print(f"  ✗ {error}")
                continue
            if step_indexes is None:
                continue

            overrides: dict[str, dict] = {}
            had_changes = False
            for idx in step_indexes:
                _, plan_idx, entry = editable_steps[idx - 1]
                print(
                    f"\n[Step {idx} / fila {plan_idx}] {entry.step_name} "
                    f"(actual: {', '.join(entry.models)})"
                )
                print("  Perfiles:")
                for pi, profile in enumerate(profile_catalog, start=1):
                    print(f"    {pi:>2}. {profile}")

                model_prompt = (
                    "  Nuevos modelos para este step (vacío = mantener, "
                    "separa con comas o usa 'all'): "
                )
                raw_models = input(model_prompt).strip()
                if raw_models:
                    selected_models, err = _parse_model_selection(raw_models)
                    if err:
                        print(f"  ✗ {err}")
                        continue
                    overrides.setdefault(entry.step_name, {})["models"] = selected_models
                    had_changes = True

                if entry.is_multi:
                    fusion_prompt = (
                        f"  Modelo de fusión (actual: {entry.fusion_model or 'auto'}) "
                        "[vacío=mantener, # índice o nombre]: "
                    )
                    raw_fusion = input(fusion_prompt).strip()
                    if raw_fusion:
                        selected_fusion, err = _resolve_profile_choice(raw_fusion)
                        if err:
                            print(f"  ✗ {err}")
                            continue
                        overrides.setdefault(entry.step_name, {})["fusion_model"] = selected_fusion
                        had_changes = True

            if not overrides:
                print("No se registraron cambios válidos.")
                continue
            if not had_changes:
                print("No se registraron cambios (solo se introdujo Enter para mantener valores).")
                continue

            config = config.with_step_model_overrides(overrides)
            new_plan = config.snapshot_pipeline_model_plan(step_names)
            new_models = build_effective_model_set(new_plan)
            pending_models = new_models - checked
            if pending_models:
                availability.update(check_model_profiles_availability(config, pending_models))
                checked.update(pending_models)
            plan = new_plan
            continue

        print("Formato: STEP=perfil1,perfil2[,fusion:perfilFusion]; STEP2=...")
        print("Opcionalmente, puedes sobreescribir el modelo de fusión con 'fusion:perfil':")
        print("  BULL=claude-opus-4.6,gemini-3-flash,fusion:claude-opus-4.6")
        print("  ARBITRO=fusion:claude-sonnet-4.6")
        print("También puedes usar índice: 8=... (8 suele ser CATALYST_DETECTION, 12 suele ser BULL)")
        print("Perfiles disponibles:", ", ".join(sorted(config.model_catalog)))
        raw_input = input("Overrides: ").strip()
        if not raw_input:
            continue

        overrides, errors = parse_step_overrides(
            raw_input,
            set(config.model_catalog.keys()),
            plan,
        )
        if errors:
            print("No se pudo aplicar el override:")
            for err in errors:
                print(f"  ✗ {err}")
            continue

        if not overrides:
            print("No se aportaron cambios válidos.")
            continue

        config = config.with_step_model_overrides(overrides)
        new_plan = config.snapshot_pipeline_model_plan(step_names)
        new_models = build_effective_model_set(new_plan)
        pending_models = new_models - checked
        if pending_models:
            availability.update(check_model_profiles_availability(config, pending_models))
            checked.update(pending_models)

        plan = new_plan


def _confirm(prompt: str) -> bool:
    ans = input(f"{prompt} [y/N]: ").strip().lower()
    return ans in {"y", "yes", "s", "sí"}


def _pick_step_indexes(raw: str, max_count: int) -> tuple[list[int], str | None]:
    if not raw.strip():
        return [], None
    token = raw.strip()
    if token == "*":
        return list(range(1, max_count + 1)), None

    selected: list[int] = []
    seen: set[int] = set()
    for piece in token.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "-" in piece:
            left, sep, right = piece.partition("-")
            if not sep or not left.isdigit() or not right.isdigit():
                return [], f"Rango inválido: {piece}"
            start, end = int(left), int(right)
            if start > end or start < 1 or end > max_count:
                return [], f"Rango inválido: {piece}"
            for idx in range(start, end + 1):
                if idx not in seen:
                    seen.add(idx)
                    selected.append(idx)
            continue

        if not piece.isdigit():
            return [], f"Paso inválido: {piece}"
        idx = int(piece)
        if idx < 1 or idx > max_count:
            return [], f"Paso inválido: {idx}"
        if idx not in seen:
            seen.add(idx)
            selected.append(idx)

    if not selected:
        return [], "No se seleccionó ningún paso"
    return selected, None


def _resolve_profile_input_for_list(
    raw_input: str,
    available_profiles: list[str],
) -> tuple[list[str] | None, bool, str | None]:
    value = raw_input.strip()
    if not value:
        return None, False, None
    if value.lower() in {"none", "clear", "-"}:
        return [], True, None

    resolved, errors = resolve_model_list(value, available_profiles)
    if errors:
        return None, False, "; ".join(errors)
    if not resolved:
        return None, False, "No se resolvieron perfiles"
    return resolved, False, None


def _resolve_single_profile_input(
    raw_input: str,
    available_profiles: list[str],
    *,
    allow_clear: bool = False,
) -> tuple[str | None, bool, str | None]:
    value = raw_input.strip()
    if not value:
        return None, False, None
    if allow_clear and value.lower() in {"none", "clear", "-"}:
        return None, True, None

    if "," in value:
        return None, False, "Especifique un único perfil"

    resolved, errors = resolve_model_list(value, available_profiles)
    if errors:
        return None, False, "; ".join(errors)
    if not resolved:
        return None, False, "Perfil sin resolver"
    if len(resolved) != 1:
        return None, False, "Especifique un único perfil"
    return resolved[0], False, None


def _transient_config_from_raw(
    base: EngineConfig,
    raw: dict,
) -> EngineConfig:
    return EngineConfig(
        raw=raw,
        workspace=base.workspace,
        model_catalog=base.model_catalog,
        copilot_binary=base.copilot_binary,
        binaries=base.binaries,
        _resolved_paths=dict(base._resolved_paths),
        _backend_availability=dict(base._backend_availability),
    )


def _describe_defaults_state(config: EngineConfig, raw: dict) -> None:
    snapshot = collect_persistent_defaults_snapshot(raw, config.model_catalog, config)
    print(format_defaults_snapshot(snapshot))


def _edit_global_defaults(
    config: EngineConfig,
    raw: dict,
    available_profiles: list[str],
) -> tuple[dict | None, list[str]]:
    if not config.is_v2:
        return None, ["Esta configuración no está en v2"]

    print("\n[defaults edit] Editando valores globales:")
    print(f"  pipeline_models      : {', '.join(raw.get('pipeline_models', []))}")
    print(f"  fusion_model         : {raw.get('fusion_model', '')}")
    print(f"  default_single_model : {raw.get('default_single_model', '')}")
    print("  Enter = mantener")

    updates: dict[str, object] = {}
    raw_pipeline = input("Nuevos pipeline_models: ").strip()
    if raw_pipeline:
        resolved, clear_error, list_err = _resolve_profile_input_for_list(
            raw_pipeline,
            available_profiles,
        )
        if list_err:
            return None, [list_err]
        if clear_error:
            return None, ["pipeline_models no puede quedar vacío"]
        if not resolved:
            return None, ["pipeline_models no puede quedar vacío"]
        updates["pipeline_models"] = resolved

    raw_fusion = input("Nuevo fusion_model global (vacío=mantener): ").strip()
    if raw_fusion:
        fusion, _, err = _resolve_single_profile_input(
            raw_fusion,
            available_profiles,
        )
        if err:
            return None, [f"fusion_model: {err}"]
        updates["fusion_model"] = fusion

    raw_single = input("Nuevo default_single_model (vacío=mantener): ").strip()
    if raw_single:
        single, _, err = _resolve_single_profile_input(
            raw_single,
            available_profiles,
        )
        if err:
            return None, [f"default_single_model: {err}"]
        updates["default_single_model"] = single

    if not updates:
        return raw, []

    next_raw, errors = build_global_updates(raw, updates)
    if errors:
        return None, [f"global update: {err}" for err in errors]
    return next_raw, []


def _edit_step_defaults(
    config: EngineConfig,
    raw: dict,
    available_profiles: list[str],
    *,
    step_plan: list[object] | None = None,
) -> tuple[dict | None, list[str]]:
    plan = step_plan or config.snapshot_pipeline_model_plan()
    editable_steps = [entry for entry in plan if entry.step_type != "python"]
    if not editable_steps:
        return raw, ["No hay pasos editables"]

    index_map: dict[int, object] = {}
    print("\n[defaults edit] Pasos editables:")
    for idx, entry in enumerate(editable_steps, start=1):
        index_map[idx] = entry
        current_fusion = entry.fusion_model or "—"
        print(
            f"  [{idx:>2}] {entry.step_name} "
            f"({entry.step_type}{' multi' if entry.is_multi else ' single'}) "
            f"→ modelos: {', '.join(entry.models)} | fusion: {current_fusion}"
        )
    print("  Tip: usa índice (1-{}), rango (1-4) o '*'.".format(len(editable_steps)))

    step_input = input("Pasos a editar: ").strip()
    step_indexes, step_err = _pick_step_indexes(step_input, len(editable_steps))
    if step_err:
        return None, [step_err]
    if not step_indexes:
        return raw, []

    next_raw = raw
    errors: list[str] = []
    for idx in step_indexes:
        entry = index_map[idx]
        print(
            f"\n[defaults edit] Step [{idx}] {entry.step_name}"
            f" (actual: modelos={', '.join(entry.models)}; fusion={entry.fusion_model or '—'})"
        )
        print("  Perfiles:")
        for pi, profile in enumerate(available_profiles, start=1):
            print(f"    {pi:>2}. {profile}")

        models_raw = input(
            "  Nuevos modelos (vacío=mantener, none=limpiar): "
        ).strip()
        if models_raw:
            resolved_models, clear_models, err = _resolve_profile_input_for_list(
                models_raw,
                available_profiles,
            )
            if err:
                errors.append(f"{entry.step_name}: {err}")
                continue
            if clear_models:
                resolved_models = []

            next_raw, step_errors = build_step_override_updates(
                next_raw,
                entry.step_name,
                models=resolved_models,
                fusion_model=None,
                reset=False,
                clear_fusion_model=False,
                is_step_multi=config.is_step_multi,
            )
            if step_errors:
                errors.extend(f"{entry.step_name}: {err}" for err in step_errors)
                continue

        if entry.is_multi:
            fusion_raw = input(
                "  Fusion model (vacío=mantener, none=limpiar): "
            ).strip()
            if fusion_raw:
                fusion_model, clear_fusion, fusion_err = _resolve_single_profile_input(
                    fusion_raw,
                    available_profiles,
                    allow_clear=True,
                )
                if fusion_err:
                    errors.append(f"{entry.step_name}: {fusion_err}")
                    continue
                next_raw, step_errors = build_step_override_updates(
                    next_raw,
                    entry.step_name,
                    models=None,
                    fusion_model=fusion_model,
                    reset=False,
                    clear_fusion_model=clear_fusion,
                    is_step_multi=config.is_step_multi,
                )
                if step_errors:
                    errors.extend(f"{entry.step_name}: {err}" for err in step_errors)
                    continue
        else:
            fusion_raw = input("  Fusion model (solo pasos multi; Enter para omitir): ").strip()
            if fusion_raw:
                errors.append(
                    f"{entry.step_name}: fusion_model no aplica en pasos single"
                )
                continue

    if errors:
        return None, errors
    return next_raw, []


def _run_defaults_edit_loop(config: EngineConfig, args) -> None:
    if not sys.stdin.isatty():
        print("[defaults] defaults edit requiere una terminal interactiva.")
        print(
            "Usa: engine defaults set/step set para cambios sin interacción."
        )
        sys.exit(1)

    try:
        ensure_v2(config)
    except RuntimeError as exc:
        print(f"[defaults] {exc}", file=sys.stderr)
        sys.exit(1)

    import copy

    raw, config_path = load_config_raw(args.config)
    working_raw = copy.deepcopy(raw)
    available_profiles = sorted(config.model_catalog.keys())

    while True:
        print("\n[defaults] Estado actual persistente (preview):")
        _describe_defaults_state(config, working_raw)

        working_config = _transient_config_from_raw(config, working_raw)
        plan = working_config.snapshot_pipeline_model_plan()
        availability = check_model_profiles_availability(
            working_config,
            working_config.effective_model_set(),
        )

        from .model_plan import render_plan_table
        print("\n[defaults] Plan efectivo con valores actuales:")
        print(render_plan_table(plan, availability))

        print(
            "\n[Enter]=Guardar y salir | [g]=Editar globals | [s]=Editar steps | [q]=Salir"
        )
        choice = input("> ").strip().lower()
        if choice in ("", "y", "ok", "sí", "si"):
            break
        if choice == "q":
            print("[defaults] Edición cancelada por el usuario.")
            sys.exit(0)
        if choice == "g":
            next_raw, errors = _edit_global_defaults(
                working_config,
                working_raw,
                available_profiles,
            )
            if errors:
                print("[defaults] Errores al editar valores globales:")
                for error in errors:
                    print(f"  ✗ {error}")
                continue
            if next_raw is not None and next_raw != working_raw:
                working_raw = next_raw
            continue
        if choice == "s":
            next_raw, errors = _edit_step_defaults(
                working_config,
                working_raw,
                available_profiles,
                step_plan=plan,
            )
            if errors:
                print("[defaults] Errores al editar steps:")
                for error in errors:
                    print(f"  ✗ {error}")
                continue
            if next_raw is not None:
                working_raw = next_raw
            continue

        print("Opción no válida.")

    final_config = _transient_config_from_raw(config, working_raw)
    diff = make_config_diff(config.raw, final_config.raw)
    print("\n[defaults] Diff:")
    print(diff)

    if diff == "No hay cambios.":
        print("[defaults] No se detectaron cambios.")
        return

    if args.dry_run:
        print("[defaults] Dry-run requested: no write.")
        return

    if not args.yes and not _confirm("¿Aplicar cambios persistentes?"):
        print("[defaults] Operación cancelada.")
        return

    backup = write_engine_config_atomic(
        config_path,
        final_config.raw,
        make_backup=not args.no_backup,
    )
    print("[defaults] Configuración persistente actualizada.")
    if backup:
        print(f"[defaults] Backup creado: {backup}")


def _print_defaults_show(config: EngineConfig, config_path: Path, *, check: bool) -> None:
    print(f"\n[defaults] Config file: {config_path}")
    print("[defaults] Current model defaults (v2):")
    print(f"  pipeline_models      : {', '.join(config.pipeline_models) or '(vacío)'}")
    print(f"  fusion_model         : {config.fusion_model}")
    print(f"  default_single_model : {config.default_single_model}")

    step_overrides = config.raw.get("step_overrides", {})
    if step_overrides:
        print("[defaults] step_overrides persistentes:")
        for step_name in sorted(step_overrides):
            override = step_overrides.get(step_name, {})
            if not isinstance(override, dict):
                continue
            models = override.get("models")
            fusion = override.get("fusion_model")
            print(f"  - {step_name}: ", end="")
            if "models" in override:
                print(f"models={', '.join(models) if isinstance(models, list) else models}", end="")
                if "fusion_model" in override:
                    print(f", fusion={fusion}")
                else:
                    print()
            elif "fusion_model" in override:
                print(f"fusion={fusion}")
            else:
                print("(sin overrides)")
    else:
        print("[defaults] step_overrides: (none)")

    from .model_plan import render_plan_table
    plan = config.snapshot_pipeline_model_plan()
    availability: dict[str, tuple[bool, str | None] | bool] = {}
    if check:
        # Keep backend preflight silent in this utility command unless explicitly requested
        # via --check, to avoid leaking noisy stderr traces in interactive output.
        availability = check_model_profiles_availability(
            config,
            set(config.model_catalog.keys()),
            suppress_backend_logs=True,
        )
    print("\n[defaults] Plan de ejecución por defecto:")
    print(render_plan_table(plan, availability, width=140))


def _normalize_updates(
    config: EngineConfig,
    pipeline_models: str | None,
    fusion_model: str | None,
    single_model: str | None,
) -> tuple[dict, list[str]]:
    updates: dict = {}
    errors: list[str] = []
    profile_catalog = sorted(config.model_catalog.keys())

    if pipeline_models is not None:
        resolved, errs = resolve_model_list(pipeline_models, profile_catalog)
        if errs:
            errors.extend([f"pipeline_models: {err}" for err in errs])
        else:
            updates["pipeline_models"] = resolved

    if fusion_model is not None:
        if not fusion_model.strip():
            errors.append("fusion-model no puede estar vacío")
        else:
            updates["fusion_model"] = fusion_model.strip()

    if single_model is not None:
        if not single_model.strip():
            errors.append("single-model no puede estar vacío")
        else:
            updates["default_single_model"] = single_model.strip()

    return updates, errors


def _cmd_defaults(config: EngineConfig, args) -> None:
    """Command dispatcher for `engine defaults ...`."""
    if args.defaults_command == "show":
        _cmd_defaults_show(config, args)
    elif args.defaults_command == "set":
        _cmd_defaults_set(config, args)
    elif args.defaults_command == "edit":
        _run_defaults_edit_loop(config, args)
    elif args.defaults_command == "step" and args.action == "set":
        _cmd_defaults_step_set(config, args)
    else:
        print("[defaults] Usage: engine defaults [show|set|edit|step set]")
        sys.exit(1)


def _cmd_defaults_show(config: EngineConfig, args) -> None:
    try:
        ensure_v2(config)
    except RuntimeError as exc:
        print(f"[defaults] {exc}", file=sys.stderr)
        sys.exit(1)
    _print_defaults_show(config, args.config, check=args.check)


def _cmd_defaults_set(config: EngineConfig, args) -> None:
    try:
        ensure_v2(config)
    except RuntimeError as exc:
        print(f"[defaults] {exc}", file=sys.stderr)
        sys.exit(1)

    raw, config_path = load_config_raw(args.config)

    updates, errors = _normalize_updates(config, args.pipeline_models, args.fusion_model, args.single_model)
    if errors:
        for error in errors:
            print(f"[defaults] ✗ {error}")
        sys.exit(1)

    if not updates:
        print("[defaults] ERROR: Debes indicar al menos --pipeline-models, --fusion-model o --single-model")
        sys.exit(1)

    new_raw, patch_errors = build_global_updates(raw, updates)
    if patch_errors:
        for error in patch_errors:
            print(f"[defaults] ✗ {error}")
        sys.exit(1)

    diff = make_config_diff(raw, new_raw)
    if diff == "No hay cambios.":
        print("[defaults] No se detectaron cambios.")
        return
    print("\n[defaults] Diff:")
    print(diff)
    if args.dry_run:
        print("[defaults] Dry-run requested: no write.")
        return

    if not args.yes and not _confirm("¿Aplicar cambios?"):
        print("[defaults] Operación cancelada.")
        return

    backup = write_engine_config_atomic(
        config_path,
        new_raw,
        make_backup=not args.no_backup,
    )
    print("[defaults] Configuración persistente actualizada.")
    if backup:
        print(f"[defaults] Backup creado: {backup}")


def _cmd_defaults_step_set(config: EngineConfig, args) -> None:
    try:
        ensure_v2(config)
    except RuntimeError as exc:
        print(f"[defaults] {exc}", file=sys.stderr)
        sys.exit(1)

    if not args.models and not args.fusion_model and not args.reset:
        print("[defaults] ERROR: Debes indicar --models, --fusion-model o --reset")
        sys.exit(1)

    raw, config_path = load_config_raw(args.config)

    models: list[str] | None
    if args.models is None:
        models = None
    else:
        raw_models = args.models.strip()
        if raw_models == "":
            models = []
        else:
            models, errors = resolve_model_list(raw_models, sorted(config.model_catalog.keys()))
            if errors:
                for error in errors:
                    print(f"[defaults] ✗ models: {error}")
                sys.exit(1)
    fusion_model = args.fusion_model.strip() if args.fusion_model else None
    fusion_value: str | None = None
    clear_fusion_model = False
    if fusion_model is not None:
        fusion_value, clear_errors = coerce_profile_or_empty(fusion_model)
        if clear_errors:
            for error in clear_errors:
                print(f"[defaults] ✗ fusion-model: {error}")
            sys.exit(1)
        clear_fusion_model = fusion_model.lower() in {"none", "clear", "-"} and fusion_value is None
        if not clear_fusion_model and fusion_value is None:
            fusion_value = None

    new_raw, errors = build_step_override_updates(
        raw,
        args.step,
        models=models,
        fusion_model=fusion_value,
        reset=bool(args.reset),
        clear_fusion_model=clear_fusion_model,
        is_step_multi=config.is_step_multi,
    )

    if errors:
        for error in errors:
            print(f"[defaults] ✗ {error}")
        sys.exit(1)

    diff = make_config_diff(raw, new_raw)
    if diff == "No hay cambios.":
        print("[defaults] No se detectaron cambios.")
        return
    print("\n[defaults] Diff:")
    print(diff)
    if args.dry_run:
        print("[defaults] Dry-run requested: no write.")
        return

    if not args.yes and not _confirm("¿Aplicar cambios?"):
        print("[defaults] Operación cancelada.")
        return

    backup = write_engine_config_atomic(
        config_path,
        new_raw,
        make_backup=not args.no_backup,
    )
    print("[defaults] Configuración persistente actualizada.")
    if backup:
        print(f"[defaults] Backup creado: {backup}")


def _report_step_failure(
    case_dir,
    step_name,
    error,
    failure_ctx,
    *,
    save_raw=False,
    persist_state=True,
    step_result=None,
) -> dict:
    if failure_ctx is None:
        failure_ctx = {
            "step_context": {
                "step": step_name,
                "mode": "router_or_dispatch",
            },
            "last_error": error or "(sin mensaje)",
        }
    elif not isinstance(failure_ctx, dict):
        failure_ctx = {"last_error": str(failure_ctx), "step_context": {"step": step_name}}

    print(format_failure_block(step_name, failure_ctx, error))

    persistent_ctx = dict(failure_ctx)
    if save_raw:
        payload = {
            "step": step_name,
            "error": error,
            "failure_ctx": failure_ctx,
            "result": step_result,
        }
        artifact_path = save_failure_artifact(case_dir, step_name, payload, include_raw=True)
        if artifact_path:
            persistent_ctx["diagnostic_path"] = artifact_path

    if persist_state:
        mark_step_failed(case_dir, step_name, error, failure_meta=persistent_ctx)
    return persistent_ctx


def _cmd_pipeline(config, args):
    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()

    config = _run_model_plan_assistant(config, no_plan=getattr(args, "no_plan", False))
    preflight_backends(config, model_profiles=config.effective_model_set())

    case_dir = config.get_path("casos") / ticker / date_str
    case_dir.mkdir(parents=True, exist_ok=True)

    raw_dir = config.get_path("casos") / ticker / "_raw_filings"
    raw_dir.mkdir(parents=True, exist_ok=True)

    result = execute_pipeline(
        config,
        case_dir,
        ticker,
        date_str,
        exchange=getattr(args, "exchange", ""),
        country=getattr(args, "country", ""),
        web_ir=getattr(args, "web_ir", ""),
    )
    final_state = result.get("state", {})
    if final_state.get("estado_pipeline") != "COMPLETO":
        for failed_step, failure_entry in (final_state.get("_errors") or {}).items():
            if not isinstance(failure_entry, dict):
                continue
            _report_step_failure(
                case_dir=case_dir,
                step_name=failed_step,
                error=failure_entry.get("error", "unknown"),
                failure_ctx=failure_entry.get("failure_meta"),
                save_raw=getattr(args, "save_raw_on_failure", False),
                persist_state=False,
                step_result=result.get("step_results", {}).get(failed_step),
            )
            break
    _refresh_quality_stats(config, case_dir)

    stage_case(case_dir, config.workspace)
    msg = prepare_commit_message(ticker, "PIPELINE", "COMPLETO", date_str)
    commit(config.workspace, msg)

    print(f"\n[engine] Pipeline finished. Status: {result['state']['estado_pipeline']}")


def _cmd_continue(config, args):
    """Continue pipeline from where it left off, executing all remaining steps."""
    import concurrent.futures

    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()

    case_dir = config.get_path("casos") / ticker / date_str
    if not (case_dir / "_estado.json").exists():
        print(f"[engine] ERROR: No state file in {case_dir}", file=sys.stderr)
        sys.exit(1)

    hints = resolve_empresa_hints(
        case_dir,
        exchange=getattr(args, "exchange", ""),
        country=getattr(args, "country", ""),
        web_ir=getattr(args, "web_ir", ""),
    )
    persist_empresa_hints(case_dir, hints)

    from .state import PIPELINE_STEPS
    mark_pipeline_status(case_dir, "EN_PROGRESO")

    next_step = get_next_step(case_dir)
    if next_step is None:
        mark_pipeline_status(case_dir, "COMPLETO")
        print("[engine] Pipeline already complete!")
        return

    if next_step in PIPELINE_STEPS:
        start_idx = PIPELINE_STEPS.index(next_step)
        pending_pipeline_keys = set(PIPELINE_STEPS[start_idx:])  # already pipeline_key values
        pending_keys: list[str] = []
        for step_def in config.get_dag("PIPELINE"):
            key = step_def.get("pipeline_key")
            if isinstance(key, str) and key in pending_pipeline_keys and key not in pending_keys:
                pending_keys.append(key)
    else:
        pending_keys = []

    config = _run_model_plan_assistant(
        config,
        no_plan=getattr(args, "no_plan", False),
        step_names=pending_keys,
    )
    preflight_backends(config, model_profiles=config.effective_model_set(step_names=pending_keys))

    print(f"[engine] Continuing from: {next_step}")

    # Walk through remaining pipeline steps (same logic as execute_pipeline)
    i = PIPELINE_STEPS.index(next_step)
    while i < len(PIPELINE_STEPS):
        step_name = PIPELINE_STEPS[i]

        if not is_step_ready(case_dir, step_name):
            print(f"[pipeline] Skipping {step_name} — dependencies not met")
            i += 1
            continue

        # Check for parallel group (e.g., CATALYST || FORENSIC)
        parallel_group = get_parallel_group(step_name)
        ready_parallels = [
            s for s in parallel_group
            if s != step_name and is_step_ready(case_dir, s)
        ]

        if ready_parallels:
            group = [step_name] + ready_parallels
            print(f"\n[pipeline] ═══ Executing parallel: {' || '.join(group)} ═══")

            max_workers = config.execution.get("max_parallel_backends", 3)
            parallel_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_step = {
                    executor.submit(
                        execute_step, config, case_dir, s, ticker, hints=hints
                    ): s
                    for s in group
                }
                for future in concurrent.futures.as_completed(future_to_step):
                    s = future_to_step[future]
                    try:
                        parallel_results[s] = future.result()
                    except Exception as e:
                        parallel_results[s] = {
                            "success": False,
                            "error": str(e),
                            "failure_ctx": {
                                "last_error": str(e),
                                "step_context": {"step": s},
                            },
                        }

            all_ok = True
            for s, res in parallel_results.items():
                if res.get("success"):
                    mark_step_done(
                        case_dir,
                        s,
                        model=res.get("model", "unknown"),
                        artefacto=res.get("artifact"),
                        model_profile=res.get("model_profile"),
                    )
                    print(f"[pipeline] ✓ {s} completed")
                else:
                    failure_ctx = res.get("failure_ctx")
                    failure_error = res.get("error", "unknown")
                    mark_step_failed(
                        case_dir,
                        s,
                        failure_error,
                        failure_meta=failure_ctx,
                    )
                    print(f"[pipeline] ✗ {s} failed: {failure_error}")
                    all_ok = False
                    _report_step_failure(
                        case_dir,
                        s,
                        failure_error,
                        failure_ctx,
                        save_raw=getattr(args, "save_raw_on_failure", False),
                        persist_state=False,
                        step_result=res,
                    )

            if not all_ok and config.execution.get("fail_fast", True):
                print("[pipeline] fail_fast=true — stopping")
                break

            i += len(group)
            continue

        print(f"\n[pipeline] ═══ Executing: {step_name} ═══")

        try:
            result = execute_step(config, case_dir, step_name, ticker, hints=hints)

            if result.get("success"):
                mark_step_done(
                    case_dir,
                    step_name,
                    model=result.get("model", "unknown"),
                    artefacto=result.get("artifact"),
                    model_profile=result.get("model_profile"),
                )
                print(f"[pipeline] ✓ {step_name} completed")
                if step_name == "ARBITRO":
                    from .router import _extract_decision_fields
                    _extract_decision_fields(case_dir, result)
            else:
                failure_error = result.get("error", "unknown")
                failure_ctx = result.get("failure_ctx")
                mark_step_failed(
                    case_dir,
                    step_name,
                    failure_error,
                    failure_meta=failure_ctx,
                )
                print(f"[pipeline] ✗ {step_name} failed: {failure_error}")
                _report_step_failure(
                    case_dir,
                    step_name,
                    failure_error,
                    failure_ctx,
                    save_raw=getattr(args, "save_raw_on_failure", False),
                    persist_state=False,
                    step_result=result,
                )
                if config.execution.get("fail_fast", True):
                    print("[pipeline] fail_fast=true — stopping")
                    break
        except Exception as e:
            print(f"[pipeline] ✗ {step_name} exception: {e}", file=sys.stderr)
            failure_ctx = {"last_error": str(e), "step_context": {"step": step_name}}
            mark_step_failed(
                case_dir,
                step_name,
                str(e),
                failure_meta=failure_ctx,
            )
            _report_step_failure(
                case_dir,
                step_name,
                str(e),
                failure_ctx,
                save_raw=getattr(args, "save_raw_on_failure", False),
                persist_state=False,
                step_result={"error": str(e), "failure_ctx": failure_ctx},
            )
            if config.execution.get("fail_fast", True):
                break

        i += 1

    # Final status
    final_state = load_state(case_dir)
    from .state import PIPELINE_STEPS as PS
    all_done = all(
        final_state.get("pipeline", {}).get(s, {}).get("estado") == "DONE"
        for s in PS
    )
    if all_done:
        mark_pipeline_status(case_dir, "COMPLETO")

    final_state = load_state(case_dir)
    _refresh_quality_stats(config, case_dir)
    print(f"\n[engine] Continue finished. Status: {final_state['estado_pipeline']}")


def _refresh_quality_stats(config, case_dir: Path) -> None:
    """Refresh global/per-case model quality stats (best-effort, non-blocking)."""
    try:
        from .quality_voting import get_quality_voting_config
        from .model_quality_stats import (
            refresh_global_model_quality_stats,
            refresh_case_model_quality_stats,
        )

        qv_cfg = get_quality_voting_config(config.raw)
        model_stats_cfg = qv_cfg.get("model_stats", {})
        if not isinstance(model_stats_cfg, dict) or not model_stats_cfg.get("enabled", False):
            return

        refresh_global_model_quality_stats(config.workspace, qv_cfg)
        refresh_case_model_quality_stats(config.workspace, case_dir, qv_cfg)
    except Exception as exc:
        print(f"[engine] WARNING: model quality stats refresh failed: {exc}", file=sys.stderr)


def _cmd_step(config, args):
    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()
    step_name = args.step_name.upper()

    case_dir = config.get_path("casos") / ticker / date_str
    hints = resolve_empresa_hints(
        case_dir,
        exchange=getattr(args, "exchange", ""),
        country=getattr(args, "country", ""),
        web_ir=getattr(args, "web_ir", ""),
    )
    if not (case_dir / "_estado.json").exists():
        init_state(
            case_dir,
            ticker,
            date_str,
            exchange=hints["exchange"],
            country=hints["country"],
            web_ir=hints["web_ir"],
        )
    else:
        persist_empresa_hints(case_dir, hints)

    result = execute_step(config, case_dir, step_name, ticker, hints=hints)

    if result.get("success"):
        mark_step_done(
            case_dir,
            step_name,
            model=result.get("model", "unknown"),
            artefacto=result.get("artifact"),
            model_profile=result.get("model_profile"),
        )
        if step_name == "ARBITRO":
            from .router import _extract_decision_fields
            _extract_decision_fields(case_dir, result)
    else:
        failure_error = result.get("error", "unknown")
        failure_ctx = result.get("failure_ctx")
        mark_step_failed(case_dir, step_name, failure_error, failure_meta=failure_ctx)
        _report_step_failure(
            case_dir,
            step_name,
            failure_error,
            failure_ctx,
            save_raw=False,
            persist_state=False,
            step_result=result,
        )

    print(f"[engine] Step {step_name}: {'success' if result.get('success') else 'failed'}")


def _cmd_rehacer(config, args):
    """Reset step to PENDING and re-execute.

    Works for both pipeline steps and sub-steps.
    """
    from .state import save_state

    date_str = args.date or date.today().isoformat()
    ticker = args.ticker.upper()
    step_name = args.step_name.upper()

    case_dir = config.get_path("casos") / ticker / date_str
    if not (case_dir / "_estado.json").exists():
        print(f"[engine] ERROR: No state file in {case_dir}", file=sys.stderr)
        sys.exit(1)

    hints = resolve_empresa_hints(
        case_dir,
        exchange=getattr(args, "exchange", ""),
        country=getattr(args, "country", ""),
        web_ir=getattr(args, "web_ir", ""),
    )
    persist_empresa_hints(case_dir, hints)

    state = load_state(case_dir)
    reset_done = False

    # Reset in pipeline dict (main steps)
    if step_name in state.get("pipeline", {}):
        state["pipeline"][step_name] = {"estado": "PENDING", "artefacto": None, "artefacto_previo": None}
        state["estado_pipeline"] = "INCOMPLETO"
        reset_done = True

    # Reset in sub_steps dict (sub-steps like TP_EXTRACTOR_FILING)
    if step_name in state.get("sub_steps", {}):
        state["sub_steps"][step_name] = {"status": "PENDING"}
        # Also reset parent group if it's FAILED
        from .router import SUB_STEPS
        for group, subs in SUB_STEPS.items():
            if step_name in subs and group in state.get("pipeline", {}):
                if state["pipeline"][group].get("estado") == "FAILED":
                    state["pipeline"][group] = {"estado": "PENDING", "artefacto": None, "artefacto_previo": None}
                break
        state["estado_pipeline"] = "INCOMPLETO"
        reset_done = True

    if not reset_done:
        print(f"[engine] ERROR: Step '{step_name}' not found in pipeline or sub_steps", file=sys.stderr)
        sys.exit(1)

    save_state(case_dir, state)

    print(f"[engine] Redoing step: {step_name}")
    result = execute_step(config, case_dir, step_name, ticker, hints=hints)
    if not result.get("success"):
        failure_error = result.get("error", "unknown")
        failure_ctx = result.get("failure_ctx")
        mark_step_failed(case_dir, step_name, failure_error, failure_meta=failure_ctx)
        _report_step_failure(
            case_dir,
            step_name,
            failure_error,
            failure_ctx,
            save_raw=False,
            persist_state=False,
            step_result=result,
        )

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
                    exchange="",
                    country="",
                    web_ir="",
                ))
        elif cmd == "continue":
            ticker = input("Ticker: ").strip().upper()
            if ticker:
                from types import SimpleNamespace
                _cmd_continue(config, SimpleNamespace(
                    ticker=ticker,
                    date=date.today().isoformat(),
                    model="Codex",
                    exchange="",
                    country="",
                    web_ir="",
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
