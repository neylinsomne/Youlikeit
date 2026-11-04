# Studio API: contrato (v1)

Estudio de producción **local**: el backend está en `src/apps/studio` (FastAPI) y el front en `frontend-react` (Vite).
Este documento es el contrato entre ambos y con el puente público de `web/` (Railway).
Si se cambia, se cambia aquí primero.

## Generalidades

| Tema | Regla |
|---|---|
| Host | `127.0.0.1:${STUDIO_PORT:-8001}`. **Nunca** `0.0.0.0`. |
| Prefijo | `/api` (WebSocket en `/ws`) |
| Auth | `Authorization: Bearer ${STUDIO_TOKEN}` (variable del `.env` raíz) en todas las rutas salvo `GET /api/health`. El proxy de Vite inyecta el header, así que el token no viaja en el JS del navegador. |
| CORS | Solo `http://127.0.0.1:5180` y `http://localhost:5180`. |
| Errores | Formato de FastAPI: `{"detail": "mensaje"}`. `401` token, `404` no existe, `409` estado inválido (p. ej. publicar sin aprobar), `422` validación, `502` falla externa (TikTok, YouTube, IA). |
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
| `ASR_BACKEND`, `LLM_PROVIDER`, `GROQ_LLM_MODEL` | Capa de IA (ver `src/integrations/ai`). |

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
 "items": [{"idx": 0, "moment_id": 12, "work_title": "...", "work_year": 1968,
            "in_ms": 366000, "out_ms": 378000, "caption": "Fear is an alarm.", "text": "...",
            "preview_url": "/api/moments/12/preview"}],
 "issues": 0, "publications": [Publication], "reject_reason": null,
 "created_at": "...", "updated_at": "..."}

// Issue
{"id": 1, "issue_type": "voice|caption|timing|image|rights|other", "start_s": 3.2, "end_s": 5.0,
 "note": "...", "created_at": "..."}

// Publication
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
   "credentials": [{"name": "Groq", "status": "OK|MISSING|..."}],  // sin red: solo presencia de variables
   "settings": {"asr_backend", "llm_provider", "groq_model", "web_base_url"},
   "jobs": [Job]}  // los últimos 10
  ```

### Biblioteca
- `GET /api/works` → `{"items": [Work]}`
- `GET /api/assets?work_id=` → `{"items": [Asset]}`
- `POST /api/media/search {"title": str, "year": int?, "providers": ["local", "archive_org"]?, "all_rights": false}` → `{"items": [MediaCandidate]}`
- `POST /api/media/ingest {"provider": "archive_org|local", "external_id": str, "title": str?, "year": int?}` → `Asset`. Responde `409` si los derechos no son usables.

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

### Momentos
- `GET /api/vocab` → `Vocab`
- `GET /api/moments?asset_id=&work_id=&dimension=&value=&min_conf=0&status=&q=&page=&per_page=` → página de `Moment`, por importancia.
- `GET /api/moments/find?spec=trope:siege&limit=6&min_works=3&per_work=1&min_confidence=0.5` → `{"dimension", "value", "items": [Moment + "score" + "confidence"], "distinct_works", "candidates", "warning"?}`
- `GET /api/moments/{id}` → `Moment`
- `PATCH /api/moments/{id} {"status": "rejected|candidate"?, "add_labels": [{"dimension", "value"}]?, "remove_labels": [{"dimension", "value"}]?}` → `Moment`. Las etiquetas manuales usan `source="manual"` y `confidence=1.0`, y se validan contra el vocabulario.
- `GET /api/moments/{id}/preview` → `video/mp4`: clip corto de baja resolución (480p de alto), cacheado en `media_cache/previews/`, con soporte de Range.

### Lecciones (recetas de supercut)
- `POST /api/lessons {"spec": "emotion:fear", "title": str?, "max_works": 5, "max_duration_s": 58, "lang": "es"}` → `Lesson` (`draft`), armada con `supercut.planner` a partir de `find_moments`. Responde `409` si hay menos de 2 obras.
- `GET /api/lessons?status=` → `{"items": [Lesson]}` (las `items` pueden ir resumidas)
- `GET /api/lessons/{id}` → `Lesson`
- `PATCH /api/lessons/{id} {"title"?, "items"?: [{"moment_id", "in_ms", "out_ms", "caption"}], "script"?}` → `Lesson`. Editar una lección `rendered`, `approved` o `rejected` la devuelve a `draft`.
- `POST /api/lessons/{id}/script {"provider": null}` → `Lesson` con `script` generado por IA (`502` si no hay LLM; queda la plantilla).
- `POST /api/lessons/{id}/render` → `Job` (atajo de `POST /jobs type=render`).
- `GET /api/lessons/{id}/video` → `video/mp4` (Range).

### Revisión
- `POST /api/lessons/{id}/approve` → `Lesson` (requiere `rendered`, si no `409`).
- `POST /api/lessons/{id}/reject {"reason": str}` → `Lesson` (`reject_reason` guardado).
- `GET /api/lessons/{id}/issues` → `{"items": [Issue]}`
- `POST /api/lessons/{id}/issues {"issue_type", "start_s", "end_s", "note"}` → `Issue`
- `DELETE /api/lessons/{id}/issues/{issue_id}` → `{"ok": true}`

### Publicar (requiere `approved`; si no, `409`)
- `GET /api/publish/tiktok/accounts` → `{"accounts": [{"open_id", "display_name"}]}` (vía el puente de `web/`; `502` si no responde)
- `POST /api/lessons/{id}/publish/tiktok {"open_id"}` → `Job`
- `GET /api/publish/youtube/status` → `{"connected": bool, "channel_title": str?}`
- `GET /api/publish/youtube/connect` → `302` a Google (OAuth de app instalada; callback `GET /api/publish/youtube/callback` en 127.0.0.1)
- `POST /api/lessons/{id}/publish/youtube {"privacy": "private|unlisted|public", "publish_at"?}` → `Job`
- `GET /api/lessons/{id}/publications` → `{"items": [Publication]}`

### Archivos
- `GET /api/files/{kind}/{name}` con `kind` en `{preview, lesson}`. El path resuelto **debe** quedar dentro de `media_cache/previews` o `outputs/lessons`; si no, `404`. Nunca se sirve otra cosa (ni `.env`, ni `tokens/`, ni la DB).

## Puente de publicación en `web/` (Railway)

Base: `${WEB_BASE_URL}`. Auth: `Authorization: Bearer ${STUDIO_API_KEY}`, comparado con `secrets.compare_digest`. Sin key configurada en el servidor → `503`.

| Método | Ruta | Cuerpo / respuesta |
|---|---|---|
| GET | `/api/studio/accounts` | `{"accounts": [{"open_id", "display_name"}]}` |
| POST | `/api/studio/tiktok/init` | `{"open_id", "video_size", "lesson_ref"}` → `{"publish_id", "upload_url"}`. Usa el token guardado (renovado si venció), llama al init de inbox `FILE_UPLOAD` de un solo trozo y registra el envío. `404` open_id desconocido · `409` hay que reconectar · `502` `{"detail": "<código TikTok>"}` |
| GET | `/api/studio/tiktok/status/{publish_id}` | `{"status": "PROCESSING_UPLOAD\|SEND_TO_USER_INBOX\|FAILED\|..."}` |

El estudio hace el `PUT` de los bytes **directo** a `upload_url`: `Content-Type: video/mp4`, `Content-Range: bytes 0-{n-1}/{n}`, un solo trozo de hasta 64 MB. El video nunca se guarda en Railway y el token de TikTok nunca sale de Railway.
