"""Estudio de producción LOCAL (FastAPI en 127.0.0.1): contrato en docs/architecture/STUDIO_API.md.

    ylk studio            → uvicorn en 127.0.0.1:${STUDIO_PORT:-8001}
    app.create_app()      → routers system | library | jobs | moments | lessons | review | publish | files
    jobs.JobQueue         → tabla studio_jobs + UN hilo worker (red/GPU en serie), progreso por /ws

Este __init__ no importa FastAPI a propósito: core.db registra `apps.studio.schema`
y una DB fresca no debe depender de que la API esté instalada.
"""
