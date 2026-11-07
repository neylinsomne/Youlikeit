"""`ylk analytics …` — dominio Analytics (Plausible + dashboards)."""
from __future__ import annotations

import typer

from cli._run import run_script

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Plausible + dashboards")

_PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


@app.command(context_settings=_PASSTHROUGH)
def fetch(ctx: typer.Context):
    """Trae stats de Plausible (scripts/analytics/fetch_plausible_stats.py)."""
    run_script("scripts/analytics/fetch_plausible_stats.py", ctx.args)


@app.command(context_settings=_PASSTHROUGH)
def dashboard(ctx: typer.Context):
    """Dashboard unificado de analítica (scripts/analytics/unified_dashboard.py)."""
    run_script("scripts/analytics/unified_dashboard.py", ctx.args)
