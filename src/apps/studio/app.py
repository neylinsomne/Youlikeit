"""FastAPI del estudio local. Contrato: docs/architecture/STUDIO_API.md.

    create_app()                     app lista para uvicorn (127.0.0.1 SOLAMENTE, ver cli/commands/studio.py)
    create_app(start_worker=False)   para tests: el worker no arranca; se usa app.state.jobs.run_next()
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.studio import settings
from apps.studio.auth import StudioGuardMiddleware
from apps.studio.jobs import JobQueue
from apps.studio.routers import files, jobs, lessons, library, moments, publish, review, system
from utils.websocket_hub import create_ws_endpoint

def create_app(*, start_worker: bool = True, queue: JobQueue | None = None) -> FastAPI:
    job_queue = queue or JobQueue(settings.connect)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.connect().close()                 # esquema completo (get_db) antes del primer request
        if start_worker:
            job_queue.start()
        try:
            yield
        finally:
            if start_worker:
                job_queue.stop()

    app = FastAPI(title="YouLikeIt Studio", version="1", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.jobs = job_queue

    for module in (system, library, jobs, moments, lessons, review, publish, files):
        app.include_router(module.router)
    app.include_router(system.public)              # GET /api/health
    app.include_router(publish.public_router)      # callback OAuth de YouTube (protegido por state)
    create_ws_endpoint(app)                        # /ws (token: StudioGuardMiddleware)

    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins(), allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type", "Range"],
                       expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"])
    app.add_middleware(StudioGuardMiddleware)      # el último agregado queda por fuera de todo
    return app
