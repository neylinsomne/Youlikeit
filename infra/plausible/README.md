# Plausible Analytics — self-host (infra)

> Owner: [docs/agents/ANALYTICS_AGENT.md](../../docs/agents/ANALYTICS_AGENT.md)
> Stack: [docker-compose.plausible.yml](../../docker-compose.plausible.yml)

Estos son los pasos de **infra** de la Fase 1 — los ejecuta el owner del host
y del DNS (no se pueden automatizar desde el repo). Las Fases 3-6 (cliente,
bridge, CLI, tests) sí son código y ya están en el árbol.

---

## 0. Pre-requisitos

- Docker daemon corriendo (`docker --version` → 29.x verificado)
- Acceso al panel de Cloudflare del tunnel `tun` (el mismo de `youlikeit-web`)
- `openssl` o Python para generar el `SECRET_KEY_BASE`

## 1. Configurar el env

```powershell
cd d:\Youlikeit
Copy-Item .env.plausible.example .env.plausible
```

Generar `SECRET_KEY_BASE` y pegarlo en `.env.plausible`:

```powershell
# Con Python (sin openssl en Windows)
python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(48)).decode())"
```

Rellenar también `POSTGRES_PASSWORD` (y la misma password dentro de
`DATABASE_URL`). `BASE_URL` ya viene como `https://analytics.vara-alta.lat`.

## 2. Levantar el stack

```powershell
docker compose -f docker-compose.plausible.yml up -d
docker compose -f docker-compose.plausible.yml ps        # los 3 → healthy en <60s
docker compose -f docker-compose.plausible.yml logs -f plausible
```

Verificar local:

```powershell
curl http://localhost:8000/api/health        # → {"clickhouse":"ok","postgres":"ok"}
```

## 3. Crear el admin + el sitio

`DISABLE_REGISTRATION=invite_only`, así que el primer usuario se crea por CLI:

```powershell
# El primer registro vía UI queda como admin cuando no hay usuarios todavía.
# Abrir http://localhost:8000/register y crear la cuenta admin.
```

Luego en el panel: **+ Add a website**
- Domain: `youlikeit.vara-alta.lat`
- Timezone: `America/Bogota`

Esto te da el `data-domain` y el snippet (ya instrumentado en los HTML).

## 4. Generar la API key (Stats API)

Panel → **Site Settings → API Keys → New API Key**. Copiar la key al `.env`
del pipeline (NO al `.env.plausible`):

```
PLAUSIBLE_BASE_URL=https://analytics.vara-alta.lat
PLAUSIBLE_API_KEY=<la key del panel>
PLAUSIBLE_SITE_ID=youlikeit.vara-alta.lat
```

## 5. Cloudflare Tunnel route

Mismo tunnel `tun` que `youlikeit-web` (ver `youlikeit-web/PASOS_DEPLOY.md`):

1. https://one.dash.cloudflare.com/ → **Networks → Tunnels → `tun`**
2. **Published application routes → + Add a published application route**

   | Campo | Valor |
   |---|---|
   | Subdomain | `analytics` |
   | Domain | `vara-alta.lat` |
   | Path | *(vacío)* |
   | Service · Type | `HTTP` |
   | Service · URL | `plausible:8000` |

   > ⚠️ Si el tunnel corre en un container que NO comparte red con `plausible`,
   > usar `http://host.docker.internal:8000` o conectar `iug-cloudflared` a la
   > red del compose. El compose bindea `127.0.0.1:8000` por seguridad.

3. **Save** → esperar ~30s.

Verificar público:

```powershell
curl https://analytics.vara-alta.lat/api/health   # → 200 OK
```

## 6. Confirmar instrumentación

Abrir `https://youlikeit.vara-alta.lat` desde 3 navegadores distintos
(hard refresh, sin ad-block) → el panel debe mostrar 3 unique visitors.

---

## Operación

```powershell
# Estado
docker compose -f docker-compose.plausible.yml ps

# Apagar (no afecta el pipeline GPU ni youlikeit-web)
docker compose -f docker-compose.plausible.yml down

# Apagar borrando datos (¡destructivo!)
docker compose -f docker-compose.plausible.yml down -v
```

## Privacy

Plausible CE no recolecta IPs ni user agents persistentes, sin cookies
(GDPR/CCPA/PECR). La política pública lo declara en
`youlikeit-web/public/privacy.html § Analytics`. No persistir PII en SQLite
end-to-end (ver anti-patrones del handbook).
