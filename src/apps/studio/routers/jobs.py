"""Jobs: POST /api/jobs, GET /api/jobs, GET /api/jobs/{id} (el worker los corre en serie)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from apps.studio import jobs
from apps.studio.auth import require_token
from apps.studio.errors import api

router = APIRouter(prefix="/api", tags=["jobs"], dependencies=[Depends(require_token)])


class JobIn(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)


def submit(request: Request, conn, job_type: str, params: dict) -> dict:
    """Encola y despierta al worker (si corre en este proceso)."""
    job = jobs.create_job(conn, job_type, params)
    queue = getattr(request.app.state, "jobs", None)
    if queue is not None:
        queue.wake()
    return job


@router.post("/jobs")
def create(body: JobIn, request: Request) -> dict:
    with api() as conn:
        return submit(request, conn, body.type, body.params)


@router.get("/jobs")
def list_(status: str | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
    with api() as conn:
        return {"items": jobs.list_jobs(conn, status=status or None, limit=limit)}


@router.get("/jobs/{job_id}")
def get(job_id: int) -> dict:
    with api() as conn:
        return jobs.get_job(conn, job_id)
