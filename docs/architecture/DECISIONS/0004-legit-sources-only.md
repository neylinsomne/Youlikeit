# 0004 · Solo fuentes legítimas; Torrentio/qBittorrent congelado

- **Status:** accepted
- **Date:** 2026-11-03 (documentada retroactivamente el 2026-11-04)
- **Deciders:** owner del repo + agente de desarrollo

## Context and Problem Statement

Las lecciones necesitan escenas de muchas películas. El repo ya tenía un conector Torrentio +
qBittorrent (`src/apps/content/movie_source.py`) del producto anterior, y se pidió extenderlo para bajar
solo segmentos de películas con copyright. ¿De dónde sale el material de las lecciones?

## Decision Drivers

- Publicar en TikTok y YouTube sin reclamos de derechos ni riesgo legal para el creador.
- Poder demostrar el origen y la licencia de cada escena (revisión de TikTok, descripción en YouTube).
- Cine de los 70-80 disponible en dominio público en Internet Archive.

## Considered Options

1. Extender Torrentio/qBittorrent para bajar segmentos de cualquier película.
2. **Solo fuentes con derechos verificables**: Internet Archive (dominio público o licencia abierta),
   y la biblioteca local del creador (`MOVIES_DIR`, copias propias). Jellyfin está previsto en el
   esquema (`provider = jellyfin`) pero no tiene proveedor implementado.

## Decision Outcome

Elegida la **opción 2**. `apps/media` clasifica los derechos de cada copia (`public_domain`,
`open_license`, `owned`, `unknown`…) y solo las tres primeras son usables. La capa de derechos se
aplica en la búsqueda, el registro, la búsqueda entre obras, el plan, el render y el catálogo del sitio
(que por defecto solo publica dominio público y licencia abierta). `movie_source.py` queda congelado: no
se extiende y los dominios nuevos no lo importan.

### Consequences

**Buenas:**
- Cada lección se puede justificar escena por escena.
- La extracción por rango HTTP de Internet Archive evita bajar películas completas.

**Malas / trade-offs:**
- Catálogo limitado a lo que es de dominio público o propio; ante la duda, `unknown` (no usable).
- Copias `owned` sirven para producir, pero el sitio no las publica salvo `--include-owned`.

## More Information

- [SUPERCUT_ETL.md § Media](../SUPERCUT_ETL.md#1-media-extract--srcappsmedia)
- [MEDIA_AGENT.md](../../agents/MEDIA_AGENT.md)
