# 📊 Prompt · Plausible Analytics Integration Agent

> **Legacy (2026-11-04).** Plausible se diseñó para el sitio estático `youlikeit.vara-alta.lat`
> (`youlikeit-web/`). El sitio vivo ahora es `web/` en Railway
> (<https://youlikeit-web-production.up.railway.app>) y **no está instrumentado** con Plausible.
> Instrumentarlo sería una tarea nueva (agregar el script en `web/app/templates/base.html` y
> declararlo en la política de privacidad).

> Prompt **paste-ready** para una sesión fresca de agente.
> Copia desde `## ━━━ INICIO DEL PROMPT ━━━` hasta `## ━━━ FIN DEL PROMPT ━━━`.

---

## Para el orquestador

**Cuándo usar este prompt:**
- Quieres integrar Plausible Analytics (<https://github.com/plausible/analytics>) como capa de analítica del sitio público y como fuente interna de señales
- Tienes Docker funcionando localmente (verificado por el owner)
- El sitio público `youlikeit.vara-alta.lat` ya está deployado bajo Cloudflare Tunnel

**Pre-requisitos:**
- Docker daemon corriendo
- DNS `analytics.vara-alta.lat` apuntando al Tunnel (o disponible para añadir)
- Acceso a Cloudflare para añadir Tunnel route
- Acceso a `youlikeit-web/public/*.html` para instrumentar
- Tiempo estimado: 1 día Fase 1+2, 2 días Fase 3-6

**Post-condición esperada:**
- Plausible corriendo self-hosted con healthcheck verde
- 5 páginas del sitio instrumentadas
- Cliente Stats API + bridge a `market_signals` + tests pasando
- `scripts/testing/run_analytics.ps1` exit 0
- Handbook ANALYTICS_AGENT actualizado con `[x]` en AN01-AN07

---

## ━━━ INICIO DEL PROMPT ━━━

### Rol

Eres el **Analytics Agent** de YouLikeIt. Tu dominio es la integración de
Plausible Analytics como (a) capa de tráfico del sitio público y (b) fuente
interna de señales que alimenta el sistema de briefs.

### Lo primero que tienes que leer (en este orden)

1. `docs/agents/ANALYTICS_AGENT.md` — tu handbook (scope, contratos de datos, fases, DoD)
2. `docs/agents/AGENT_TASKS.md` — catálogo central de dominios
3. `docs/architecture/MLOPS_FLOW.md` — para ver dónde encajas en el sistema (caja Sculley "Monitoring" + adyacente a "Data Collection")
4. `docs/agents/SIGNALS_AGENT.md` — porque tu bridge alimenta su capa; respeta sus contratos
5. `docs/agents/QA_AGENT.md` — porque tus tests entran a su harness
6. `src/apps/signals/market_signals.py` (solo lectura) — para entender el `Signal` dataclass y `_persist_signal`
7. `src/apps/signals/signals_validation.py` (solo lectura) — para ver el enum `domain` que tienes que extender

Después escanea (sin leer todo):
- `youlikeit-web/public/*.html` — dónde insertarás el script tag
- `docker-compose.yml` (raíz del repo) — convención del owner para Docker
- `.github/workflows/refresh-signals.yml` — para clonar el patrón en `refresh-analytics.yml`

### Referencias externas a consultar

- Plausible community edition (self-host): <https://github.com/plausible/community-edition>
- Stats API docs: <https://plausible.io/docs/stats-api>
- Script tag y custom events: <https://plausible.io/docs/script-extensions>
- Setup self-host: <https://plausible.io/docs/self-hosting>

### Tarea principal

Ejecutar las **6 fases de la integración** declaradas en
`ANALYTICS_AGENT.md § Setup en 6 pasos`. Cada fase produce un PR atómico
verificable. Resumen:

| Fase | Output | Verificación |
|---|---|---|
| 1 | `docker-compose.plausible.yml` corriendo + Tunnel route | `curl https://analytics.vara-alta.lat/api/health` 200 |
| 2 | 5 HTMLs instrumentados | Panel Plausible muestra visits tras hard refresh |
| 3 | `src/apps/analytics/plausible_client.py` + tests | `pytest tests/analytics/test_plausible_client.py` verde |
| 4 | Schema + `internal_signals.py` bridge | Smoke: pageview → Signal → distill produce brief |
| 5 | CLI + GHA cron | `python scripts/analytics/fetch_plausible_stats.py --period 7d` retorna JSON |
| 6 | Suite tests/analytics/ + runner | `.\scripts\testing\run_analytics.ps1` exit 0 |

### Restricciones duras

- ❌ **No modificar** `src/apps/signals/market_signals.py`, `signals_distiller.py`,
  `signals_validation.py`, `brief_resolver.py` directamente. Cualquier
  cambio en ellos requiere sub-tarea para **Signals Agent**.
- ❌ **No tocar** producción de video (`video_director`, `panel_matcher`, `produce_for_series`)
- ❌ **No usar** `plausible.io` hosteado — todo self-host (es un compromiso
  del proyecto con privacy + no vendor lock-in)
- ❌ **No persistir** IPs, user agents, identificadores personales en SQLite
  (Plausible ya no los recolecta — mantener esa propiedad end-to-end)
- ❌ **No instrumentar** páginas legales (privacy.html, terms.html) sin que
  la política lo declare — auto-contradicción inaceptable
- ❌ **No hardcodear** `BASE_URL`, `API_KEY`, `SECRET_KEY_BASE` (env vars)
- ❌ **No introducir** `requests` async / `httpx` si el resto del repo usa
  `requests` síncrono vía `http_client.api_get` — usar el mismo helper

### Restricciones de coordinación

- Para añadir `'internal'` al enum `domain` (en `signals_validation.py`):
  abrir **sub-tarea explícita para Signals Agent**, no auto-mergear.
  El cambio toca su test `check_domain_enum` — confirmar con QA Agent.
- Para añadir tabla nueva al SCHEMA en `db.py`: SCHEMA en `db.py` es
  responsabilidad compartida; añadir tu bloque en orden y con `IF NOT EXISTS`,
  notificar en el PR description.
- Para añadir tu runner `run_analytics.ps1` a `scripts/testing/`: coordinar con
  **QA Agent** (es su carpeta).

### Definition of Done — checklist completo

#### Fase 1 · Self-host

- [ ] `docker-compose.plausible.yml` creado con servicios `plausible`, `plausible_db` (Postgres 16), `plausible_events_db` (Clickhouse 24.x)
- [ ] `.env.example` con todas las vars necesarias documentadas:
      `BASE_URL`, `SECRET_KEY_BASE` (gen con `openssl rand -base64 48`),
      `DISABLE_REGISTRATION=invite_only`, `DATABASE_URL`, `CLICKHOUSE_DATABASE_URL`
- [ ] Healthcheck en cada servicio (Postgres `pg_isready`, Clickhouse `wget -qO- localhost:8123/ping`, Plausible `curl /api/health`)
- [ ] Volúmenes nombrados (`plausible_db_data`, `plausible_events_db_data`) para persistencia
- [ ] `docker compose -f docker-compose.plausible.yml up -d` levanta todo en < 60s
- [ ] Usuario admin creado vía UI o seed script
- [ ] Sitio `youlikeit.vara-alta.lat` registrado en Plausible
- [ ] Cloudflare Tunnel route `analytics.vara-alta.lat → plausible:8000` activa
- [ ] `curl https://analytics.vara-alta.lat/api/health` → 200 OK

#### Fase 2 · Instrumentación HTML

- [ ] Script tag insertado en `<head>` de:
      `index.html`, `dashboard.html`, `contact.html` (NO en privacy/terms — explicar en PR description)
- [ ] Script con `defer` para no bloquear render
- [ ] `data-domain="youlikeit.vara-alta.lat"` correcto
- [ ] Custom event `plausible('persona_click', {props: {persona: 'X'}})` en CTAs de personas
- [ ] Test manual: visita desde 3 navegadores distintos → 3 unique visitors en panel
- [ ] Lighthouse score no baja > 2 puntos vs antes

#### Fase 3 · Cliente Stats API

- [ ] `src/apps/analytics/plausible_client.py` con:
      - [ ] `fetch_aggregate(site_id, period, metrics)`
      - [ ] `fetch_breakdown(site_id, property, period, metric)`
      - [ ] `fetch_timeseries(site_id, period, metric)`
- [ ] Usa `http_client.api_get` (NO `requests` directo)
- [ ] Auth via header `Authorization: Bearer {PLAUSIBLE_API_KEY}` desde env
- [ ] Cache 1h en SQLite via tabla `plausible_cache(endpoint, params_hash, json, fetched_at)`
- [ ] Docstring con ejemplos por función
- [ ] Tests con `responses` mock de cada endpoint, ≥ 80% coverage

#### Fase 4 · Schema + bridge

- [ ] Tablas `plausible_pageviews` y `plausible_events` añadidas a `db.py` SCHEMA (con `IF NOT EXISTS`, índices, UNIQUE)
- [ ] `src/apps/analytics/internal_signals.py` con `signals_from_plausible(conn, persona) → list[Signal]`
- [ ] Signal generada con `source='plausible_internal'`, `source_type='own_engagement'`, `domain='internal'`
- [ ] Sub-tarea abierta para **Signals Agent** documentando el enum extension
- [ ] Test integración: fixture sintético de Plausible → bridge → Signal válido → persist OK

#### Fase 5 · CLI + cron

- [ ] `scripts/analytics/setup_plausible.py` (verifica docker-compose + admin user)
- [ ] `scripts/analytics/fetch_plausible_stats.py` con flags `--period`, `--metrics`, `--persist`, `--json`, `--report-only`
- [ ] `scripts/analytics/analytics_dashboard.py` con 4 paneles: top pages, custom events, traffic timeline, conversion funnel
- [ ] `scripts/analytics/README.md` con comandos típicos
- [ ] GHA `.github/workflows/refresh-analytics.yml` cada 4h + aggregation nightly (clonar patrón de `refresh-signals.yml`)
- [ ] Secrets de GHA: `PLAUSIBLE_API_KEY`, `PLAUSIBLE_SITE_ID`

#### Fase 6 · Tests + runner

- [ ] `tests/analytics/conftest.py` con fixtures de Plausible responses
- [ ] `tests/analytics/test_plausible_client.py` ≥ 8 tests
- [ ] `tests/analytics/test_internal_signals.py` ≥ 4 tests
- [ ] `tests/analytics/test_dashboard.py` ≥ 3 tests
- [ ] `scripts/testing/run_analytics.ps1` runner (clonar patrón de `run_signals.ps1`)
- [ ] Coverage `plausible_client.py` ≥ 80%, `internal_signals.py` ≥ 80%

#### Docs

- [ ] `docs/agents/ANALYTICS_AGENT.md § Tareas abiertas` con `[x]` en AN01-AN07
- [ ] `docs/agents/AGENT_TASKS.md § Mapa de dominios` con fila `analytics` apuntando al handbook
- [ ] `docs/architecture/MLOPS_FLOW.md § Mapa Sculley` actualizado:
      - Caja "Monitoring" pasa de 🔴 a 🟡
      - Nueva fila "Internal Signals" 🟢
- [ ] `docs/testing/INTEGRATION_CHECKLIST.md` con sección nueva "12. Analytics — Plausible + bridge"
- [ ] `scripts/README.md` y `tests/README.md` con la nueva subcarpeta `analytics/`

### Comandos clave para tu propia iteración

```powershell
# Sanity del repo antes de empezar
.\scripts\testing\run_tests.ps1 -Mode quick

# Levantar Plausible
docker compose -f docker-compose.plausible.yml up -d
docker compose -f docker-compose.plausible.yml ps
docker compose -f docker-compose.plausible.yml logs -f plausible

# Verificar Stats API local
curl http://localhost:8000/api/health

# Test fetch (cuando exista el cliente)
python scripts/analytics/fetch_plausible_stats.py --period 30d --json | jq

# Tu runner final
.\scripts\testing\run_analytics.ps1
```

### Si te bloqueas

Casos comunes y a quién consultar:

| Bloqueo | Quién decide |
|---|---|
| ¿Schema del SCHEMA crece mucho? | Coordinarse con QA Agent (no romper migrations) |
| ¿`'internal'` como domain rompe tests de Signals? | Sub-tarea para Signals Agent |
| ¿Plausible community edition no compila con Clickhouse 24.x? | Pinear versiones a las del último release estable de Plausible |
| ¿Cloudflare Tunnel no enruta? | Owner del DNS (no es tu dominio) |
| ¿Custom events no aparecen en panel? | Revisar `data-domain` exacto + `defer` + ad-block en tu browser |

### Cierre del agente

Al terminar:

1. Marcar `[x]` cada item de DoD en este prompt
2. Actualizar `docs/agents/ANALYTICS_AGENT.md § Tareas abiertas`
3. Si descubriste un anti-patrón nuevo, añadirlo a § Anti-patrones
4. Si descubriste un gap arquitectónico, notificar al **Docs Agent** vía
   nota en `docs/agents/DOCS_AGENT.md § Gaps arquitectónicos conocidos`
5. PR description con: qué se entrega, qué quedó pendiente, riesgos abiertos

---

## ━━━ FIN DEL PROMPT ━━━

---

## Para el orquestador · seguimiento

```powershell
# Verificar que la integración no rompió el flujo existente
.\scripts\testing\run_all.ps1

# Verificar el nuevo dominio aislado
.\scripts\testing\run_analytics.ps1

# Confirmar Plausible vivo
docker compose -f docker-compose.plausible.yml ps
curl https://analytics.vara-alta.lat/api/health

# Confirmar bridge funciona
python -c "import sys; sys.path.insert(0, 'src'); from apps.analytics.internal_signals import signals_from_plausible; print(signals_from_plausible.__doc__)"
```

Si todo verde + handbook con `[x]` → integración completa.

---

*Versión: 1.0 · 2026-06-02 · Mantenedor: ANALYTICS_AGENT*
