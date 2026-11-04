# Video demo para la revisión de TikTok

TikTok exige uno o más videos (máximo 5, de hasta 50 MB cada uno) con el flujo
completo, grabados en **Sandbox** y en el **mismo dominio** del Website URL:
`https://youlikeit-web-production.up.railway.app`. Ambos permisos
(`user.info.basic` y `video.upload`) deben verse funcionando.

## Antes de grabar (una vez)

1. **Sandbox en el Developer Portal** (tu app → Sandbox → crear):
   - Productos: **Login Kit** y **Content Posting API**.
   - Scopes: `user.info.basic` y `video.upload` (nada más).
   - Redirect URI: `https://youlikeit-web-production.up.railway.app/auth/tiktok/callback`
   - Verificar el prefijo `https://youlikeit-web-production.up.railway.app/`. El archivo
     ya está publicado; si el Sandbox da un archivo distinto, el sitio solo sirve los tokens
     permitidos: agrégalo con `TIKTOK_SITE_TOKENS` en Railway.
   - **Target users**: agrega la cuenta de TikTok con la que vas a grabar.
2. **Keys del Sandbox en Railway** (el sitio las lee de ahí):
   ```
   railway variable set --service youlikeit-web TIKTOK_CLIENT_KEY=... TIKTOK_CLIENT_SECRET=...
   ```
3. Prueba una vez el flujo sin grabar. Si TikTok rechaza la subida por la privacidad de la
   cuenta, pon la cuenta de prueba en **privada** mientras dura la revisión.

## Grabación 1: navegador (Win + Alt + R con Xbox Game Bar, u OBS)

Graba la ventana del navegador con la **barra de direcciones visible**.

| # | Acción | Qué demuestra |
|---|---|---|
| 1 | Abrir `https://youlikeit-web-production.up.railway.app` y mostrar el dominio | Sitio y dominio = Website URL |
| 2 | Bajar por "How it works"; señalar *Terms of Service* y *Privacy Policy* en el encabezado | Sitio completo con políticas visibles |
| 3 | **Explore** → **Fear**: guía, pausa y lección de ejemplo (reproducir unos segundos) | Qué hace la app |
| 4 | **Creator studio**: mostrar la lista de permisos → **Continue with TikTok** | Inicio de Login Kit |
| 5 | Iniciar sesión con la cuenta del Sandbox; en la pantalla de TikTok mostrar los permisos → **Authorize** | Consentimiento de los scopes |
| 6 | De vuelta en el estudio: nombre y avatar de la cuenta conectada | `user.info.basic` |
| 7 | En "Your lessons" → **Send to TikTok as draft** | `video.upload` |
| 8 | Página "Delivered to your TikTok inbox as a draft" con los pasos | Resultado de la subida |
| 9 | (Opcional) **Disconnect and revoke access** | Control de datos del usuario |

## Grabación 2: celular (grabador de pantalla del teléfono)

1. Abrir TikTok → bandeja de entrada → notificación *"Your video is ready"*.
2. Abrir el borrador: se ve la lección (Fear · Miedo).
3. Mostrar que se puede editar y elegir sonido; no hace falta publicar.

Sube las dos grabaciones como videos separados en el formulario. Si alguna pasa de 50 MB,
se comprime así:

```
ffmpeg -i grabacion.mp4 -vf "scale=-2:1080" -c:v libx264 -crf 28 -preset veryfast -c:a aac -b:a 96k grabacion_50mb.mp4
```

## Texto para "Explain how each product and scope works"

Ya coincide con lo que se ve en el video (Send to TikTok → borrador en el inbox, sin
publicación automática). No pidas `video.publish`.
