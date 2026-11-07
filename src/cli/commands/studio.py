"""`ylk studio` — API del estudio local (FastAPI + uvicorn en 127.0.0.1).

    ylk studio                 # 127.0.0.1:${STUDIO_PORT:-8001}
    ylk studio --port 8011

Escucha SOLO en 127.0.0.1 (no hay opción de host a propósito). No arranca sin
STUDIO_TOKEN en el .env; el token nunca se imprime.
"""
from __future__ import annotations

import os

import typer

TOKEN_HELP = (
    "Falta STUDIO_TOKEN en el .env. Genera uno y pégalo en el .env (y en frontend-react/.env.local):\n"
    "  python -c \"import secrets;print(secrets.token_urlsafe(32))\"\n"
    "  STUDIO_TOKEN=<el valor generado>"
)


def register(app: typer.Typer) -> None:

    @app.command()
    def studio(port: int = typer.Option(None, help="Default: STUDIO_PORT del .env o 8001"),
               log_level: str = typer.Option("info", help="debug|info|warning")):
        """Estudio local: biblioteca, momentos, lecciones, revisión y publicación (127.0.0.1)."""
        from dotenv import load_dotenv
        load_dotenv()
        if not (os.getenv("STUDIO_TOKEN") or "").strip():
            typer.echo(TOKEN_HELP, err=True)
            raise typer.Exit(2)
        if port:
            os.environ["STUDIO_PORT"] = str(port)        # el redirect de OAuth de YouTube usa este puerto
        import uvicorn

        from apps.studio.app import create_app
        from apps.studio.settings import port as studio_port
        bind = studio_port()
        typer.echo(f"Estudio en http://127.0.0.1:{bind}/api  (front: http://127.0.0.1:5180)")
        uvicorn.run(create_app(), host="127.0.0.1", port=bind, log_level=log_level, ws="auto")
