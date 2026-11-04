"""Momentos: vocabulario, listado paginado, búsqueda entre obras, edición manual y preview."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from apps.moments import vocab
from apps.studio import serializers
from apps.studio.auth import require_token
from apps.studio.errors import api

router = APIRouter(prefix="/api", tags=["moments"], dependencies=[Depends(require_token)])
MOMENT_STATUSES = ("candidate", "labeled", "rejected")


class LabelRef(BaseModel):
    dimension: str
    value: str


class MomentPatch(BaseModel):
    status: str | None = None
    add_labels: list[LabelRef] | None = None
    remove_labels: list[LabelRef] | None = None


@router.get("/vocab")
def get_vocab() -> dict:
    return serializers.vocab_json()


@router.get("/moments")
def list_moments(asset_id: int | None = None, work_id: int | None = None, dimension: str | None = None,
                 value: str | None = None, min_conf: float = Query(0.0, ge=0, le=1), status: str | None = None,
                 q: str | None = Query(None, max_length=200), page: int = Query(1, ge=1),
                 per_page: int = Query(50, ge=1, le=200)) -> dict:
    if dimension and dimension not in vocab.DIMENSIONS:
        raise HTTPException(422, f"dimension inválida (usa {', '.join(vocab.DIMENSIONS)})")
    if status and status not in MOMENT_STATUSES:
        raise HTTPException(422, f"status inválido (usa {', '.join(MOMENT_STATUSES)})")
    with api() as conn:
        return serializers.query_moments(conn, asset_id=asset_id, work_id=work_id, dimension=dimension or None,
                                         value=value or None, min_conf=min_conf, status=status or None,
                                         q=q or None, page=page, per_page=per_page)


@router.get("/moments/find")
def find(spec: str, limit: int = Query(6, ge=1, le=20), min_works: int = Query(3, ge=1, le=20),
         per_work: int = Query(1, ge=1, le=10), min_confidence: float = Query(0.5, ge=0, le=1)) -> dict:
    from apps.moments.retrieval import find_moments
    with api() as conn:
        dimension, value = vocab.parse_spec(spec)                     # ValueError → 422
        res = find_moments(conn, dimension, value, limit=limit, min_works=min_works, max_per_work=per_work,
                           min_confidence=min_confidence)
        extra = {r["id"]: {"score": r["score"], "confidence": r["confidence"]} for r in res["items"]}
        items = [{**m, **extra[m["id"]]} for m in serializers.moments_by_ids(conn, [r["id"] for r in res["items"]])]
        out = {"dimension": dimension, "value": value, "items": items, "distinct_works": res["distinct_works"],
               "candidates": res["candidates"]}
        if res.get("warning"):
            out["warning"] = res["warning"]
        return out


@router.get("/moments/{moment_id}")
def get_moment(moment_id: int) -> dict:
    with api() as conn:
        return serializers.moment(conn, moment_id)


def _check_label(lab: LabelRef) -> None:
    if lab.dimension not in vocab.DIMENSIONS:
        raise ValueError(f"dimension inválida: {lab.dimension!r}")
    if lab.value not in vocab.ids(lab.dimension):
        raise ValueError(f"{lab.value!r} no existe en {lab.dimension}")


@router.patch("/moments/{moment_id}")
def patch_moment(moment_id: int, body: MomentPatch) -> dict:
    from apps.moments.schema import add_label
    if body.status is not None and body.status not in ("rejected", "candidate"):
        raise HTTPException(422, "status solo puede ser rejected o candidate")
    with api() as conn:
        serializers.moment(conn, moment_id)                          # 404 si no existe
        for lab in (body.add_labels or []) + (body.remove_labels or []):
            _check_label(lab)
        for lab in body.remove_labels or []:
            conn.execute("DELETE FROM moment_labels WHERE moment_id = ? AND dimension = ? AND value = ?",
                         (moment_id, lab.dimension, lab.value))
        for lab in body.add_labels or []:
            add_label(conn, moment_id, lab.dimension, lab.value, 1.0, "manual", commit=False)
        # Volver a detectar momentos BORRA los 'candidate' (y sus etiquetas). Por eso un momento
        # con etiquetas de la IA o manuales nunca queda como 'candidate': restaurarlo lo devuelve
        # a 'labeled', y etiquetar a mano un candidato lo protege.
        has_labels = conn.execute(
            "SELECT (SELECT labeled_by FROM moments WHERE id = ?) IS NOT NULL OR EXISTS("
            "SELECT 1 FROM moment_labels WHERE moment_id = ? AND source = 'manual')",
            (moment_id, moment_id)).fetchone()[0]
        if body.status is not None:
            status = "labeled" if body.status == "candidate" and has_labels else body.status
            conn.execute("UPDATE moments SET status = ? WHERE id = ?", (status, moment_id))
        elif body.add_labels:
            conn.execute("UPDATE moments SET status = 'labeled', labeled_by = COALESCE(labeled_by, 'manual') "
                         "WHERE id = ? AND status = 'candidate'", (moment_id,))
        conn.commit()
        return serializers.moment(conn, moment_id)


@router.get("/moments/{moment_id}/preview")
def moment_preview(moment_id: int) -> FileResponse:
    from apps.supercut.preview import moment_preview as make
    with api() as conn:
        path = make(conn, moment_id)                                 # MomentNotFound → 404, FFmpegError → 502
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})
