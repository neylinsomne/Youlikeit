"""`ylk doctor` — estado de keys, tokens OAuth y stack local (sin mostrar valores)."""
from __future__ import annotations

import typer

_ICON = {"OK": "✔", "WARN": "!", "MISSING": "·", "INVALID": "✘", "ERROR": "✘"}


def register(app: typer.Typer) -> None:

    @app.command()
    def doctor(offline: bool = typer.Option(False, help="Solo stack local, sin llamar a APIs")):
        """Verifica credenciales (llamada mínima a cada servicio) y el stack local."""
        from dotenv import load_dotenv

        from integrations.credentials_check import run_all

        load_dotenv()
        checks = run_all(network=not offline)
        width = max(len(c.name) for c in checks)
        for c in checks:
            typer.echo(f" {_ICON.get(c.status, '?')} {c.name:<{width}}  {c.status:<8} "
                       f"{c.detail[:80]:<80}  [{c.needed_for}]")
        bad = [c for c in checks if c.status in ("INVALID", "ERROR")]
        typer.echo(f"\n{len(checks) - len(bad)}/{len(checks)} sin errores. "
                   "Guía para arreglar: SETUP_CUENTAS.md")
        raise typer.Exit(1 if bad else 0)
