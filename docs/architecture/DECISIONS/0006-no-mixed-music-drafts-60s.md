# 0006 · Sin música mezclada, TikTok como borrador y lecciones de ≤ 60 s

- **Status:** accepted
- **Date:** 2026-11-03 (documentada retroactivamente el 2026-11-04)
- **Deciders:** owner del repo

## Context and Problem Statement

Una lección es un video vertical corto con escenas de varias películas, texto y narración. Faltaba
decidir tres cosas: si mezclar música, cómo publicar en TikTok y cuánto puede durar.

## Decision Drivers

- La música en tendencia y con licencia para la plataforma solo se puede elegir dentro de cada app.
- Una app de TikTok sin auditoría solo puede subir borradores o contenido privado.
- Los Shorts de más de 60 s con reclamos de Content ID se bloquean; un video corto y narrado es
  contenido transformador (la narración es lo principal, no la escena).

## Considered Options

1. Mezclar música propia y publicar directo (`video.publish`).
2. **No mezclar música; subir a TikTok como borrador al inbox (`video.upload`); lecciones ≤ 60 s.**

## Decision Outcome

Elegida la **opción 2**:
- El render no agrega música: pista original con ducking bajo la narración y normalización a −14 LUFS.
  El estudio solo sugiere un *mood*; el sonido se elige en TikTok o YouTube.
- TikTok: borrador al inbox con `video.upload`; el creador termina y publica en la app. No se pide
  `video.publish`.
- YouTube: privado por defecto, con `publishAt` opcional.
- El planificador usa 58 s por defecto (incluida la tarjeta final de 4 s) y cada tramo dura ≤ 60 s;
  el título lleva `#Shorts` si el video dura ≤ 60 s.

### Consequences

**Buenas:**
- Sin problemas de licencia musical; la revisión de TikTok solo pide dos scopes.
- El creador mantiene el control final de cada publicación.

**Malas / trade-offs:**
- Publicar en TikTok requiere un paso manual en el celular.
- Como mucho 5 borradores pendientes por 24 h por cuenta.

## More Information

- [UPLOADS.md](../../operations/UPLOADS.md), [TIKTOK_APP_REVIEW.md](../../operations/TIKTOK_APP_REVIEW.md)
