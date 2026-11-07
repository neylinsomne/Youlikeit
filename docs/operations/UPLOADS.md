# Uploads · Publicar lecciones en TikTok y YouTube

> Flujo real de publicación desde el estudio local (2026-11-04). Código: `src/apps/publish/`
> (estudio) y `web/app/` (puente en Railway). Contrato HTTP: [STUDIO_API.md](../architecture/STUDIO_API.md).
> Reemplaza a la guía vieja de APIs y tendencias (estaba "en pausa").

## Estado

| Canal | Código | Envío real |
|---|---|---|
| TikTok desde el sitio ("Send to TikTok as draft", lección demo) | ✅ | ⚠️ Falta cargar las keys del Sandbox en Railway |
| TikTok desde el estudio (puente `web/`) | ✅ (tests con TikTok simulado) | ⚠️ Igual: keys del Sandbox + conectar la cuenta en `/studio` |
| YouTube desde el estudio | ✅ (tests con la API simulada) | ⚠️ Falta key nueva de Google, pantalla de consentimiento "En producción" y reconectar |

## Reglas comunes

- Solo se publica una lección **`approved`**, o una ya `published` (para subirla a la otra plataforma).
  Si no, `409`. También `409` si no tiene video renderizado.
- Cada envío crea una fila en `publications` (`pending` → `sent` | `published` | `failed`).
- TikTok termina en **`sent`** (borrador en el inbox); YouTube en **`published`** (subido al canal).
- La lección pasa a `published` cuando alguna plataforma sale bien.
- La música no se mezcla: se elige en la app (TikTok) o se deja la pista original.
- El envío corre como job (`publish_tiktok` / `publish_youtube`) en la cola única del estudio, con
  progreso por WebSocket.

## TikTok (borrador al inbox)

Scopes: `user.info.basic` y `video.upload`. **No** se pide `video.publish`: el creador termina la
publicación en la app, donde elige el sonido.

```
Estudio (127.0.0.1)                         web/ en Railway                      TikTok
  GET  /api/studio/accounts      ────────►  lista open_id + display_name
  POST /api/studio/tiktok/init   ────────►  token vigente (lo renueva) ───────►  inbox/video/init
                                 ◄────────  {publish_id, upload_url}   ◄───────
  PUT upload_url (bytes del MP4, 1 trozo ≤ 64 MB)  ─────────────────────────────►  (directo)
  GET  /api/studio/tiktok/status/{id}  ──►  status/fetch  ──────────────────────►
```

- El video **no** pasa por Railway y el token de TikTok **no** sale de Railway.
- El estudio solo acepta `upload_url` `https://*.tiktokapis.com`.
- Tras el PUT consulta el estado cada 5 s, hasta 5 min: `SEND_TO_USER_INBOX` → `sent`,
  `PUBLISH_COMPLETE` → `published`, `FAILED` → `failed`.
- Límite de TikTok: como mucho 5 borradores pendientes por 24 h (`spam_risk_too_many_pending_share`).

### Pasos (una vez)

1. Keys del Sandbox en Railway (ver [TIKTOK_APP_REVIEW.md](TIKTOK_APP_REVIEW.md)):
   `railway variable set --service youlikeit-web TIKTOK_CLIENT_KEY=... TIKTOK_CLIENT_SECRET=...`
2. Abrir `https://youlikeit-web-production.up.railway.app/studio` → **Continue with TikTok** con la
   cuenta del Sandbox.
3. En el `.env` local: `WEB_BASE_URL=https://youlikeit-web-production.up.railway.app` y el mismo
   `STUDIO_API_KEY` que en Railway.

### Pasos (cada lección)

Estudio → **Revisión** → lección aprobada → **Enviar a TikTok como borrador** → elegir la cuenta.
Luego, en el celular: TikTok → bandeja de entrada → abrir el borrador, elegir sonido y publicar.

## YouTube (privado, con fecha opcional)

- OAuth de **app instalada**: `client_secrets.json` de tipo "Aplicación de escritorio"; redirect loopback
  `http://127.0.0.1:${STUDIO_PORT:-8001}/api/publish/youtube/callback`.
- Scopes: `youtube.upload` y `youtube.readonly` (para leer el nombre del canal).
- Token cifrado con Fernet en `tokens/youtube_studio.json.enc` (`TOKEN_ENC_KEY` local).
- Subida resumible en trozos de 8 MB, categoría Educación (27), `selfDeclaredMadeForKids=false`.
- Título ≤ 100 caracteres, sin `<` ni `>`, y con `#Shorts` si dura ≤ 60 s.
- Descripción automática: gancho del guion + lista de escenas (título y año) + nota de derechos + hashtags.
- `privacy`: `private` por defecto (`unlisted` y `public` permitidos). `publish_at` exige `private` y
  una fecha futura (ISO-8601); YouTube la publica a esa hora.
- Publicar en **público** vía API requiere la auditoría de YouTube API Services; sin ella los videos
  subidos por API quedan privados.

### Pasos (una vez, dueño)

1. Crear una key nueva en Google Cloud (la anterior está inválida) y un cliente OAuth de escritorio;
   guardar el JSON como `client_secrets.json` (o apuntar `GOOGLE_CLIENT_SECRETS`).
2. Pantalla de consentimiento → **Publicar app (En producción)**. En "Testing" Google vence los refresh
   tokens a los 7 días.
3. Generar `TOKEN_ENC_KEY` local (comando en `.env.example`).
4. Estudio → **Revisión** → **Conectar YouTube** → autorizar. El estado se ve en `GET /api/publish/youtube/status`.

## Errores frecuentes

Los errores de validación salen al encolar (respuesta HTTP); los de la plataforma salen en el job
(`error`) y en la publicación (`detail`).

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `409` "debe estar aprobada" al encolar | La lección no está `approved`/`published` o no tiene video | Renderizar y aprobar |
| `409` YouTube no conectado al encolar | No hay token guardado | Conectar YouTube |
| `503` al listar cuentas o al conectar YouTube | Faltan `WEB_BASE_URL`/`STUDIO_API_KEY`, `client_secrets.json` o `TOKEN_ENC_KEY` | Completar el `.env` |
| `502` al listar cuentas | El puente no responde o la key no coincide | Revisar `/healthz` del sitio y `STUDIO_API_KEY` en ambos lados |
| Job en error con `reconnect_required` | TikTok rechazó el refresh token (el puente responde `409`) | Reconectar en `/studio` del sitio |
| Job en error con `tiktok_unreachable` | TikTok no respondió | Reintentar |
| Publicación `failed` | La plataforma rechazó el envío | Ver `detail` en la publicación |

## Legacy

`scripts/uploads/` (`upload_cycle_v2_shorts.py`, `upload_series_from_produce.py`) y el OAuth por persona
de `ex34_oauth_manager.py` pertenecen al producto anterior y no se usan para las lecciones.
