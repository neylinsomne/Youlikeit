"""Modelos del dominio media (sin dependencias pesadas)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Estados de derechos. Solo `public_domain`, `open_license` y `owned` se usan
# para producir; `unknown` / `restricted` quedan indexables pero bloqueados.
RIGHTS_PUBLIC_DOMAIN = "public_domain"
RIGHTS_OPEN = "open_license"          # CC BY / CC BY-SA (permiten derivados comerciales)
RIGHTS_OWNED = "owned"                # biblioteca propia del usuario (E:, Jellyfin)
RIGHTS_RESTRICTED = "restricted"      # CC NC / ND u otra restricción
RIGHTS_UNKNOWN = "unknown"

USABLE_RIGHTS = frozenset({RIGHTS_PUBLIC_DOMAIN, RIGHTS_OPEN, RIGHTS_OWNED})


def media_cache_dir(*parts: str) -> Path:
    """data/media_cache/<parts> respetando DATA_DIR (como core.config.load_settings)."""
    return Path(os.getenv("DATA_DIR", "data"), "media_cache", *parts)


@dataclass
class MediaCandidate:
    """Un archivo de video que un proveedor puede servir para una obra.

    `master_uri` es la mejor calidad (de ahí salen los clips por rango);
    `proxy_uri` es una versión liviana con la MISMA línea de tiempo, para
    análisis (transcripción, cortes de plano). Pueden ser el mismo archivo.
    """
    provider: str
    external_id: str
    title: str
    year: int | None = None
    kind: str = "movie"                 # movie | episode
    season: int | None = None
    episode: int | None = None
    master_uri: str = ""
    proxy_uri: str = ""
    duration_ms: int = 0
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    rights: str = RIGHTS_UNKNOWN
    license_url: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.rights in USABLE_RIGHTS


@dataclass
class Mezzanine:
    """Segmento bajado por rango, con timestamps ORIGINALES del master.

    `start_ms`/`end_ms` son reales (el corte -c copy arranca en el keyframe
    anterior al pedido). El corte exacto al frame se hace después, una sola
    vez, en el render: offset = requested_start_ms - start_ms.
    """
    path: str
    start_ms: int
    end_ms: int
    requested_start_ms: int
    requested_end_ms: int
    bytes_transferred: int | None = None
    cached: bool = False

    @property
    def offset_ms(self) -> int:
        return self.requested_start_ms - self.start_ms
