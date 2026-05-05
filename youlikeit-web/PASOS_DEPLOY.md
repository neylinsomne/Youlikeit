# YouLikeIt — pasos para terminar el deploy

> Este dominio es **solo** para que TikTok pase su revision de tratado de
> datos. No se va a desplegar nada mas aqui.

Estado actual:

- ✅ Sitio construido en `d:\Youlikeit\youlikeit-web\public\`
- ✅ Imagen Docker `youlikeit-web:latest` ya construida
- ✅ Container `youlikeit-web-prod` corriendo y `healthy`
- ✅ Conectado a `estudio_inmobiliario_app-network` (la misma red que `iug-cloudflared`)
- ✅ Probado: `wget http://youlikeit-web-prod/healthz` → `ok`
- ⏳ Falta: agregar el route en Cloudflare (1 minuto)
- ⏳ Falta: pegar las URLs en TikTok Developer Portal

---

## 1. Agregar el route en Cloudflare (1 minuto)

1. Abrir **https://one.dash.cloudflare.com/**
2. Ir a **Networks → Tunnels**
3. Click en el tunel `tun`
4. Pestana **Published application routes**
5. Click **+ Add a published application route**
6. Llenar:

   | Campo | Valor |
   |---|---|
   | Subdomain | `youlikeit` |
   | Domain | `vara-alta.lat` |
   | Path | *(dejar vacio)* |
   | Service · Type | `HTTP` |
   | Service · URL | `youlikeit-web-prod:80` |

7. Click **Save**
8. Esperar ~30 segundos para que Cloudflare propague DNS y emita certificado

### Verificar

```powershell
nslookup youlikeit.vara-alta.lat
# Debe responder con un CNAME a <tunnel-id>.cfargotunnel.com
```

Abrir en el navegador: **https://youlikeit.vara-alta.lat**

Probar tambien:
- https://youlikeit.vara-alta.lat/dashboard.html
- https://youlikeit.vara-alta.lat/terms.html
- https://youlikeit.vara-alta.lat/privacy.html
- https://youlikeit.vara-alta.lat/contact.html
- https://youlikeit.vara-alta.lat/callback?code=test_demo (deberia mostrar "Authorization complete" con el codigo `test_demo`)

---

## 2. Pegar las URLs en TikTok Developer Portal

Abrir **https://developers.tiktok.com/apps** → tu app → **Edit basic info**:

| Campo del formulario | Valor a pegar |
|---|---|
| **Web/Desktop URL** | `https://youlikeit.vara-alta.lat` |
| **Terms of Service URL** | `https://youlikeit.vara-alta.lat/terms.html` |
| **Privacy Policy URL** | `https://youlikeit.vara-alta.lat/privacy.html` |
| **Redirect URI** (en Login Kit / Content Posting API) | `https://youlikeit.vara-alta.lat/callback` |

Asegurate que en **Domain verification** uses el archivo de verificacion que
TikTok te pida — si te pide subir `tiktok-developers-site-verification.txt`
(o similar), avisas y lo agregamos a `public/`.

---

## 3. Pegar las URLs en Google Cloud Console (cuando lo necesites)

Para YouTube OAuth (Nico Flor / oh_tarab / Oh Que Sera) — solo cuando crees
un nuevo proyecto OAuth, los actuales ya estan corriendo con el redirect
local:

| Campo | Valor |
|---|---|
| Authorized JavaScript origins | `https://youlikeit.vara-alta.lat` |
| Authorized redirect URIs | `https://youlikeit.vara-alta.lat/callback` |

---

## 4. Comandos utiles

### Ver el estado del container

```powershell
docker ps --filter "name=youlikeit-web"
docker logs youlikeit-web-prod --tail 30
```

### Reiniciar despues de un cambio en `public/`

```powershell
cd d:\Youlikeit\youlikeit-web
docker compose build
docker compose up -d --force-recreate web
```

### Apagar el sitio (no afecta el tunel ni INMU)

```powershell
cd d:\Youlikeit\youlikeit-web
docker compose down
```

### Volver a prenderlo

```powershell
cd d:\Youlikeit\youlikeit-web
docker compose up -d
```

---

## 5. Si TikTok rechaza otra vez

Cosas comunes que pide y que ya estan cubiertas:

- ✅ Web/Desktop URL accesible publicamente
- ✅ Terms of Service URL diferente del Privacy Policy URL
- ✅ Privacy Policy explica explicitamente cada scope
- ✅ Sitio se ve "como un producto real" (landing + dashboard preview)
- ✅ Email de contacto y forma de reportar issues
- ✅ Redirect URI funcional (devuelve 200 con un mensaje sobre el codigo)

Si rechazan, el feedback va a estar en el dashboard de TikTok — me lo
pasas literal y ajustamos exactamente lo que pidan.

---

## 6. Troubleshooting

**El subdominio no resuelve**
- Espera 1-2 minutos despues de Save en Cloudflare
- `nslookup youlikeit.vara-alta.lat` debe dar CNAME a `*.cfargotunnel.com`

**502 Bad Gateway**
- `docker ps --filter "name=youlikeit-web"` debe mostrar `Up X (healthy)`
- Si esta `Restarting`, ver `docker logs youlikeit-web-prod --tail 50`

**522 Connection timed out**
- Verificar que el container esta en la red:
  `docker network inspect estudio_inmobiliario_app-network --format "{{range .Containers}}{{.Name}} {{end}}"`
- Debe aparecer `youlikeit-web-prod`

**El callback dice "No authorization data" cuando lo abro directo**
- Es lo correcto. Solo muestra el codigo cuando llega con `?code=...` desde TikTok/Google
- Para probar manualmente: `https://youlikeit.vara-alta.lat/callback?code=demo123`

**Quiero cambiar texto de las paginas**
1. Editar el `.html` correspondiente en `d:\Youlikeit\youlikeit-web\public\`
2. `cd d:\Youlikeit\youlikeit-web && docker compose build && docker compose up -d --force-recreate web`
3. Recargar el navegador (Ctrl+Shift+R para saltar cache)

---

## Resumen de URLs

```
https://youlikeit.vara-alta.lat/              → Landing
https://youlikeit.vara-alta.lat/dashboard.html → Dashboard preview (mock)
https://youlikeit.vara-alta.lat/terms.html     → Terms of Service
https://youlikeit.vara-alta.lat/privacy.html   → Privacy Policy
https://youlikeit.vara-alta.lat/contact.html   → Contact info
https://youlikeit.vara-alta.lat/callback       → OAuth callback
https://youlikeit.vara-alta.lat/healthz        → Health probe (returns "ok")
```
