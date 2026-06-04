"""`ylk score` — dominio Scoring (hook quality gate, verbo top-level)."""
from __future__ import annotations

import typer

from cli._run import run_script

_PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


def register(app: typer.Typer) -> None:
    """Registra los verbos de scoring como comandos top-level de `ylk`."""

    @app.command(context_settings=_PASSTHROUGH)
    def score(ctx: typer.Context):
        """Scorea hooks de videos producidos (scripts/scoring/score_hooks.py)."""
        run_script("scripts/scoring/score_hooks.py", ctx.args)
