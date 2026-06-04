"""`ylk signals …` — dominio Signals (ingesta → briefs).

Wrappers passthrough sobre scripts/signals/*. Cualquier flag se reenvía tal cual
al script subyacente (ver `--help` del script para la lista completa).
"""
from __future__ import annotations

import typer

from cli._run import run_script

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Ingesta de señales y briefs")

_PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


@app.command(context_settings=_PASSTHROUGH)
def refresh(ctx: typer.Context):
    """Refresca market_signals + distill (scripts/signals/refresh_market_signals.py)."""
    run_script("scripts/signals/refresh_market_signals.py", ctx.args)


@app.command(context_settings=_PASSTHROUGH)
def verify(ctx: typer.Context):
    """Smoke E2E del flujo de información sobre DB real (verify_signals_flow.py)."""
    run_script("scripts/signals/verify_signals_flow.py", ctx.args)


@app.command(context_settings=_PASSTHROUGH)
def dashboard(ctx: typer.Context):
    """Inspector CLI de briefs/scrapers/unresolved (briefs_dashboard.py)."""
    run_script("scripts/signals/briefs_dashboard.py", ctx.args)
