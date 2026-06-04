"""`ylk produce|rotate|clean` — dominio Production (verbos top-level)."""
from __future__ import annotations

import typer

from cli._run import run_script

_PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


def register(app: typer.Typer) -> None:
    """Registra los verbos de producción como comandos top-level de `ylk`."""

    @app.command(context_settings=_PASSTHROUGH)
    def produce(ctx: typer.Context):
        """Produce 1 serie × vtype (scripts/production/produce_for_series.py)."""
        run_script("scripts/production/produce_for_series.py", ctx.args)

    @app.command(context_settings=_PASSTHROUGH)
    def rotate(ctx: typer.Context):
        """Batch 3 personas × 3 vtypes (scripts/production/run_rotation_batch.py)."""
        run_script("scripts/production/run_rotation_batch.py", ctx.args)

    @app.command(context_settings=_PASSTHROUGH)
    def clean(ctx: typer.Context):
        """Reset DB + produce primer short (scripts/production/clean_and_produce.py)."""
        run_script("scripts/production/clean_and_produce.py", ctx.args)
