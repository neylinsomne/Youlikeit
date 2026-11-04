# Security & Secrets · YouLikeIt

> Inventario de secrets, dónde viven, cómo se rotan y modelo de amenazas.
> **No commitear secrets.** Si algo de esto aparece en `git log`, tratarlo como comprometido y rotar.
> Este doc es el contrato, no el dump: el inventario real está en `.env`, `.env.example`, las
> variables del servicio `youlikeit-web` en Railway y los GitHub Secrets.
> Última revisión: 2026-11-04.

## Superficies

| Superficie | Exposición | Secretos que maneja |
|---|---|---|
| Sitio `web/` (Railway) | **Pública** en internet | Client secret de TikTok, tokens OAuth de TikTok (cifrados), `STUDIO_API_KEY`, `SESSION_SECRET` |
| Estudio local (`src/apps/studio` + `frontend-react`) | Solo `127.0.0.1` en el PC del creador | `STUDIO_TOKEN`, `STUDIO_API_KEY`, token de YouTube (cifrado), keys de IA |
| CLI / ETL (`ylk`) | Local | Keys de IA y de fuentes |
| GitHub Actions | CI | Ninguno configurado hoy (las crons corren sin keys) |

## Inventario de secrets

### `.env` local (raíz del repo, gitignored)

| Variable | Para qué | Notas |
|---|---|---|
| `STUDIO_TOKEN` | Bearer de la API del estudio | Lo inyecta el proxy de Vite del lado del servidor; nunca llega al JS. `ylk studio` no arranca sin él |
| `STUDIO_API_KEY` | Secreto compartido con el puente de `web/` | El **mismo valor** en `.env` y en Railway; mínimo 32 caracteres (si no, el puente responde `503`) |
| `TOKEN_ENC_KEY` | Fernet para `tokens/youtube_studio.json.enc` | Si cambia, el token de YouTube no se descifra y hay que reconectar |
| `GOOGLE_CLIENT_SECRETS` → `client_secrets.json` | Cliente OAuth "Aplicación de escritorio" de YouTube | Gitignored |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | ASR y LLM por API | Ollama local no usa key |
| `TMDB_API_KEY` | Metadatos | ⚠️ **Filtrada en el historial de git**: rotar (acción del dueño) |
| `OPENSUBTITLES_*`, `SUBDL_API_KEY`, `OMDB_API_KEY`, `TRAKT_CLIENT_ID`, `YOUTUBE_API_KEY`, `HF_TOKEN` | Fuentes opcionales | — |
| `QBIT_USER`, `QBIT_PASS` | qBittorrent (legacy, congelado) | ⚠️ La contraseña quedó en el historial: cambiarla |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | Solo para que `ylk doctor` los revise | Los que usa el sitio viven en Railway |

`WEB_BASE_URL`, `STUDIO_PORT`, `ASR_BACKEND`, `LLM_PROVIDER`, `TTS_BACKEND` son configuración, no secretos.

### Variables del servicio `youlikeit-web` en Railway

| Variable | Para qué | Estado (2026-11-04) |
|---|---|---|
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | Login Kit + Content Posting API | ⚠️ Pendiente (keys del Sandbox) |
| `TOKEN_ENC_KEY` | Fernet para los tokens de TikTok en `web.db` | Cargada. Usar un valor distinto al local |
| `SESSION_SECRET` | Firma de la cookie de sesión | Cargada. Sin ella se genera una al azar por proceso y las sesiones se pierden al reiniciar |
| `STUDIO_API_KEY` | Auth del puente `/api/studio/*` | Cargada |
| `PUBLIC_BASE_URL` | Redirect URI de TikTok y cookie `https_only` | Cargada |
| `CONTACT_EMAIL` | Página de contacto | Cargada |
| `TIKTOK_SITE_TOKENS` | Tokens extra de verificación de URL (coma) | Opcional |
| `ALLOWED_TIKTOK_OPEN_IDS` | Cuentas de TikTok que pueden conectarse (acceso por invitación; vacía = abierto) | Cargada con la cuenta del dueño (2026-11-04). La identidad es el login de TikTok: no hay contraseñas propias que guardar |

`DATA_DIR=/data` lo fija el `Dockerfile`; `/data` es el volumen de Railway.

## Dónde viven los tokens OAuth

| Token | Dónde | Cifrado |
|---|---|---|
| TikTok (access + refresh) | `web.db` en el volumen `/data` de Railway, tabla `tiktok_accounts` | Fernet con `TOKEN_ENC_KEY` de Railway. Del perfil solo se guardan `open_id` y `display_name`; el avatar no se almacena |
| YouTube del estudio | `tokens/youtube_studio.json.enc` (local) | Fernet con `TOKEN_ENC_KEY` local; escritura atómica |
| YouTube legacy por persona (ex34) | `tokens/youtube_<persona>.json` | En claro (legacy). `tokens/` está gitignored |

Desconectar TikTok en `/studio` revoca el token en TikTok y borra la fila y sus publicaciones de `web.db`.
`store.save_account` se niega a guardar si falta `TOKEN_ENC_KEY`.

## Qué NO se commitea (`.gitignore`)

- [x] `.env`, `.env.plausible`
- [x] `client_secret.json` / `client_secrets.json`
- [x] `tokens/` (salvo `tokens/personas.json`, que sigue versionado: config con emails/channel IDs)
- [x] `data/shorts_pipeline.db` y sus `-wal`/`-shm` (des-versionada en esta rama)
- [x] `*.mp4` (las lecciones del sitio se suben con `railway up --no-gitignore`)
- [x] `.claude/settings.local.json`
- `web/.railwayignore` y `web/.dockerignore` excluyen `.env`, `*.db` y `tests/` de la imagen.

## Modelo de amenazas

### Sitio público `web/`

| Amenaza | Mitigación |
|---|---|
| Robo de tokens de TikTok desde la DB | Cifrados en reposo (Fernet); la key solo está en las variables de Railway |
| CSRF en el OAuth de TikTok | `state` aleatorio en la sesión, comparado con `secrets.compare_digest` |
| Uso del puente por terceros | `Authorization: Bearer STUDIO_API_KEY` con comparación en tiempo constante; sin key (o < 32 caracteres) el puente queda apagado (`503`) |
| Un tercero verifica nuestro dominio en su app de TikTok | Solo se sirven archivos `tiktok<TOKEN>.txt` en lista permitida (`web/app/verification/` o `TIKTOK_SITE_TOKENS`) |
| Ver el estado de envíos ajenos | `/studio/sent/{publish_id}` solo responde a la sesión dueña del envío |
| Superficie de API innecesaria | Sin `/docs` ni `openapi.json` (`docs_url=None`) |
| El video pasa por un servidor | No pasa: el puente solo entrega un `upload_url`; los bytes van del PC a TikTok |

### Estudio local

| Amenaza | Mitigación |
|---|---|
| Acceso desde la red local | La API escucha solo en `127.0.0.1` (no hay opción de host); Vite también |
| Página web ajena que usa el proxy de Vite (que inyecta el token) | Guardia de `Origin`: cualquier pedido HTTP o WS con `Origin` fuera de la lista responde `403`; el proxy además bloquea `Origin` ajeno y `Sec-Fetch-Site` cruzado |
| Lectura de archivos sensibles (`.env`, `tokens/`, la DB) | `/api/files/{kind}/{name}`: solo `preview` y `lesson`, solo nombres `.mp4` simples, el path resuelto debe quedar dentro de la carpeta; si no, `404` |
| WebSocket sin auth | `/ws` exige el token por header (proxy) o `?token=`; si no, cierre `1008` |
| Callback de YouTube sin token | Protegido por `state` de un solo uso (10 min) + PKCE |
| Puente comprometido redirige la subida | El estudio solo sube a `https://*.tiktokapis.com` |

Rutas sin token en el estudio: `GET /api/health`, `GET /api/publish/youtube/callback`, `/api/docs` y
`/api/openapi.json` (solo alcanzables desde el propio PC).

### API ex29 (retirada)

La API legacy ex29 entregaba un token admin sin contraseña, `/api/files/{path}` servía `.env`, `tokens/`
y la DB sin auth, tenía CORS `*` y escuchaba en `0.0.0.0`. Se quitó de `docker-compose.yml` junto con el
contenedor del front viejo. El código queda en `scripts/legacy/` solo como referencia: **no correrla**.

### Generales

| Amenaza | Mitigación |
|---|---|
| Leak de API key en repo o log | `.gitignore` estricto; `ylk doctor` y `studio.ps1` nunca imprimen valores; rotar al detectar |
| Supply chain | Deps justificadas en el PR; versiones fijadas en `web/requirements.txt` |
| PII | El sitio no guarda avatar ni datos de perfil más allá de `open_id` y `display_name` |
| Secret en logs de CI | No hay secrets en CI hoy; no hacer `echo` de variables |

## Incidente 2026-11-03: secretos en reglas de permisos de Claude Code

Reglas `allow` viejas de `.claude/settings.json` y `.claude/settings.local.json` traían en texto plano
la key de TMDB, la contraseña de qBittorrent y un bearer de ex29. Se quitaron y `settings.local.json`
dejó de versionarse, **pero siguen en el historial de git**. Pendiente del dueño: rotar la key de
TMDB y cambiar la contraseña de qBittorrent. ex29 ya no corre.

## Política de rotación

| Secreto | Cómo rotar | Efecto |
|---|---|---|
| `STUDIO_TOKEN` | Nuevo valor en `.env` y reiniciar `scripts/ops/studio.ps1` (Vite lee el `.env` al arrancar) | Ninguno fuera del PC |
| `STUDIO_API_KEY` | Cambiar en `.env` **y** en Railway a la vez | Hasta igualarlas, el estudio recibe `401` del puente |
| `TOKEN_ENC_KEY` (Railway) | `railway variable set` | Las cuentas de TikTok deben reconectarse en `/studio` |
| `TOKEN_ENC_KEY` (local) | Cambiar en `.env` | Reconectar YouTube desde el estudio |
| `TIKTOK_CLIENT_SECRET` | Developer Portal → Railway | Puede invalidar tokens: reconectar |
| API keys de terceros | En el proveedor + `.env` | Revisar con `ylk doctor` |
| Secret en un commit | Rotar de inmediato en el proveedor; reescribir historia si es viable | — |

## Relacionado

- [UPLOADS.md](UPLOADS.md): flujo de publicación.
- [RUNBOOK.md](RUNBOOK.md): incidentes de operación.
- [STUDIO_API.md](../architecture/STUDIO_API.md): contrato y reglas de auth.
- [SETUP_CUENTAS.md](../../SETUP_CUENTAS.md): alta de cuentas y keys.
