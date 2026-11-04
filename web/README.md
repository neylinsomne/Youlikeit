# web/ · Sitio público de YouLikeIt (Railway)

Sitio público de "learn empathy through film": explorar películas de dominio público por emoción,
términos y privacidad, y la cara de la app ante TikTok (Login Kit + Content Posting API).
También es el **puente** que usa el estudio local para mandar borradores a TikTok.

- URL: <https://youlikeit-web-production.up.railway.app>
- Stack: FastAPI + Jinja2 (`app/main.py`), sin build de front. Textos del sitio en inglés.
- Railway: proyecto `youlikeit`, servicio `youlikeit-web`, volumen montado en `/data`.
- Reemplaza al sitio estático de `youlikeit-web/` (nginx en `vara-alta.lat`), que queda como historia.

## Rutas

| Ruta | Qué hace |
|---|---|
| `GET /` | Inicio: qué es y cómo funciona |
| `GET /explore` | Guía de emociones + biblioteca de películas (`app/data/catalog.json`) |
| `GET /explore/{emotion}` | Una emoción: qué es, cómo la muestra el cine, pausa, tropos, películas y lecciones |
| `GET /terms`, `/privacy`, `/contact` | Políticas y contacto (`/terms.html` y `/privacy.html` también responden) |
| `GET /healthz` | `{"ok": true}` (healthcheck de Railway) |
| `GET /studio` | Conectar TikTok y ver la cuenta conectada (nombre + avatar, el avatar no se guarda) |
| `GET /auth/tiktok/login` · `GET /auth/tiktok/callback` · `POST /auth/tiktok/disconnect` | OAuth de TikTok (`state` en la sesión); desconectar revoca el token y borra la cuenta |
| `POST /studio/send/{lesson_id}` | "Send to TikTok as draft" de una lección del sitio |
| `GET /studio/sent/{publish_id}` | Estado del envío (solo para la sesión dueña) |
| `GET /api/studio/accounts` · `POST /api/studio/tiktok/init` · `GET /api/studio/tiktok/status/{id}` | Puente del estudio local (Bearer `STUDIO_API_KEY`). Contrato: [STUDIO_API.md](../docs/architecture/STUDIO_API.md#puente-de-publicación-en-web-railway) |
| `GET /tiktok<TOKEN>.txt` | Verificación de prefijo de URL de TikTok, **solo** para tokens en lista permitida |
| `/static/*`, `/lessons-media/*` | Logo y MP4 de las lecciones del sitio |

No hay `/docs` ni `openapi.json` (deshabilitados a propósito).

## Variables de entorno (Railway)

| Variable | Uso |
|---|---|
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | App de TikTok. Sin ellas el sitio funciona y `/studio` muestra "not configured" |
| `PUBLIC_BASE_URL` | Base del redirect URI (`{PUBLIC_BASE_URL}/auth/tiktok/callback`); si es `https`, la cookie de sesión es `https_only` |
| `TOKEN_ENC_KEY` | Fernet para cifrar los tokens de TikTok. Sin ella no se guarda ninguna cuenta |
| `SESSION_SECRET` | Firma de la cookie de sesión (14 días, `SameSite=lax`) |
| `STUDIO_API_KEY` | Auth del puente; mínimo 32 caracteres o el puente responde `503` |
| `CONTACT_EMAIL` | Página de contacto |
| `TIKTOK_SITE_TOKENS` | Tokens de verificación de URL extra, separados por coma (opcional) |
| `ALLOWED_TIKTOK_OPEN_IDS` | Acceso por invitación: `open_id`s (coma) que pueden conectar TikTok. Otra cuenta → se revoca su autorización, no se guarda nada y ve "invite-only". Vacía = abierto. El puente solo expone cuentas permitidas |
| `DATA_DIR` | Carpeta de `web.db`; el `Dockerfile` fija `/data` (el volumen) |

Secrets y modelo de amenazas: [docs/operations/SECURITY.md](../docs/operations/SECURITY.md).

## Datos

El sitio tiene su **propia** base SQLite, `web.db` en `DATA_DIR` (volumen `/data`), separada de la DB
del estudio (`data/shorts_pipeline.db`, que vive solo en el PC del creador). Esquema en `app/store.py`:

| Tabla | Contenido |
|---|---|
| `tiktok_accounts` | `open_id`, `display_name`, `access_token_enc`, `refresh_token_enc` (Fernet), `scope`, vencimientos, `updated_at` |
| `publishes` | `publish_id`, `open_id`, `lesson_id` (o `lesson_ref` del estudio), `status`, `created_at` |

Contenido estático versionado:

| Archivo | Lo genera |
|---|---|
| `app/data/catalog.json` | `python scripts/web/export_catalog.py` (desde la DB local; solo dominio público y licencia abierta, salvo `--include-owned`) |
| `app/lessons/lessons.json` + `*.mp4` | `python scripts/web/make_demo_lesson.py` (lección demo "Fear" con *Night of the Living Dead*). El MP4 no va a git (`*.mp4` está ignorado) |
| `app/verification/tiktok<TOKEN>.txt` | A mano, con el archivo que da el Developer Portal |

## Correr localmente

```powershell
cd web
python -m pip install -r requirements.txt
$env:DATA_DIR = "$env:TEMP\youlikeit-web"      # fuera del repo (web.db no está en .gitignore); si no, usa /data
uvicorn app.main:app --reload --port 8080       # http://127.0.0.1:8080
```

Para probar el login de TikTok en local hacen falta las keys, `TOKEN_ENC_KEY` y un `PUBLIC_BASE_URL`
registrado como redirect en el portal; normalmente se prueba directo en Railway.

## Desplegar

Desde `web/`, con el proyecto de Railway enlazado:

```powershell
cd web
railway up --no-gitignore --service youlikeit-web
```

- `--no-gitignore` sube también los MP4 de `app/lessons/` (ignorados por git). `.railwayignore` sigue
  excluyendo `tests/`, `.env`, `*.db` y `__pycache__/`.
- Railway construye con el `Dockerfile` (`uvicorn` en `0.0.0.0:$PORT` con `--proxy-headers`),
  healthcheck en `/healthz` y reinicio ante fallas (`railway.json`).
- Variables: `railway variable set --service youlikeit-web NOMBRE=valor` (no imprimirlas).

## Tests

```powershell
cd web
python -m pytest -q
```

TikTok va simulado (no hay red). Cubren páginas, OAuth (state, denegación, tokens cifrados,
revocación), envío de borrador, refresh de tokens, errores explicados al creador, verificación de URL
por lista permitida y el puente (`503` sin key, `401`, `404`, `409`, `422`, `502`). En CI corren en el
job `web` de `.github/workflows/tests.yml`, con sus propias dependencias.

## Relacionado

- Publicar desde el estudio: [docs/operations/UPLOADS.md](../docs/operations/UPLOADS.md)
- Revisión de la app de TikTok: [docs/operations/TIKTOK_APP_REVIEW.md](../docs/operations/TIKTOK_APP_REVIEW.md)
- Guion del video demo: [docs/operations/TIKTOK_DEMO_VIDEO.md](../docs/operations/TIKTOK_DEMO_VIDEO.md)
