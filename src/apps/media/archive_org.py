"""Proveedor Internet Archive (cine de dominio público / licencias abiertas).

- Búsqueda: advancedsearch.php (colecciones de cine, orden por descargas).
- Archivos: /metadata/{identifier} → lista de `files` con source original/derivative.
- master = original de video de mayor calidad (prefiere contenedores con índice:
  mp4/mkv permiten saltar por rangos sin leer el archivo).
- proxy = derivado MÁS LIVIANO de ESE master (misma línea de tiempo). Nunca un
  derivado de otra versión: los cortes DVD/1080p pueden estar desfasados.
- derechos: licenseurl/rights del ítem → public_domain | open_license |
  restricted (CC NC/ND) | unknown. Solo los dos primeros se usan para producir.
"""
from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from urllib.parse import quote

from apps.media.models import (
    RIGHTS_OPEN,
    RIGHTS_PUBLIC_DOMAIN,
    RIGHTS_RESTRICTED,
    RIGHTS_UNKNOWN,
    MediaCandidate,
)
from utils.http_client import api_get

log = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{name}"

FILM_COLLECTIONS = ("feature_films", "moviesandfilms", "classic_tv", "television")
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg", ".m2ts", ".ts",
              ".ogv", ".vob"}
# Contenedores con índice (moov / Cues): ffmpeg salta directo al rango pedido.
_CONTAINER_PREF = {".mp4": 3, ".m4v": 3, ".mov": 3, ".mkv": 3, ".webm": 2, ".avi": 1, ".ogv": 1}
_MAX_USEFUL_HEIGHT = 1080
# Contenedores SIN índice: ffmpeg no puede saltar por rangos (visto con un MPEG-PS de DVD
# de IA que declaraba 5 s de duración para 90 min). Se prefiere un derivado indexado.
_UNINDEXED = {".mpeg", ".mpg", ".ts", ".m2ts", ".vob"}


def classify_rights(license_url: str | None, rights_text: str | None = None) -> str:
    """Clasifica derechos de un ítem de IA. Conservador: ante la duda, unknown."""
    url = (license_url or "").lower()
    text = (rights_text or "").lower()
    if "publicdomain" in url or "/zero/" in url or "public domain" in text:
        return RIGHTS_PUBLIC_DOMAIN
    m = re.search(r"creativecommons\.org/licenses/([a-z\-]+)/", url)
    if m:
        terms = m.group(1).split("-")
        if "nc" in terms or "nd" in terms:
            return RIGHTS_RESTRICTED
        return RIGHTS_OPEN
    return RIGHTS_UNKNOWN


def _ext(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _length_s(f: dict) -> float:
    """`length` viene como '5752.82' o '95:51' / '01:35:06'."""
    raw = str(f.get("length") or "")
    if ":" in raw:
        total = 0.0
        for part in raw.split(":"):
            total = total * 60 + _f(part)
        return total
    return _f(raw)


def _is_video(f: dict) -> bool:
    return _ext(f.get("name", "")) in VIDEO_EXTS and "gif" not in (f.get("format") or "").lower()


def pick_master_and_proxy(files: list[dict]) -> tuple[dict | None, dict | None]:
    """Elige (master, proxy) de la lista `files` de la metadata API."""
    originals = [f for f in files if f.get("source") == "original" and _is_video(f)]
    if not originals:
        # Ítems viejos: a veces todo es "derivative"; tomamos el más pesado como master.
        originals = [f for f in files if _is_video(f)]
    if not originals:
        return None, None

    def master_key(f: dict):
        h = int(_f(f.get("height")))
        length = _length_s(f) or 1.0
        bitrate = _f(f.get("size")) * 8 / length          # bits/s
        return (min(h, _MAX_USEFUL_HEIGHT), _CONTAINER_PREF.get(_ext(f["name"]), 0),
                min(bitrate, 25e6))

    original = max(originals, key=master_key)
    derived = [f for f in files
               if f.get("source") == "derivative" and f.get("original") == original["name"]
               and _is_video(f) and _ext(f["name"]) in {".mp4", ".m4v", ".mkv", ".webm"}]
    proxy = min(derived, key=lambda f: _f(f.get("size"))) if derived else None
    master = original
    if _ext(original["name"]) in _UNINDEXED:
        # Derivado h.264 del MISMO original (misma línea de tiempo) con resolución equivalente.
        same_res = [f for f in derived if _f(f.get("height")) >= 0.9 * _f(original.get("height"))
                    and "512kb" not in (f.get("format") or "").lower()]
        if same_res:
            master = max(same_res, key=lambda f: _f(f.get("size")))
    return master, proxy


def _year(md: dict) -> int | None:
    for key in ("year", "date"):
        m = re.match(r"(\d{4})", str(md.get(key) or ""))
        if m:
            return int(m.group(1))
    return None


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def candidate_from_metadata(meta: dict) -> MediaCandidate | None:
    """Convierte la respuesta de /metadata/{id} en un MediaCandidate."""
    md = meta.get("metadata") or {}
    identifier = _first(md.get("identifier"))
    if not identifier:
        return None
    master, proxy = pick_master_and_proxy(meta.get("files") or [])
    if not master:
        return None

    def url(f: dict) -> str:
        return DOWNLOAD_URL.format(identifier=identifier, name=quote(f["name"]))

    license_url = _first(md.get("licenseurl")) or ""
    runtime_s = _length_s({"length": _first(md.get("runtime"))})
    master_s = _length_s(master)
    # Ítems de DVD partidos (VTS_01_1.mp4, VTS_01_2.mp4…): el master es solo un trozo.
    partial = bool(runtime_s and master_s and master_s < 0.8 * runtime_s)
    return MediaCandidate(
        provider="archive_org",
        external_id=identifier,
        title=str(_first(md.get("title")) or identifier),
        year=_year(md),
        master_uri=url(master),
        proxy_uri=url(proxy) if proxy else url(master),
        duration_ms=int(_length_s(master) * 1000),
        width=int(_f(master.get("width"))),
        height=int(_f(master.get("height"))),
        size_bytes=int(_f(master.get("size"))),
        rights=classify_rights(license_url, _first(md.get("rights"))),
        license_url=license_url,
        extra={
            "master_file": master["name"],
            "proxy_file": proxy["name"] if proxy else None,
            "proxy_size": int(_f(proxy.get("size"))) if proxy else None,
            "collections": md.get("collection"),
            "language": _first(md.get("language")),
            "runtime_s": runtime_s or None,
            "partial": partial,
        },
    )


def build_search_query(title: str, year: int | None = None) -> str:
    safe = re.sub(r'[:"()\[\]{}^~*?\\]', " ", title).strip()
    colls = " OR ".join(f"collection:{c}" for c in FILM_COLLECTIONS)
    q = f'title:({safe}) AND mediatype:movies AND ({colls})'
    if year:
        q += f" AND year:[{year - 1} TO {year + 1}]"
    return q


class ArchiveOrgProvider:
    name = "archive_org"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def search_items(self, title: str, year: int | None = None, *, limit: int = 10) -> list[dict]:
        params = {
            "q": build_search_query(title, year),
            "fl[]": ["identifier", "title", "year", "downloads", "licenseurl"],
            "sort[]": "downloads desc",
            "rows": limit,
            "output": "json",
        }
        data = api_get(SEARCH_URL, params=params, timeout=self.timeout, service="archive_org")
        if not isinstance(data, dict):
            return []
        return list((data.get("response") or {}).get("docs") or [])

    def get_item(self, identifier: str) -> MediaCandidate | None:
        meta = api_get(METADATA_URL.format(identifier=quote(identifier)),
                       timeout=self.timeout, service="archive_org")
        if not isinstance(meta, dict) or not meta.get("files"):
            log.warning("IA: ítem sin archivos o inexistente: %s", identifier)
            return None
        return candidate_from_metadata(meta)

    def search(self, title: str, year: int | None = None, *, limit: int = 10) -> list[MediaCandidate]:
        out = []
        for doc in self.search_items(title, year, limit=limit):
            cand = self.get_item(doc["identifier"])
            if cand:
                cand.extra["downloads"] = doc.get("downloads")
                out.append(cand)
        # Usables primero, luego más altura (calidad) y popularidad.
        out.sort(key=lambda c: (c.usable, not c.extra.get("partial"),
                                min(c.height, _MAX_USEFUL_HEIGHT),
                                c.extra.get("downloads") or 0), reverse=True)
        return out
