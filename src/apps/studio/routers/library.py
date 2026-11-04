"""Biblioteca: obras, assets, búsqueda en proveedores e ingesta."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.studio import serializers
from apps.studio.auth import require_token
from apps.studio.errors import NotFound, api

router = APIRouter(prefix="/api", tags=["library"], dependencies=[Depends(require_token)])
PROVIDERS = ("local", "archive_org")


class SearchIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=1880, le=2100)
    providers: list[str] | None = None
    all_rights: bool = False


class IngestIn(BaseModel):
    provider: str
    external_id: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=200)
    year: int | None = Field(default=None, ge=1880, le=2100)


def _check_providers(names: list[str] | None) -> list[str] | None:
    bad = [n for n in names or [] if n not in PROVIDERS]
    if bad:
        raise HTTPException(422, f"proveedor desconocido: {bad} (usa {', '.join(PROVIDERS)})")
    return names


@router.get("/works")
def list_works() -> dict:
    with api() as conn:
        return {"items": serializers.works(conn)}


@router.get("/assets")
def list_assets(work_id: int | None = None) -> dict:
    with api() as conn:
        return {"items": serializers.assets(conn, work_id)}


@router.post("/media/search")
def media_search(body: SearchIn) -> dict:
    from apps.media.sources import search_all
    providers = _check_providers(body.providers)
    try:
        cands = search_all(body.title, body.year, providers=providers, only_usable=not body.all_rights, limit=10)
    except Exception as e:  # noqa: BLE001 — red/IA caída: falla externa
        raise HTTPException(502, f"Búsqueda falló: {type(e).__name__}: {e}"[:500]) from e
    return {"items": [serializers.candidate(c) for c in cands]}


def _resolve(provider: str, external_id: str):
    from apps.media.sources import get_provider
    prov = get_provider(provider)
    try:
        if provider == "archive_org":
            return prov.get_item(external_id)
        return next((c for c in prov.scan() if c.external_id == external_id), None)
    except FileNotFoundError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{provider}: {type(e).__name__}: {e}"[:500]) from e


@router.post("/media/ingest")
def media_ingest(body: IngestIn) -> dict:
    from apps.media.indexer import register_candidate
    _check_providers([body.provider])
    cand = _resolve(body.provider, body.external_id)
    with api() as conn:
        if cand is None:
            raise NotFound(f"No encontrado en {body.provider}: {body.external_id}")
        if not cand.usable:
            raise HTTPException(409, f"Derechos '{cand.rights}' ({cand.license_url or 'sin licencia'}): no usable")
        asset_id = register_candidate(conn, cand, work_title=body.title, work_year=body.year)
        return serializers.asset(conn, asset_id)
