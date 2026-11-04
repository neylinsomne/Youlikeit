"""Lecciones (recetas de supercut): armar, editar, guion con IA, render y video."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from apps.studio.auth import require_token
from apps.studio.errors import NotFound, api
from apps.studio.routers.jobs import submit
from apps.supercut import lessons, planner, script

router = APIRouter(prefix="/api", tags=["lessons"], dependencies=[Depends(require_token)])


class LessonIn(BaseModel):
    spec: str = Field(min_length=3, max_length=100)
    title: str | None = Field(default=None, max_length=200)
    max_works: int = Field(default=5, ge=2, le=10)
    max_duration_s: float = Field(default=58, ge=10, le=180)
    lang: Literal["es", "en"] = "es"
    min_confidence: float = Field(default=0.5, ge=0, le=1)


class ItemIn(BaseModel):
    moment_id: int
    in_ms: int = Field(ge=0)
    out_ms: int = Field(ge=1)
    caption: str | None = Field(default=None, max_length=300)


class SegmentIn(BaseModel):
    idx: int = Field(ge=0)
    narration: str = Field(max_length=1000)
    caption: str = Field(max_length=300)


class ScriptBody(BaseModel):
    hook: str = Field(max_length=500)
    outro: str = Field(max_length=500)
    segments: list[SegmentIn]


class LessonPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    items: list[ItemIn] | None = Field(default=None, max_length=20)
    script: ScriptBody | None = None


class ScriptIn(BaseModel):
    provider: str | None = None


class RenderIn(BaseModel):
    narrate: bool | None = None


@router.post("/lessons")
def create_lesson(body: LessonIn) -> dict:
    with api() as conn:
        return planner.plan_lesson(conn, body.spec, title=body.title, max_works=body.max_works,
                                   max_duration_s=body.max_duration_s, lang=body.lang,
                                   min_confidence=body.min_confidence)


@router.get("/lessons")
def list_lessons(status: str | None = None) -> dict:
    with api() as conn:
        return {"items": lessons.list_lessons(conn, status or None)}


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: int) -> dict:
    with api() as conn:
        return lessons.get_lesson(conn, lesson_id)


@router.patch("/lessons/{lesson_id}")
def patch_lesson(lesson_id: int, body: LessonPatch) -> dict:
    with api() as conn:
        return lessons.update_lesson(
            conn, lesson_id, title=body.title,
            items=[i.model_dump() for i in body.items] if body.items is not None else None,
            script=body.script.model_dump() if body.script is not None else None)


@router.post("/lessons/{lesson_id}/script")
def generate_script(lesson_id: int, body: ScriptIn | None = None) -> dict:
    with api() as conn:
        return script.generate_script(conn, lesson_id, provider=(body.provider if body else None) or None)


@router.post("/lessons/{lesson_id}/render")
def render(lesson_id: int, request: Request, body: RenderIn | None = None) -> dict:
    with api() as conn:
        return submit(request, conn, "render", {"lesson_id": lesson_id, "narrate": body.narrate if body else None})


@router.get("/lessons/{lesson_id}/video")
def video(lesson_id: int) -> FileResponse:
    with api() as conn:
        lessons.get_lesson(conn, lesson_id)                      # 404 si la lección no existe
        path = lessons.video_path(lesson_id)                     # ruta derivada del id, no de la DB
        if not path.is_file():
            raise NotFound("La lección todavía no tiene video")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-cache"})
