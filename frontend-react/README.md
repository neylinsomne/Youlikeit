# YouLikeIt · Estudio (front local)

El **Estudio** es la mesa de producción local de YouLikeIt: *aprender empatía a través del cine*.
Desde aquí se buscan películas de dominio público, se detectan sus momentos clave (por emoción o tropo,
entre obras distintas), se arman lecciones verticales cortas (supercuts de ≤ 60 s con textos y narración
opcional), se revisan y se publican:

- **TikTok** como **borrador**, a través del puente del sitio público (`web/`, Railway). El video va directo
  de esta PC a TikTok; el token de TikTok nunca sale de Railway.
- **YouTube** privado, con fecha de publicación opcional (OAuth de app instalada).

La música **no se mezcla**: se elige dentro de TikTok/YouTube. El estudio solo sugiere un *mood*.

Todo corre en `127.0.0.1`: la API en `:8001` y este front en `:5180`. Nada escucha en `0.0.0.0`.

## Cómo correrlo

Requisitos: Node 24 y la API del estudio (`src/apps/studio`) instalada (`pip install -e .` en la raíz).

```powershell
# 1. API del estudio (127.0.0.1:8001)
ylk studio

# 2. Front (127.0.0.1:5180)
cd frontend-react
npm install
npm run dev
```

O todo junto con `scripts/ops/studio.ps1`.

Abre **http://127.0.0.1:5180**.

### Token y proxy

- La API exige `Authorization: Bearer $STUDIO_TOKEN` (salvo `/api/health`).
- `vite.config.js` lee `STUDIO_TOKEN` del **`.env` de la raíz del repo** con `loadEnv` (sin prefijo `VITE_`)
  y lo **inyecta en el proxy** de `/api` y `/ws`. El token nunca llega al JavaScript del navegador ni al build.
- El proxy solo atiende peticiones de la propia página (bloquea `Origin` ajeno y `Sec-Fetch-Site` cruzado),
  porque agrega credenciales.
- Si la API no está corriendo, el proxy responde `503` con un detalle claro y la UI lo muestra.
- Variables opcionales (en el `.env` raíz o en el entorno):
  - `STUDIO_PORT`: puerto de la API (por defecto `8001`).
  - `STUDIO_API_URL`: destino completo del proxy (por defecto `http://127.0.0.1:${STUDIO_PORT}`).

Si cambias el `.env`, reinicia `npm run dev`.

## Páginas

| Ruta | Para qué |
|---|---|
| `/` **Inicio** | Conteos, almacenamiento por capa (con tope), credenciales presentes, ajustes de ASR/IA y últimos trabajos en vivo. |
| `/biblioteca` | Buscar películas (Internet Archive y local) con su estado de derechos; registrar solo las usables; ver obras/assets con el estado de cada paso de indexado; encolar **indexar → detectar → etiquetar**. |
| `/momentos` | Explorar momentos (filtros por etiqueta, obra, estado, texto, paginado) y **Buscar entre obras** un mismo tema. Cada tarjeta trae vista previa diferida, "por qué", anclas (cita/trama), etiquetas manuales validadas contra el vocabulario, rechazar/restaurar y **Agregar a lección**. |
| `/editor` | Crear una lección por tema o abrir una; línea de tiempo con arrastrar y soltar, recortes `mm:ss.s` por segmento, texto en pantalla, indicador de duración vs 60 s, guion (gancho, cierre, narración) con IA o a mano, guardar y **renderizar** con progreso en vivo. |
| `/revision` | Lecciones por estado; reproductor 9:16; issues con rango de tiempo (clic = saltar, "Ahora" = tiempo actual del video); aprobar o rechazar con motivo; si está aprobada, **Enviar a TikTok como borrador** y **Subir a YouTube**, más el historial de publicaciones. |
| `/trabajos` | La cola de trabajos en vivo por WebSocket, con filtros y detalle de parámetros, resultado y errores. |
| `/vocabulario` | Tropos, emociones, beats, roles y temas (solo lectura) con búsqueda y atajos a Momentos/Editor. |

## Estructura

```
src/
  api/client.js          cliente del contrato (errores reales: ApiError con status y detail)
  hooks/                 useApi (loading/error/data/refetch), useJobsSocket (WS único con reconexión),
                         useLiveJobs/useJobTracker, useVocab, useToast, useDebounced
  lib/                   formato (ms → mm:ss.s, fechas), etiquetas en español, socket de jobs
  components/            Layout, Sidebar, Header, ui (botones, pills, banners, modal), MomentCard, JobRow…
  pages/                 Inicio, Biblioteca, Momentos, Editor, Revision, Trabajos, Vocabulario, NoEncontrado
```

El contrato de la API está en [`docs/architecture/STUDIO_API.md`](../docs/architecture/STUDIO_API.md).

## Calidad

```powershell
npm run lint    # ESLint (incluye las reglas del React Compiler)
npm run build   # build de producción en dist/ (no se versiona)
```
