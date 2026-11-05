"""Proveedores de video intercambiables.

El pipeline nunca sabe de dónde viene el video: pide candidatos para una obra
y recibe `MediaCandidate` con `master_uri` (calidad, se corta por rangos) y
`proxy_uri` (liviano, misma línea de tiempo, para analizar).

Proveedores incluidos:
  - archive_org   Internet Archive (feature_films / moviesandfilms), con capa de derechos
  - local         biblioteca propia en MOVIES_DIR (E:), con detección de episodios
  - stremio       un addon de Stremio (STREMIO_ADDON_URL): solo enlaces http de archive.org
                  (re-verificados) o de tus hosts (STREMIO_OWN_HOSTS); torrents y debrid fuera

`apps.content.movie_source` (Torrentio + qBittorrent) NO es un proveedor de
este dominio y no se importa desde acá.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol, runtime_checkable

from apps.media.models import MediaCandidate, SourceUnavailable

log = logging.getLogger(__name__)
PROVIDERS = ("local", "archive_org", "stremio")


@runtime_checkable
class SourceProvider(Protocol):
    name: str

    def search(self, title: str, year: int | None = None, *, limit: int = 10) -> list[MediaCandidate]:
        """Candidatos para una obra, mejores primero."""
        ...


def get_provider(name: str, **kwargs) -> SourceProvider:
    if name in ("archive_org", "ia"):
        from apps.media.archive_org import ArchiveOrgProvider
        return ArchiveOrgProvider(**kwargs)
    if name in ("local", "library"):
        from apps.media.local_library import LocalLibraryProvider
        return LocalLibraryProvider(**kwargs)
    if name in ("stremio", "addon"):
        from apps.media.stremio_addon import StremioAddonProvider
        return StremioAddonProvider(**kwargs)
    raise ValueError(f"Proveedor desconocido: {name!r} (usa {' | '.join(PROVIDERS)})")


def default_providers() -> list[str]:
    """local + archive_org siempre; stremio solo si hay STREMIO_ADDON_URL."""
    names = ["local", "archive_org"]
    if (os.getenv("STREMIO_ADDON_URL") or "").strip():
        names.append("stremio")
    return names


def search_all(title: str, year: int | None = None, *, providers: list[str] | None = None,
               only_usable: bool = True, limit: int = 10,
               errors: list[str] | None = None) -> list[MediaCandidate]:
    """Busca en varios proveedores; por defecto solo devuelve candidatos con derechos usables.

    Un proveedor no disponible (USB desconectada, addon caído) no tumba la búsqueda:
    se salta y, si se pasa `errors`, se anota ahí el motivo para mostrarlo.
    """
    out: list[MediaCandidate] = []
    seen: set[tuple[str, str]] = set()
    for name in providers or default_providers():
        try:
            found = get_provider(name).search(title, year, limit=limit)
        except (FileNotFoundError, SourceUnavailable) as e:  # p.ej. MOVIES_DIR en una USB desconectada
            log.warning("Proveedor %s no disponible: %s", name, e)
            if errors is not None:
                errors.append(f"{name}: {e}")
            continue
        for c in found:
            # stremio puede devolver un ítem de archive.org que ya salió en archive_org
            if (c.usable or not only_usable) and (c.provider, c.external_id) not in seen:
                seen.add((c.provider, c.external_id))
                out.append(c)
    return out
