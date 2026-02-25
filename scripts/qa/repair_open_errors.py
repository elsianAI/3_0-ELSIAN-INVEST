#!/usr/bin/env python3
"""Reconstruye _errors/open_errors.json desde cero.

Escanea todos los _estado.json en casos/**/_estado.json y reconstruye
el snapshot de errores activos (open_errors.json) a partir de los pasos
con estado=FAILED que aún no se han completado.

Útil después de:
  - Pérdida o corrupción de _errors/open_errors.json
  - Migración de versión del schema
  - Cualquier operación manual sobre _estado.json

Uso:
  python3 scripts/qa/repair_open_errors.py
  python3 scripts/qa/repair_open_errors.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconstruye _errors/open_errors.json escaneando todos los _estado.json."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra cuántos errores se encontrarían sin escribir nada.",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Ruta raíz del workspace (por defecto: directorio padre de scripts/).",
    )
    args = parser.parse_args()

    # Resolve workspace root
    if args.workspace:
        workspace = Path(args.workspace).resolve()
    else:
        # scripts/qa/repair_open_errors.py → workspace = ../../
        workspace = Path(__file__).resolve().parent.parent.parent

    if not workspace.exists():
        print(f"ERROR: workspace no encontrado: {workspace}", file=sys.stderr)
        sys.exit(1)

    casos_dir = workspace / "casos"
    errors_dir = workspace / "_errors"
    open_errors_path = errors_dir / "open_errors.json"

    if not casos_dir.exists():
        print(f"ERROR: directorio casos/ no encontrado en {workspace}", file=sys.stderr)
        sys.exit(1)

    # Añadir workspace al sys.path para importar engine
    sys.path.insert(0, str(workspace))

    try:
        from engine.error_tracker import rebuild_open_errors
    except ImportError as e:
        print(f"ERROR: no se pudo importar engine.error_tracker: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        # Sólo cuenta sin escribir
        count = 0
        for estado_path in sorted(casos_dir.glob("*/*/_estado.json")):
            try:
                with open(estado_path, encoding="utf-8") as fh:
                    state = json.load(fh)
            except Exception:
                continue
            for step, err_entry in (state.get("_errors") or {}).items():
                if isinstance(err_entry, dict):
                    ticker = state.get("ticker", "?")
                    fecha = state.get("fecha_caso", "?")
                    print(f"  [DRY-RUN] {ticker} {fecha} {step}: {(err_entry.get('error','?'))[:60]}")
                    count += 1
        print(f"\n[dry-run] Se encontraron {count} error(s) activo(s). Nada escrito.")
        return

    count = rebuild_open_errors(workspace)
    print(f"✓ open_errors.json reconstruido: {open_errors_path}")
    print(f"  {count} error(s) activo(s) encontrado(s) en casos/.")


if __name__ == "__main__":
    main()
