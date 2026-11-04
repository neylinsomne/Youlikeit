# 0005 · Railway solo para el sitio público; la producción es local

- **Status:** accepted (reemplaza a la decisión anterior "sin Railway")
- **Date:** 2026-11-03 / 2026-11-04 (documentada retroactivamente el 2026-11-04)
- **Deciders:** owner del repo

## Context and Problem Statement

TikTok exige un sitio público en un dominio verificado, con términos, privacidad y el redirect de
OAuth, y el token de TikTok tiene que vivir en algún servidor. El resto del pipeline (indexar, etiquetar,
renderizar) es pesado, usa la GPU local (RTX 5060, 8 GB) o APIs gratis, y trabaja con películas de la
biblioteca local. ¿Qué corre en la nube y qué en el PC del creador?

## Decision Drivers

- Costo cero.
- El token de TikTok y el client secret no deben estar en el PC del creador ni en el navegador.
- El video no debería pasar por un servidor (ancho de banda y almacenamiento).
- La API vieja (ex29) era insegura en red; la producción no necesita exponerse.

## Considered Options

1. Todo local, sin servidor (no cumple los requisitos de TikTok).
2. Todo en la nube (costo de GPU/almacenamiento, películas fuera del PC).
3. **Sitio público mínimo en Railway + estudio local en 127.0.0.1**, unidos por un puente autenticado.

## Decision Outcome

Elegida la **opción 3**. `web/` (FastAPI) corre en Railway con su propia `web.db` (tokens cifrados) y
expone `/api/studio/*` con `STUDIO_API_KEY`. El estudio (`src/apps/studio` + `frontend-react`) escucha
solo en `127.0.0.1`. Para publicar, el estudio pide un `upload_url` al puente y sube los bytes directo
a TikTok. YouTube se conecta desde el estudio con OAuth de app instalada (no pasa por Railway).

### Consequences

**Buenas:**
- El token de TikTok nunca sale de Railway; el video nunca pasa por Railway.
- El estudio no tiene superficie pública (token, guardia de origen, allowlist de archivos).

**Malas / trade-offs:**
- Un secreto compartido (`STUDIO_API_KEY`) que hay que mantener igual en dos lados.
- Publicar en TikTok requiere que el sitio esté arriba.

## More Information

- [STUDIO_API.md](../STUDIO_API.md), [web/README.md](../../../web/README.md),
  [SECURITY.md](../../operations/SECURITY.md)
