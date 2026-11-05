# Studio API: contrato (v1)

Estudio de producción **local**: el backend está en `src/apps/studio` (FastAPI) y el front en `frontend-react` (Vite).
Este documento es el contrato entre ambos y con el puente público de `web/` (Railway).
Si se cambia, se cambia aquí primero.

> Revisado el 2026-11-04 contra el código implementado (commits `2097888`, `751acdd`): incluye las
> desviaciones respecto del borrador inicial (estados de publicación, `409`/`422`/`503`, guardia de
> origen, campos extra). Arranque: `ylk studio` o `scripts/ops/studio.ps1`. Docs interactivas en
> `/api/docs` (OpenAPI en `/api/openapi.json`).

## Generalidades

| Tema | Regla |
|---|---|
| Host | `127.0.0.1:${STUDIO_PORT:-8001}`. **Nunca** `0.0.0.0`. |
| Prefijo | `/api` (WebSocket en `/ws`) |
| Auth | `Authorization: Bearer ${STUDIO_TOKEN}` (variable del `.env` raíz, comparado con `secrets.compare_digest`; el esquema `bearer` no distingue mayúsculas). El proxy de Vite inyecta el header, así que el token no viaja en el JS del navegador. Sin `STUDIO_TOKEN` configurado todo responde `401` y `ylk studio` no arranca. |
| Sin token | Solo `GET /api/health`, `GET /api/publish/youtube/callback` (lo protege el `state` de un solo uso, 10 min), `/api/docs` y `/api/openapi.json`. |
| Origen | Además de CORS, todo pedido HTTP o WS con un `Origin` que no sea el front ni el propio estudio responde `403` `{"detail": "Origen no permitido"}` (así una página ajena no usa el proxy de Vite). Sin `Origin` (curl, scripts) pasa. |
| CORS | Solo `http://127.0.0.1:5180` y `http://localhost:5180` (`STUDIO_ALLOWED_ORIGINS`, separado por comas, reemplaza la lista). |
| Errores | Formato de FastAPI: `{"detail": "mensaje"}`. `400` `state` de OAuth inválido o vencido (página HTML), `401` token, `403` origen, `404` no existe, `409` estado inválido (p. ej. publicar sin aprobar, YouTube sin conectar, menos de 2 obras), `422` validación, `502` falla externa (TikTok, YouTube, IA, ffmpeg), `503` falta configuración local (`WEB_BASE_URL`/`STUDIO_API_KEY`, `client_secrets.json`, `TOKEN_ENC_KEY`). |
| Éxitos | Siempre `200` (también al crear jobs, lecciones e issues; no hay `201`). Excepciones: `GET /api/publish/youtube/connect` (`302`) y los videos pedidos con `Range` (`206`). |
| Listas paginadas | `{"items": [...], "page": 1, "per_page": 50, "total": 123}`. Parámetros `page` y `per_page` (máx. 200). |
| Tiempos | Siempre en **milisegundos enteros** (`*_ms`), salvo `duration_s` y `start_s`/`end_s` de issues (segundos con decimales). |
| Fechas | ISO-8601 UTC (`2026-11-04T05:12:00Z`). |
| DB | `core.db.get_db(DATA_DIR)` (WAL + busy_timeout). Una conexión por request o hilo. |

## Variables de entorno (`.env` raíz)

| Variable | Uso |
|---|---|
| `STUDIO_TOKEN` | Token local del estudio (lo genera la instalación). |
| `STUDIO_PORT` | Por defecto 8001. |
| `WEB_BASE_URL` | `https://youlikeit-web-production.up.railway.app` |
| `STUDIO_API_KEY` | Secreto compartido con Railway para el puente de TikTok (el mismo valor en ambos lados). |
| `TOKEN_ENC_KEY` | Fernet local para cifrar los tokens de YouTube en `tokens/`. |
| `GOOGLE_CLIENT_SECRETS` | `client_secrets.json` (OAuth de app instalada para YouTube). |
| `ASR_BACKEND`, `LLM_PROVIDER`, `GROQ_LLM_MODEL` | Capa de IA (ver `src/integrations/ai`). Groq por defecto: `openai/gpt-oss-120b`. |
| `TTS_BACKEND`, `TTS_VOICE_ES`, `TTS_VOICE_EN` | Voz de la narración (`edge` por defecto). |
| `STUDIO_ALLOWED_ORIGINS`, `STUDIO_FRONT_URL` | Opcionales: orígenes permitidos y URL del front (link de vuelta tras conectar YouTube). |
| `DATA_DIR`, `OUTPUT_DIR` | DB (`shorts_pipeline.db`) y salida de lecciones (`outputs/lessons`). |

## Formas JSON

```jsonc
// Work
{"id": 1, "kind": "movie", "title": "Night of the Living Dead", "year": 1968, "assets": 1}

// Asset
{"id": 1, "work_id": 1, "work_title": "...", "work_year": 1968, "provider": "archive_org",
 "external_id": "Night.Of.The.Living.Dead_1080p", "rights": "public_domain",
 "duration_ms": 5752800, "height": 1080, "fps": 23.976, "accept_ranges": true,
 "steps": {"probe": true, "proxy": false, "analyze": true, "asr": true, "shots": true},
 "moments": 40, "moments_labeled": 12}

// MediaCandidate (resultado de búsqueda)
{"provider": "archive_org", "external_id": "HorrorExpress1972", "title": "Horror Express", "year": 1972,
 "rights": "public_domain", "license_url": "...", "height": 720, "duration_ms": 5265024,
 "partial": false, "master_file": "HorrorExpress.mkv", "proxy_file": "HorrorExpress_512kb.mp4",
 "usable": true}

// Job
{"id": 7, "type": "index", "status": "queued|running|done|error", "params": {...},
 "progress": {"stage": "asr", "pct": 40, "detail": "tramo 3/10"}, "result": {...} | null,
 "error": "..." | null, "created_at": "...", "started_at": "..." | null, "finished_at": "..." | null}

// Vocab (GET /api/vocab)
{"trope": [{"id": "siege", "es": "Encerrados juntos", "en": "Trapped together", "desc_es": "...", "desc_en": "..."}],
 "beat": [...], "emotion": [...], "role": [...], "theme": [...]}

// Moment
{"id": 12, "asset_id": 1, "work_id": 1, "work_title": "...", "work_year": 1968,
 "start_ms": 366000, "end_ms": 388000, "text": "They're coming for you, Barbara...",
 "summary_es": "..." | null, "importance": 0.71, "signal_score": 0.52, "position": 0.06,
 "status": "candidate|labeled|rejected",
 "why": {"quote_anchor": 0.13, "loudness": 0.05},          // contribuciones > 0, de mayor a menor
 "anchors": {"quote": "...", "plot": "..."},
 "labels": [{"dimension": "trope", "value": "the_dead_return", "confidence": 0.8, "source": "llm:groq"}],
 "preview_url": "/api/moments/12/preview"}

// Lesson
{"id": 3, "title": "Fear across the decades", "spec": "emotion:fear", "format": "essay",
 "lang": "es", "status": "draft|rendering|rendered|approved|rejected|published",
 "duration_s": 54.2 | null, "video_url": "/api/lessons/3/video" | null,
 "script": {"hook": "...", "outro": "...", "segments": [{"idx": 0, "narration": "...", "caption": "..."}]} | null,
 "script_source": "llm:groq|template|manual" | null,
 "items": [{"idx": 0, "moment_id": 12, "work_title": "...", "work_year": 1968,
            "in_ms": 366000, "out_ms": 378000, "caption": "Fear is an alarm.", "text": "...",
            "preview_url": "/api/moments/12/preview"}],
 "issues": 0, "publications": [Publication], "reject_reason": null,
 "created_at": "...", "updated_at": "..."}

// Issue
{"id": 1, "issue_type": "voice|caption|timing|image|rights|other", "start_s": 3.2, "end_s": 5.0,
 "note": "...", "created_at": "..."}

// Publication (TikTok termina en "sent": borrador en el inbox; YouTube en "published")
{"id": 1, "lesson_id": 3, "platform": "tiktok|youtube", "status": "pending|sent|published|failed",
 "external_id": "publish_id o video_id", "url": "https://..." | null, "detail": "..." | null,
 "created_at": "..."}
```

## Endpoints

### Sistema
- `GET /api/health` → `{"ok": true}` (sin auth).
- `GET /api/overview` →
  ```jsonc
  {"counts": {"works", "assets", "assets_indexed", "moments", "moments_labeled",
              "lessons": {"draft": 1, "rendered": 0}},
   "storage": <apps.media.storage.usage>,
   "credentials": [{"name": "Groq", "status": "OK|MISSING", "needed_for": "ASR y LLM por API"}],  // sin red: solo presencia
   "settings": {"asr_backend", "llm_provider", "groq_model", "web_base_url", "tts_backend"},
   "jobs": [Job]}  // los últimos 10
  ```

### Biblioteca
- `GET /api/works` → `{"items": [Work]}`
- `GET /api/assets?work_id=` → `{"items": [Asset]}`
- `GET /api/media/providers` → `{"items": [{"name": "local|archive_org|stremio", "available": bool, "detail": str}]}`. Sin red: solo dice qué está configurado. Del addon de Stremio solo muestra el host.
- `POST /api/media/search {"title": str, "year": int?, "providers": ["local", "archive_org", "stremio"]?, "all_rights": false}` → `{"items": [MediaCandidate], "warnings": [str]}`. Sin `providers` busca en los disponibles. Una fuente caída no tumba la búsqueda: se salta y queda en `warnings`. `MediaCandidate.via` = `"stremio:<host>"` cuando un ítem de archive.org llegó por el addon.
- `POST /api/media/ingest {"provider": "archive_org|local|stremio", "external_id": str, "title": str?, "year": int?}` → `Asset`. Responde `409` si los derechos no son usables o si la fuente no está disponible. Contrato del addon: [STREMIO_ADDON.md](STREMIO_ADDON.md).

### Jobs (una cola; un worker para red/GPU)
- `POST /api/jobs {"type": ..., "params": {...}}` → `Job` (`status: queued`)
  - `index`: `{"asset_ids": [1, 2], "steps": [...]?, "force": false}`
  - `detect`: `{"asset_id": 1, "fetch_anchors": true}`
  - `label`: `{"asset_id": 1, "top_k": 40, "provider": null}`
  - `render`: `{"lesson_id": 3}`
  - `publish_tiktok`: `{"lesson_id": 3, "open_id": "..."}`
  - `publish_youtube`: `{"lesson_id": 3, "privacy": "private", "publish_at": "2026-11-05T15:00:00Z"?}`
- `GET /api/jobs?status=&limit=50` → `{"items": [Job]}`
- `GET /api/jobs/{id}` → `Job`
- `WS /ws`: eventos del hub (`utils.websocket_hub`) con el formato `{"ts", "source", "stage", "data"}`. Los jobs emiten `source: "studio.job"` y `data: {"job_id", "type", "status", "stage", "pct", "detail"}`. Al conectar llega `{"type": "catchup", "events": [...]}`.
  - Token: header `Authorization: Bearer` (lo pone el proxy de Vite) o `?token=` (scripts sin proxy). Sin token válido se cierra con código `1008`; con `Origin` ajeno también.
- Un solo worker procesa la cola en orden. Al arrancar, los jobs que quedaron `running` pasan a `error` y las lecciones `rendering` vuelven a `draft`.
- Los parámetros se validan al encolar: `422` datos inválidos, `404` asset o lección inexistente, `409` estado inválido (`render` de una lección bloqueada o sin tramos; publicar sin aprobar; YouTube sin conectar).

### Momentos
- `GET /api/vocab` → `Vocab`
- `GET /api/moments?asset_id=&work_id=&dimension=&value=&min_conf=0&status=&q=&page=&per_page=` → página de `Moment`, por importancia.
- `GET /api/moments/find?spec=trope:siege&limit=6&min_works=3&per_work=1&min_confidence=0.5` → `{"dimension", "value", "items": [Moment + "score" + "confidence"], "distinct_works", "candidates", "warning"?}`
- `GET /api/moments/{id}` → `Moment`
- `PATCH /api/moments/{id} {"status": "rejected|candidate"?, "add_labels": [{"dimension", "value"}]?, "remove_labels": [{"dimension", "value"}]?}` → `Moment`. Las etiquetas manuales usan `source="manual"` y `confidence=1.0`, y se validan contra el vocabulario.
- `GET /api/moments/{id}/preview` → `video/mp4`: clip corto de baja resolución (480p de alto), cacheado en `media_cache/previews/`, con soporte de Range.

### Lecciones (recetas de supercut)
- `POST /api/lessons {"spec": "emotion:fear", "title": str?, "max_works": 5, "max_duration_s": 58, "lang": "es", "min_confidence": 0.5}` → `Lesson` (`draft`), armada con `supercut.planner` a partir de `find_moments`, con guion de plantilla (`script_source: "template"`). Responde `409` si hay menos de 2 obras. Límites: `max_works` 2–10, `max_duration_s` 10–180, `min_confidence` 0–1.
- `GET /api/lessons?status=` → `{"items": [Lesson]}` (las `items` pueden ir resumidas)
- `GET /api/lessons/{id}` → `Lesson`
- `PATCH /api/lessons/{id} {"title"?, "items"?: [{"moment_id", "in_ms", "out_ms", "caption"}], "script"?}` → `Lesson`. Editar una lección `rendered`, `approved` o `rejected` la devuelve a `draft`. Una lección `rendering` o `published` no se edita (`409`). Cada tramo ≤ 60 s, máximo 20 tramos, y solo momentos con derechos usables (`422`). Un guion editado a mano queda con `script_source: "manual"`.
- `POST /api/lessons/{id}/script {"provider": null}` → `Lesson` con `script` generado por IA (`script_source: "llm:<proveedor>"`). `502` si no hay LLM o si la respuesta menciona un año que no está entre las obras; en ese caso queda la plantilla. `409` si la lección está bloqueada.
- `POST /api/lessons/{id}/render {"narrate": bool | null}` (cuerpo opcional) → `Job` (atajo de `POST /jobs type=render`). `narrate: null` narra si hay guion. `409` si la lección está `rendering`/`published` o no tiene tramos.
- `GET /api/lessons/{id}/video` → `video/mp4` (Range). `404` si todavía no tiene video.

### Revisión
- `POST /api/lessons/{id}/approve` → `Lesson` (requiere `rendered`, si no `409`).
- `POST /api/lessons/{id}/reject {"reason": str}` → `Lesson` (`reject_reason` guardado). Solo desde `rendered` o `approved` (si no `409`); `reason` es obligatorio (`422` si falta o está vacío).
- `GET /api/lessons/{id}/issues` → `{"items": [Issue]}`
- `POST /api/lessons/{id}/issues {"issue_type", "start_s", "end_s", "note"}` → `Issue` (`422` si `issue_type` no está en la lista o `end_s < start_s`)
- `DELETE /api/lessons/{id}/issues/{issue_id}` → `{"ok": true}`

### Publicar (requiere `approved` o `published`; si no, `409`)

`published` se acepta para subir a la segunda plataforma. También `409` si la lección no tiene video.
El job de TikTok deja la publicación en `sent` (borrador en el inbox); el de YouTube en `published`.
La lección pasa a `published` cuando alguna plataforma sale bien.

- `GET /api/publish/tiktok/accounts` → `{"accounts": [{"open_id", "display_name"}]}` (vía el puente de `web/`; `503` sin `WEB_BASE_URL`/`STUDIO_API_KEY`, `502` si el puente falla)
- `POST /api/lessons/{id}/publish/tiktok {"open_id"}` → `Job`
- `GET /api/publish/youtube/status` → `{"connected": bool, "channel_title": str | null, "detail"?: str}` (sin red; `detail` aparece si el token no se puede descifrar)
- `GET /api/publish/youtube/connect` → `302` a Google (OAuth de app instalada con PKCE). `503` sin `client_secrets.json` o `TOKEN_ENC_KEY`.
- `GET /api/publish/youtube/callback?state&code` → página HTML (sin token). `400` si el `state` es inválido, vencido o ya usado; `502` si no se pudo canjear el código.
- `POST /api/lessons/{id}/publish/youtube {"privacy": "private|unlisted|public", "publish_at"?}` → `Job`. `409` si YouTube no está conectado; `422` si `publish_at` no es futuro o se combina con algo distinto de `private`.
- `GET /api/lessons/{id}/publications` → `{"items": [Publication]}`

### Archivos
- `GET /api/files/{kind}/{name}` con `kind` en `{preview, lesson}`. `name` debe ser un nombre simple terminado en `.mp4` (`^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.mp4$`, sin `..`). El path resuelto **debe** quedar dentro de `media_cache/previews` o `outputs/lessons`; si no, `404`. Nunca se sirve otra cosa (ni `.env`, ni `tokens/`, ni la DB).

## Puente de publicación en `web/` (Railway)

Base: `${WEB_BASE_URL}`. Auth: `Authorization: Bearer ${STUDIO_API_KEY}`, comparado con `secrets.compare_digest`. Si la key del servidor no está configurada o tiene menos de 32 caracteres → `503` (el puente queda apagado). Key ausente o distinta → `401`.

| Método | Ruta | Cuerpo / respuesta |
|---|---|---|
| GET | `/api/studio/accounts` | `{"accounts": [{"open_id", "display_name"}]}` (sin tokens) |
| POST | `/api/studio/tiktok/init` | `{"open_id", "video_size", "lesson_ref"}` → `{"publish_id", "upload_url"}`. `lesson_ref` acepta texto o entero; `video_size` entre 1 byte y 64 MB (si no, `422`). Usa el token guardado (renovado si venció), llama al init de inbox `FILE_UPLOAD` de un solo trozo y registra el envío. `404` `unknown open_id` · `409` `reconnect_required` · `502` `{"detail": "<código TikTok>"}` o `{"detail": "tiktok_unreachable"}` |
| GET | `/api/studio/tiktok/status/{publish_id}` | `{"status": "PROCESSING_UPLOAD\|SEND_TO_USER_INBOX\|PUBLISH_COMPLETE\|FAILED\|...", "fail_reason"?: str}`. `404` `unknown publish_id`; mismos `409`/`502` que `init` |

El estudio hace el `PUT` de los bytes **directo** a `upload_url`: `Content-Type: video/mp4`, `Content-Range: bytes 0-{n-1}/{n}`, un solo trozo de hasta 64 MB. Antes verifica que `upload_url` sea `https` en `*.tiktokapis.com` (si no, no sube). Luego consulta el estado cada 5 s, hasta 5 min. El video nunca se guarda en Railway y el token de TikTok nunca sale de Railway.
