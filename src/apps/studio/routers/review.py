"""Revisión: aprobar, rechazar e issues con tiempo."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from apps.studio.auth import require_token
from apps.studio.errors import api
from apps.supercut import lessons

router = APIRouter(prefix="/api", tags=["review"], dependencies=[Depends(require_token)])


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class IssueIn(BaseModel):
    issue_type: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    note: str | None = Field(default=None, max_length=2000)


@router.post("/lessons/{lesson_id}/approve")
def approve(lesson_id: int) -> dict:
    with api() as conn:
        return lessons.approve(conn, lesson_id)


@router.post("/lessons/{lesson_id}/reject")
def reject(lesson_id: int, body: RejectIn) -> dict:
    with api() as conn:
        return lessons.reject(conn, lesson_id, body.reason)


@router.get("/lessons/{lesson_id}/issues")
def list_issues(lesson_id: int) -> dict:
    with api() as conn:
        return {"items": lessons.list_issues(conn, lesson_id)}


@router.post("/lessons/{lesson_id}/issues")
def add_issue(lesson_id: int, body: IssueIn) -> dict:
    with api() as conn:
        return lessons.add_issue(conn, lesson_id, issue_type=body.issue_type, start_s=body.start_s,
                                 end_s=body.end_s, note=body.note)


@router.delete("/lessons/{lesson_id}/issues/{issue_id}")
def delete_issue(lesson_id: int, issue_id: int) -> dict:
    with api() as conn:
        lessons.delete_issue(conn, lesson_id, issue_id)
        return {"ok": True}
