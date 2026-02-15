"""Equivalente a estado_resumen.py — genera dashboard sin LLM (0 tokens).

Implements §3.3 of PLAN COMPLETO.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass, field


@dataclass
class DashboardData:
    """Datos procesados del dashboard."""
    total_cases: int = 0
    by_status: dict[str, list[dict]] = field(default_factory=dict)
    actionable: list[dict] = field(default_factory=list)
    monitors_overdue: list[dict] = field(default_factory=list)
    generated_at: str = ""


# Operations available from the interactive menu
OPERATIONS = {
    "1": {"label": "Pipeline completo (caso nuevo)", "command": "pipeline"},
    "2": {"label": "Continuar caso incompleto", "command": "continue"},
    "3": {"label": "Ejecutar step individual", "command": "step"},
    "4": {"label": "Rehacer step", "command": "rehacer"},
    "5": {"label": "Validar artefactos", "command": "validate"},
    "6": {"label": "Monitor", "command": "monitor"},
    "7": {"label": "Scanner", "command": "scanner"},
    "8": {"label": "Scout", "command": "scout"},
    "9": {"label": "Outcome", "command": "outcome"},
    "10": {"label": "Evaluar", "command": "evaluar"},
    "11": {"label": "Benchmark", "command": "benchmark"},
    "0": {"label": "Salir", "command": "exit"},
}


def build_dashboard(workspace: Path) -> DashboardData:
    """Construye DashboardData escaneando todos los casos."""
    casos_dir = workspace / "casos"
    data = DashboardData(generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"))

    if not casos_dir.exists():
        return data

    cases = []
    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            state_file = case_dir / "_estado.json"
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        state = json.load(f)
                    state["_case_dir"] = str(case_dir)
                    cases.append(state)
                except (json.JSONDecodeError, OSError):
                    cases.append({"caso_id": case_dir.name, "estado_pipeline": "ERROR_READ"})

    data.total_cases = len(cases)

    # Group by status
    for c in cases:
        status = c.get("estado_pipeline", "UNKNOWN")
        data.by_status.setdefault(status, []).append(c)

    # Monitors overdue
    today = date.today().isoformat()
    data.monitors_overdue = [
        c for c in cases
        if c.get("proxima_revision") and c["proxima_revision"] <= today
        and c.get("estado_pipeline") == "COMPLETO"
    ]

    # Actionable items
    data.actionable = get_actionable_items(workspace)

    return data


def render_dashboard(data: DashboardData) -> str:
    """Renderiza DashboardData como texto para terminal."""
    lines = []
    lines.append(f"═══ DASHBOARD 3_0-ELSIAN-INVEST ═══  ({data.generated_at})")
    lines.append(f"Total cases: {data.total_cases}")
    lines.append("")

    for status in ["COMPLETO", "EN_PROGRESO", "INCOMPLETO", "QUARANTINE",
                    "BLOCKED", "SUPERSEDED", "EXCLUIDO", "LEGACY"]:
        group = data.by_status.get(status, [])
        if group:
            tickers = [c.get("ticker", "?") for c in group]
            lines.append(f"  {status}: {len(group)} — {', '.join(tickers[:10])}")

    if data.monitors_overdue:
        lines.append("")
        lines.append(f"⚠ Monitors overdue: {len(data.monitors_overdue)}")
        for c in data.monitors_overdue[:5]:
            lines.append(f"    {c.get('ticker', '?')} — due {c.get('proxima_revision')}")

    incomplete = data.by_status.get("INCOMPLETO", [])
    if incomplete:
        lines.append("")
        lines.append(f"Incomplete pipelines ({len(incomplete)}):")
        for c in incomplete[:10]:
            pipeline = c.get("pipeline", {})
            pending = [s for s, v in pipeline.items() if v.get("estado") != "DONE"]
            next_s = pending[0] if pending else "?"
            lines.append(f"    {c.get('ticker', '?')} → next: {next_s}")

    if data.actionable:
        lines.append("")
        lines.append("Actionable items:")
        for item in data.actionable[:8]:
            t = item.get("type", "?")
            tk = item.get("ticker", "?")
            if t == "QUARANTINE":
                lines.append(f"  🔴 {tk}: {item.get('reason', '')}")
            elif t == "CONTINUE":
                lines.append(f"  🟡 {tk}: continue → {item.get('next_step', '?')}")
            elif t == "MONITOR_DUE":
                lines.append(f"  🔵 {tk}: monitor due {item.get('due_date', '?')}")

    return "\n".join(lines)


def generate_dashboard(workspace: Path) -> str:
    """Shortcut: build + render."""
    data = build_dashboard(workspace)
    return render_dashboard(data)


def get_actionable_items(workspace: Path) -> list[dict]:
    """Retorna lista priorizada de acciones pendientes."""
    casos_dir = workspace / "casos"
    if not casos_dir.exists():
        return []

    items = []
    today = date.today().isoformat()

    for ticker_dir in sorted(casos_dir.iterdir()):
        if not ticker_dir.is_dir():
            continue
        for case_dir in sorted(ticker_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            state_file = case_dir / "_estado.json"
            if not state_file.exists():
                continue
            try:
                with open(state_file) as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            ticker = state.get("ticker", "?")
            status = state.get("estado_pipeline", "UNKNOWN")

            if status == "QUARANTINE":
                items.append({
                    "type": "QUARANTINE",
                    "ticker": ticker,
                    "priority": 1,
                    "reason": state.get("notas", "Quality audit failed"),
                })
            elif status == "INCOMPLETO":
                pipeline = state.get("pipeline", {})
                pending = [s for s, v in pipeline.items() if v.get("estado") != "DONE"]
                if pending:
                    items.append({
                        "type": "CONTINUE",
                        "ticker": ticker,
                        "priority": 2,
                        "next_step": pending[0],
                    })
            elif status == "COMPLETO" and state.get("proxima_revision"):
                if state["proxima_revision"] <= today:
                    items.append({
                        "type": "MONITOR_DUE",
                        "ticker": ticker,
                        "priority": 3,
                        "due_date": state["proxima_revision"],
                    })

    items.sort(key=lambda x: x.get("priority", 99))
    return items


def show_menu() -> str | None:
    """Muestra menú interactivo, retorna command seleccionado o None."""
    print("\n═══ OPERACIONES DISPONIBLES ═══")
    for key, op in OPERATIONS.items():
        print(f"  [{key}] {op['label']}")
    print()

    try:
        choice = input("Selecciona operación: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    op = OPERATIONS.get(choice)
    if op is None:
        print(f"Opción no válida: {choice}")
        return None
    return op["command"]
