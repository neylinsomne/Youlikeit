# YouLikeIt — landing site (review-only)

> **Superseded (2026-11-04).** The live public site is the FastAPI app in [`web/`](../web/README.md),
> deployed on Railway at **https://youlikeit-web-production.up.railway.app**. That site hosts the
> terms, privacy policy, TikTok Login Kit, "Send to TikTok as draft" and the studio bridge.
> This static nginx site is kept for history only; do not use its URLs in developer dashboards.
>
> Current values for TikTok / Google:
>
> | Field | Value |
> |---|---|
> | Website URL | `https://youlikeit-web-production.up.railway.app` |
> | Terms of Service | `https://youlikeit-web-production.up.railway.app/terms` |
> | Privacy Policy | `https://youlikeit-web-production.up.railway.app/privacy` |
> | TikTok Redirect URI | `https://youlikeit-web-production.up.railway.app/auth/tiktok/callback` |
>
> YouTube does not use a web redirect anymore: the local studio uses an installed-app OAuth client
> with the loopback redirect `http://127.0.0.1:8001/api/publish/youtube/callback`
> (see [docs/operations/UPLOADS.md](../docs/operations/UPLOADS.md)).

Static landing site whose **only purpose** is to host the public-facing pages
required to pass TikTok's data treatment / app review:

- A real-looking product page so reviewers see a coherent product
- Terms of Service URL
- Privacy Policy URL
- OAuth callback URL
- Contact info

**Nothing else gets deployed under this domain.** No backend, no DB, no
real product runs here. The actual YouLikeIt tooling (review dashboard,
content cycle, video producers) runs locally on the creator's machine.

Deployed at: **https://youlikeit.vara-alta.lat**

---

## Pages

| Path | Purpose |
|------|---------|
| `/` | Landing — hero, features, workflow, scopes |
| `/dashboard.html` | Static preview of the local review dashboard |
| `/terms.html` | Terms of Service |
| `/privacy.html` | Privacy Policy |
| `/contact.html` | Contact info + security disclosures |
| `/callback/` | OAuth callback for TikTok / YouTube authorization flows |
| `/healthz` | Health probe used by docker / cloudflared |

All pages are static HTML + Tailwind via CDN. No build step.

---

## Stack

- nginx 1.27 alpine
- Tailwind via CDN (no toolchain)
- Inter + Space Grotesk via Google Fonts
- One nginx container, ~25 MB image

---

## Local preview

Open the static files directly in a browser:

```powershell
cd d:\Youlikeit\youlikeit-web\public
start index.html
```

Or run the container locally:

```powershell
cd d:\Youlikeit\youlikeit-web
docker build -t youlikeit-web:latest .
docker run --rm -p 8088:80 --name youlikeit-web-test youlikeit-web:latest
# open http://localhost:8088
```

---

## Production deploy under `vara-alta.lat`

This follows **Option A** of the
[`DEPLOY_NEW_APP.md`](../../Vara_alta/DEPLOY_NEW_APP.md) guide — reuse the
existing `estudio_inmobiliario_app-network` and the running `iug-cloudflared`
tunnel. No tunnel changes are required.

### 1. Build and start the container

```powershell
cd d:\Youlikeit\youlikeit-web
docker compose build
docker compose up -d
```

Verify:

```powershell
docker ps --filter "name=youlikeit-web-prod"
docker logs youlikeit-web-prod --tail 20
```

### 2. Confirm it joined the shared network

```powershell
docker network inspect estudio_inmobiliario_app-network --format "{{range .Containers}}{{.Name}} {{end}}"
```

`youlikeit-web-prod` must appear next to `iug-cloudflared`.

### 3. Reachability from the tunnel

```powershell
docker exec iug-cloudflared wget -qO- http://youlikeit-web-prod:80/healthz
# expected: ok
```

### 4. Cloudflare published-application route

In `https://one.dash.cloudflare.com/` → **Networks → Tunnels → tun → Published
application routes** click **+ Add a published application route**:

| Field | Value |
|---|---|
| Subdomain | `youlikeit` |
| Domain | `vara-alta.lat` |
| Path | *(leave empty)* |
| Service · Type | `HTTP` |
| Service · URL | `youlikeit-web-prod:80` |

Save. Wait ~30 seconds for DNS / certificate.

### 5. Test

Open https://youlikeit.vara-alta.lat — should render the landing page.

Confirm the OAuth callback path works:
https://youlikeit.vara-alta.lat/callback?code=test_demo_code

Expected: a card showing the captured code with a "Copy" button.

---

## Updating the site

```powershell
cd d:\Youlikeit\youlikeit-web
# edit any .html under public/
docker compose build
docker compose up -d --force-recreate web
```

The previous container is replaced in <2 seconds.

---

## Rollback

If something goes wrong:

```powershell
docker compose down
# fall back to the last working image
docker compose up -d
```

If you need to remove the route entirely, delete it from the Cloudflare
dashboard — the subdomain stops resolving immediately.

---

## URLs to plug into developer dashboards

Historical values (no longer valid; use the table at the top of this file):

| Dashboard field | URL |
|---|---|
| Web/Desktop URL | `https://youlikeit.vara-alta.lat` |
| Terms of Service URL | `https://youlikeit.vara-alta.lat/terms.html` |
| Privacy Policy URL | `https://youlikeit.vara-alta.lat/privacy.html` |
| Redirect URI (OAuth) | `https://youlikeit.vara-alta.lat/callback` |

---

## Notes

- The site is **fully static**. No backend, no DB, no secrets in the image.
- The dashboard page is a **static preview** — the real review dashboard
  (`ex15_review_server.py`) runs locally on the creator's machine and is
  never exposed.
- Tokens, OAuth secrets, and credentials never touch this site or its
  container.
