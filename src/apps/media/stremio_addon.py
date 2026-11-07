"""Proveedor `stremio`: usa un addon de Stremio como catálogo de fuentes.

Se conecta con la URL del manifest (`STREMIO_ADDON_URL=https://host/.../manifest.json`),
no con un ID. Los IDs salen después: el catálogo del addon (o Cinemeta, si el addon acepta
IDs de IMDb `tt...`) devuelve un ID por obra, y con ese ID se piden los streams.

Protocolo (stremio-addon-sdk/docs/protocol.md):
  GET {base}/manifest.json
  GET {base}/catalog/movie/{catalog_id}/search={q}.json  -> {"metas": [{id, name, releaseInfo}]}
  GET {base}/stream/movie/{id}.json                      -> {"streams": [{url | infoHash | ...}]}

Reglas, iguales para cualquier addon (propio o ajeno):
  - Solo streams `url` http(s). Torrents (infoHash/magnet), ytId y externalUrl se descartan.
  - Hosts de debrid se descartan siempre, aunque estén en STREMIO_OWN_HOSTS.
  - archive.org -> se re-verifica con ArchiveOrgProvider (derechos y master/proxy reales):
    el candidato que sale es de `archive_org`, no del addon.
  - Hosts de STREMIO_OWN_HOSTS (tu Jellyfin, NAS o servidor) -> `owned`, como la biblioteca de E:.
  - Cualquier otro host -> `unknown`: se ve con "Ver todos los derechos", no se registra.

La URL del manifest puede llevar configuración (incluso claves) en el path: nunca se
registra completa en logs ni se devuelve al front; solo el host.
"""
from __future__ import annotations

import logging
import os
import re
from collections import Counter
from collections.abc import Iterable
from urllib.parse import quote, unquote, urlparse

import requests

from apps.media.models import RIGHTS_OWNED, RIGHTS_UNKNOWN, MediaCandidate, SourceUnavailable

log = logging.getLogger(__name__)

CINEMETA_URL = "https://v3-cinemeta.strem.io"
TYPES = ("movie",)                     # series: pendiente (los streams van por episodio, tt..:S:E)
ARCHIVE_HOSTS = ("archive.org",)
DEBRID_HOSTS = ("real-debrid.com", "rdeb.io", "alldebrid.com", "premiumize.me", "debrid-link.com",
                "debrid-link.fr", "torbox.app", "offcloud.com", "put.io", "easydebrid.com")
_UA = {"User-Agent": "youlikeit-media/1.0"}
_YEAR = re.compile(r"(1[89]\d\d|20\d\d)")


class StremioAddonError(SourceUnavailable):
    """Addon sin configurar, caído o con un manifest inválido."""


def addon_base_url(manifest_url: str | None = None) -> str:
    """URL base del addon (sin /manifest.json). Acepta también stremio://."""
    url = (manifest_url if manifest_url is not None else os.getenv("STREMIO_ADDON_URL") or "").strip()
    if not url:
        raise StremioAddonError("STREMIO_ADDON_URL vacío (pega la URL del manifest de tu addon en el .env)")
    if url.startswith("stremio://"):
        url = "https://" + url[len("stremio://"):]
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise StremioAddonError("STREMIO_ADDON_URL debe ser http(s)://.../manifest.json")
    url = url.split("?", 1)[0].rstrip("/")
    return url[: -len("/manifest.json")] if url.endswith("/manifest.json") else url


def addon_host(manifest_url: str | None = None) -> str | None:
    """Solo el host del addon (lo único que se muestra o se registra en logs)."""
    try:
        return urlparse(addon_base_url(manifest_url)).hostname
    except StremioAddonError:
        return None


def own_hosts() -> tuple[str, ...]:
    """STREMIO_OWN_HOSTS: hosts de tu propia biblioteca, separados por coma (sin puerto)."""
    return tuple(h.strip().lower() for h in (os.getenv("STREMIO_OWN_HOSTS") or "").split(",") if h.strip())


def _host_in(host: str, domains: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def _archive_identifier(path: str) -> str | None:
    parts = [unquote(p) for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] in ("download", "details", "embed"):
        return parts[1]
    if "items" in parts[:-1]:                    # ia8xxxx.us.archive.org/<n>/items/<identifier>/<file>
        return parts[parts.index("items") + 1]
    return None


def classify_stream(stream: dict, own: Iterable[str] = ()) -> tuple[str, str]:
    """-> (kind, value). kind: skip (value = motivo) | archive (identifier) | owned | unknown (url)."""
    if not isinstance(stream, dict):
        return "skip", "formato inválido"
    if stream.get("infoHash"):
        return "skip", "torrent"
    url = str(stream.get("url") or "").strip()
    if not url:
        return "skip", "sin url directa"
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return "skip", "torrent" if p.scheme == "magnet" else "esquema no http"
    host = p.hostname.lower()
    if _host_in(host, DEBRID_HOSTS):
        return "skip", "debrid"
    if _host_in(host, ARCHIVE_HOSTS):
        ident = _archive_identifier(p.path)
        return ("archive", ident) if ident else ("skip", "archive.org sin identifier")
    if _host_in(host, own):
        return "owned", url
    return "unknown", url


def meta_year(meta: dict) -> int | None:
    m = _YEAR.search(str(meta.get("releaseInfo") or meta.get("year") or ""))
    return int(m.group(1)) if m else None


class StremioAddonProvider:
    name = "stremio"

    def __init__(self, manifest_url: str | None = None, *, timeout: int = 20,
                 own: Iterable[str] | None = None):
        self.base = addon_base_url(manifest_url)
        self.host = urlparse(self.base).hostname
        self.timeout = timeout
        self.own = tuple(h.lower() for h in own) if own is not None else own_hosts()
        self._manifest: dict | None = None

    # ── HTTP ────────────────────────────────────────────────────────────

    def _get_json(self, url: str, who: str) -> dict | None:
        """GET -> dict, None si 404. Los errores nombran solo el host (la URL puede llevar claves)."""
        try:
            r = requests.get(url, timeout=self.timeout, headers=_UA)
        except requests.RequestException as e:
            raise StremioAddonError(f"{who} no responde ({type(e).__name__})") from None
        if r.status_code == 404:
            return None
        if not r.ok:
            raise StremioAddonError(f"{who} respondió HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise StremioAddonError(f"{who} no devolvió JSON") from None
        return data if isinstance(data, dict) else None

    def _addon(self, path: str) -> dict | None:
        return self._get_json(f"{self.base}/{path}", f"El addon ({self.host})")

    # ── manifest ────────────────────────────────────────────────────────

    def manifest(self) -> dict:
        if self._manifest is None:
            m = self._addon("manifest.json")
            if not m or not m.get("id"):
                raise StremioAddonError(f"El addon ({self.host}) no tiene un manifest.json válido")
            self._manifest = m
        return self._manifest

    def search_catalogs(self) -> list[tuple[str, str]]:
        """(type, catalog_id) de los catálogos que aceptan búsqueda por texto."""
        out = []
        for c in self.manifest().get("catalogs") or []:
            if not isinstance(c, dict) or c.get("type") not in TYPES or not c.get("id"):
                continue
            names = {e.get("name") for e in c.get("extra") or [] if isinstance(e, dict)}
            names |= set(c.get("extraSupported") or [])
            if "search" in names:
                out.append((c["type"], c["id"]))
        return out

    def accepts_imdb(self) -> bool:
        """¿Sirve streams para IDs de IMDb (tt...)? Entonces se puede buscar el ID en Cinemeta."""
        m = self.manifest()
        for r in m.get("resources") or []:
            if r == "stream":
                prefixes = m.get("idPrefixes")
            elif isinstance(r, dict) and r.get("name") == "stream":
                prefixes = r.get("idPrefixes", m.get("idPrefixes"))
            else:
                continue
            if prefixes is None or any(str(p).startswith("tt") for p in prefixes):
                return True
        return False

    # ── búsqueda ────────────────────────────────────────────────────────

    def find_metas(self, title: str, year: int | None = None, *, limit: int = 10) -> list[dict]:
        q = quote(title.strip(), safe="")
        metas: list[dict] = []
        catalogs = self.search_catalogs()
        for type_, cat_id in catalogs:
            data = self._addon(f"catalog/{type_}/{quote(cat_id, safe='')}/search={q}.json") or {}
            metas += [{**m, "type": m.get("type") or type_} for m in data.get("metas") or []
                      if isinstance(m, dict) and m.get("id")]
        if not catalogs and self.accepts_imdb():
            data = self._get_json(f"{CINEMETA_URL}/catalog/movie/top/search={q}.json", "Cinemeta") or {}
            metas += [{**m, "type": "movie"} for m in data.get("metas") or []
                      if isinstance(m, dict) and str(m.get("id", "")).startswith("tt")]
        out, seen = [], set()
        for m in metas:
            y = meta_year(m)
            if (m["type"], m["id"]) in seen or (year and y and abs(y - year) > 1):
                continue
            seen.add((m["type"], m["id"]))
            out.append(m)
        return out[:limit]

    def streams(self, type_: str, id_: str) -> list[dict]:
        data = self._addon(f"stream/{type_}/{quote(id_, safe=':')}.json") or {}
        return [s for s in data.get("streams") or [] if isinstance(s, dict)]

    def candidates_for(self, meta: dict) -> list[MediaCandidate]:
        """Streams de una obra -> candidatos (archive.org re-verificado, propios, desconocidos)."""
        type_, id_ = meta.get("type") or "movie", str(meta["id"])
        archive_ids: list[str] = []
        direct: dict[str, dict] = {}
        skipped: Counter[str] = Counter()
        for s in self.streams(type_, id_):
            kind, value = classify_stream(s, self.own)
            if kind == "skip":
                skipped[value] += 1
            elif kind == "archive":
                if value not in archive_ids:
                    archive_ids.append(value)
            else:
                direct.setdefault(kind, {**s, "url": value})
        if skipped:
            log.info("stremio %s: streams descartados %s", id_, dict(skipped))

        out: list[MediaCandidate] = []
        if archive_ids:
            from apps.media.archive_org import ArchiveOrgProvider
            ia = ArchiveOrgProvider(timeout=self.timeout)
            for ident in archive_ids:
                cand = ia.get_item(ident)
                if cand:
                    cand.extra["via"] = f"stremio:{self.host}"
                    out.append(cand)
        stream = direct.get("owned") or direct.get("unknown")
        if stream:
            out.append(self._direct(meta, type_, id_, stream, RIGHTS_OWNED if "owned" in direct else RIGHTS_UNKNOWN))
        return out

    def _direct(self, meta: dict, type_: str, id_: str, stream: dict, rights: str) -> MediaCandidate:
        hints = stream.get("behaviorHints") if isinstance(stream.get("behaviorHints"), dict) else {}
        try:
            size = int(hints.get("videoSize") or 0)
        except (TypeError, ValueError):
            size = 0
        return MediaCandidate(
            provider=self.name, external_id=f"{type_}/{id_}",
            title=str(meta.get("name") or id_), year=meta_year(meta),
            master_uri=stream["url"], proxy_uri=stream["url"], size_bytes=size, rights=rights,
            extra={"addon": self.manifest().get("name"), "host": urlparse(stream["url"]).hostname,
                   "master_file": hints.get("filename") or stream.get("name")},
        )

    def search(self, title: str, year: int | None = None, *, limit: int = 10) -> list[MediaCandidate]:
        out: list[MediaCandidate] = []
        seen: set[tuple[str, str]] = set()
        for meta in self.find_metas(title, year, limit=limit):
            for c in self.candidates_for(meta):
                if (c.provider, c.external_id) not in seen:
                    seen.add((c.provider, c.external_id))
                    out.append(c)
        out.sort(key=lambda c: c.usable, reverse=True)
        return out[:limit]

    def get_item(self, external_id: str) -> MediaCandidate | None:
        """external_id = "movie/<id>" (como lo devuelve search). Solo candidatos del addon."""
        type_, _, id_ = external_id.partition("/")
        if type_ not in TYPES or not id_:
            return None
        return next((c for c in self.candidates_for({"type": type_, "id": id_})
                     if c.provider == self.name), None)
