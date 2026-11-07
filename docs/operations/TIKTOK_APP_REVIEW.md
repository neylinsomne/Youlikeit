# TikTok · Configuración del portal y revisión de la app

> Cómo está configurada la app de TikTok de YouLikeIt, qué falta y qué se envía a revisión.
> Código: `web/app/tiktok.py` (OAuth + Content Posting API) y `web/app/main.py` (rutas).
> Guion de los videos demo: [TIKTOK_DEMO_VIDEO.md](TIKTOK_DEMO_VIDEO.md).
> Última revisión: 2026-11-04.

## Estado

| Paso | Estado |
|---|---|
| Sitio público en Railway con términos, privacidad y contacto | ✅ <https://youlikeit-web-production.up.railway.app> |
| Login Kit + "Send to TikTok as draft" implementados y con tests | ✅ |
| Archivos de verificación de prefijo de URL publicados | ✅ (`web/app/verification/`, dos tokens) |
| Sandbox creado en el portal con productos, scopes y target user | ⚠️ Pendiente del dueño |
| `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` del Sandbox en Railway | ⚠️ Pendiente del dueño |
| Cuenta de prueba conectada en `/studio` | ⚠️ Pendiente (depende de las keys) |
| Videos demo grabados | ⚠️ Pendiente |
| Solicitud de revisión enviada | ⚠️ Pendiente |

## Configuración en el Developer Portal

<https://developers.tiktok.com/apps> → la app → (Sandbox y luego Production):

| Campo | Valor |
|---|---|
| Website URL | `https://youlikeit-web-production.up.railway.app` |
| Terms of Service URL | `https://youlikeit-web-production.up.railway.app/terms` |
| Privacy Policy URL | `https://youlikeit-web-production.up.railway.app/privacy` |
| Productos | **Login Kit** y **Content Posting API** |
| Scopes | `user.info.basic` y `video.upload`. **No** pedir `video.publish` |
| Redirect URI (Login Kit) | `https://youlikeit-web-production.up.railway.app/auth/tiktok/callback` |
| URL properties | Prefijo `https://youlikeit-web-production.up.railway.app/` |

El redirect lo arma el sitio con `PUBLIC_BASE_URL` + `/auth/tiktok/callback`: si cambia el dominio, cambian
los dos. Las URLs viejas de `youlikeit.vara-alta.lat` ya no se usan.

### Verificación del prefijo de URL

TikTok pide servir `/tiktok<TOKEN>.txt` con `tiktok-developers-site-verification=<TOKEN>`. El sitio solo
responde a tokens **en lista permitida** (si respondiera a cualquiera, un tercero podría verificar el
dominio en su app):

- Archivo en `web/app/verification/tiktok<TOKEN>.txt` (versionado; requiere redeploy), o
- Variable `TIKTOK_SITE_TOKENS=<TOKEN>[,<TOKEN2>]` en Railway (sin redeploy de código).

Comprobar: `curl https://youlikeit-web-production.up.railway.app/tiktok<TOKEN>.txt`.

### Sandbox

1. Crear el Sandbox con los mismos productos, scopes y redirect URI.
2. **Target users**: agregar la cuenta de TikTok con la que se va a grabar.
3. Cargar sus keys en Railway (no imprimirlas):
   `railway variable set --service youlikeit-web TIKTOK_CLIENT_KEY=... TIKTOK_CLIENT_SECRET=...`
4. Abrir `/studio` → **Continue with TikTok** → autorizar → enviar la lección demo como borrador.
5. Si TikTok rechaza la subida por la privacidad de la cuenta, ponerla en privada durante la revisión.

Sin auditoría, TikTok solo permite contenido privado o borradores, y como mucho 5 borradores pendientes
por 24 h por cuenta.

## Textos para la solicitud (en inglés, como el portal)

Coinciden con lo que muestran el sitio, la política de privacidad y los videos demo.

**App description**

> YouLikeIt helps people understand emotions and practice empathy through film. The website lets
> anyone explore public-domain films by emotion, with short guided reflections. Creators can connect
> their TikTok account and send short educational video lessons to their own TikTok inbox as drafts,
> then finish and post them in the TikTok app.

**Login Kit · `user.info.basic`**

> Used only to connect the creator's own TikTok account to the YouLikeIt Creator Studio. We read the
> open_id and display name to show which account is connected and to send drafts to that account. The
> avatar is displayed but not stored. Tokens are encrypted at rest, and "Disconnect and revoke access"
> revokes the token with TikTok and deletes the account data immediately.

**Content Posting API · `video.upload`**

> When the creator clicks "Send to TikTok as draft", we upload the selected lesson video (FILE_UPLOAD,
> single chunk) to the creator's TikTok inbox as a draft. Nothing is published automatically: the
> creator opens TikTok, reviews the draft, adds music, edits the caption and decides whether to post.
> We do not request video.publish.

## Videos demo

TikTok pide hasta 5 videos (≤ 50 MB cada uno), grabados en Sandbox y en el mismo dominio del Website
URL, mostrando los dos scopes funcionando. Guion, tabla de acciones y comando para comprimir:
[TIKTOK_DEMO_VIDEO.md](TIKTOK_DEMO_VIDEO.md).

## Después de la aprobación

1. Reemplazar en Railway las keys del Sandbox por las de Production.
2. Reconectar las cuentas en `/studio` (los tokens son por client key).
3. Probar un borrador desde el estudio local ([UPLOADS.md](UPLOADS.md)).
