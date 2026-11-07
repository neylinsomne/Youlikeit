"""`ylk` — CLI unificado de YouLikeIt.

Entry point declarado en pyproject (`[project.scripts] ylk = "cli.main:main"`).
Disponible tras `pip install -e .` (lo hace el Dockerfile y los workflows).

Estructura:
- grupos por dominio:   ylk signals …   ylk analytics …
- verbos top-level:     ylk produce …   ylk rotate …   ylk clean …   ylk score …

Agregar funcionalidad = añadir un comando en cli/commands/<dominio>.py
(o un módulo nuevo + add_typer/register acá).
"""
from __future__ import annotations

import sys

import typer

from cli.commands import analytics as analytics_cmd
from cli.commands import doctor as doctor_cmd
from cli.commands import media as media_cmd
from cli.commands import moments as moments_cmd
from cli.commands import production as production_cmd
from cli.commands import scoring as scoring_cmd
from cli.commands import signals as signals_cmd
from cli.commands import studio as studio_cmd

# Consolas Windows (cp1252) no codifican algunos glifos; forzamos UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="YouLikeIt - CLI unificado del pipeline (signals -> produce -> score -> analytics)",
)

# Grupos por dominio
app.add_typer(signals_cmd.app, name="signals")
app.add_typer(analytics_cmd.app, name="analytics")
app.add_typer(media_cmd.app, name="media")
app.add_typer(moments_cmd.app, name="moments")

# Verbos top-level
production_cmd.register(app)
scoring_cmd.register(app)
doctor_cmd.register(app)
studio_cmd.register(app)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
