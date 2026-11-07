"""Helper compartido: ejecuta un script del repo reenviando args.

Los comandos de `ylk` son wrappers delgados: parsean lo mínimo y delegan en los
runners de `scripts/<dominio>/`. cwd = repo root para que los paths relativos
(data/, outputs/) resuelvan igual que al invocar el script a mano.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_script(rel_path: str, extra: list[str] | None = None) -> "None":
    """Corre `python <repo>/<rel_path> <extra...>` con cwd=repo root.

    Sale con el mismo código de retorno del script (SystemExit).
    """
    cmd = [sys.executable, str(ROOT / rel_path), *(extra or [])]
    raise SystemExit(subprocess.run(cmd, cwd=ROOT).returncode)
