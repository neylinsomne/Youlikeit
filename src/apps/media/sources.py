"""Proveedores de video intercambiables.

El pipeline nunca sabe de dónde viene el video: pide candidatos para una obra
y recibe `MediaCandidate` con `master_uri` (calidad, se corta por rangos) y
`proxy_uri` (liviano, misma línea de tiempo, para analizar).

Proveedores incluidos:
  - archive_org   Internet Archive (feature_films / moviesandfilms), con capa de derechos
  - local         biblioteca propia en MOVIES_DIR (E:), con detección de episodios

`apps.content.movie_source` (Torrentio + qBittorrent) NO es un proveedor de
este dominio y no se importa desde acá.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from apps.media.models import MediaCandidate


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
    raise ValueError(f"Proveedor desconocido: {name!r} (usa archive_org | local)")


def search_all(title: str, year: int | None = None, *, providers: list[str] | None = None,
               only_usable: bool = True, limit: int = 10) -> list[MediaCandidate]:
    """Busca en varios proveedores; por defecto solo devuelve candidatos con derechos usables."""
    out: list[MediaCandidate] = []
    for name in providers or ["local", "archive_org"]:
        try:
            found = get_provider(name).search(title, year, limit=limit)
        except FileNotFoundError:
            continue  # p.ej. MOVIES_DIR en una USB desconectada
        out.extend(c for c in found if c.usable or not only_usable)
    return out
