"""Actualiza CHANGELOG.md y FECHAS_CLAVE.md programáticamente (0 tokens).

Implements §3.12 of PLAN COMPLETO.
"""

from pathlib import Path
from datetime import date, datetime


def append_entry(
    changelog_path: Path,
    ticker: str,
    operation: str,
    step: str,
    model: str,
    notes: str = "",
) -> None:
    """
    Añade entrada al CHANGELOG con formato:
    ## {fecha}
    - [{operation}] {ticker}: {step} ({model}). {notes}
    """
    today = date.today().isoformat()
    timestamp = datetime.now().strftime("%H:%M")

    entry = f"- [{operation}] {ticker}: {step} ({model})"
    if notes:
        entry += f". {notes}"

    if changelog_path.exists():
        content = changelog_path.read_text()
    else:
        content = f"# CHANGELOG — 3_0-ELSIAN-INVEST\n\n"

    # Check if today's header already exists
    header = f"## {today}"
    if header in content:
        # Insert entry after the header
        idx = content.index(header) + len(header)
        # Find end of header line
        newline_idx = content.index("\n", idx)
        content = content[:newline_idx + 1] + f"{entry}  [{timestamp}]\n" + content[newline_idx + 1:]
    else:
        # Add new date header at the top (after main title)
        if content.startswith("# "):
            first_newline = content.index("\n")
            content = (
                content[:first_newline + 1]
                + f"\n{header}\n{entry}  [{timestamp}]\n"
                + content[first_newline + 1:]
            )
        else:
            content = f"{header}\n{entry}  [{timestamp}]\n\n" + content

    changelog_path.write_text(content)


def read_last_entries(changelog_path: Path, n: int = 10) -> list[str]:
    """Lee últimas N entradas."""
    if not changelog_path.exists():
        return []

    entries = []
    for line in changelog_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("- ["):
            entries.append(line)
            if len(entries) >= n:
                break

    return entries


def update_fechas_clave(
    fechas_path: Path,
    ticker: str,
    event_type: str,
    event_date: str,
    description: str = "",
) -> None:
    """
    Añade o actualiza entrada en FECHAS_CLAVE.md.
    event_type: 'earnings', 'ex-div', 'catalyst', etc.
    """
    today = date.today().isoformat()
    entry = f"| {ticker} | {event_type} | {event_date} | {description} |"

    if fechas_path.exists():
        content = fechas_path.read_text()
    else:
        content = (
            "# FECHAS CLAVE\n\n"
            "| Ticker | Tipo | Fecha | Descripción |\n"
            "|--------|------|-------|-------------|\n"
        )

    # Check if ticker+type already exists → update
    lines = content.splitlines()
    updated = False
    for i, line in enumerate(lines):
        if f"| {ticker} |" in line and f"| {event_type} |" in line:
            lines[i] = entry
            updated = True
            break

    if updated:
        content = "\n".join(lines) + "\n"
    else:
        # Append at the end
        content = content.rstrip() + "\n" + entry + "\n"

    fechas_path.write_text(content)
