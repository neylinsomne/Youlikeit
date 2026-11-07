# Analytics Agent · Handbook

> **Legacy (2026-11-04).** Plausible se diseñó para el sitio estático `youlikeit.vara-alta.lat`
> (`youlikeit-web/`). El sitio vivo ahora es `web/` en Railway
> (<https://youlikeit-web-production.up.railway.app>) y **no está instrumentado** con Plausible.
> Instrumentarlo sería una tarea nueva (agregar el script en `web/app/templates/base.html` y
> declararlo en la política de privacidad).

> **Scope**: integración de Plausible Analytics + ingestión de su Stats API
> como fuente interna de `market_signals`. Owner del dashboard de tráfico,
> métricas de conversión del sitio público, retention proxies cuando aplique.
> Este agente **NO** toca render, NO toca scraping externo, NO toca scoring.

---

## Por qué Plausible

- **Open source** (AGPL v3) — self-hostable, sin lock-in
- **Privacy-first** — GDPR/CCPA/PECR compliant sin cookies
- **Lightweight** — script ~1KB, no impacta Lighthouse del sitio público
- **Stats API JSON** — endpoint `/api/v1/stats/*` consumible por nuestra capa de signals
- **Compatible con Docker** — encaja con stack actual (Cloudflare Tunnel + nginx + Docker Compose)
- **Aligned con TikTok review** — refuerza el discurso de "single creator, no tracking de usuarios"

Referencia upstream: <https://github.com/plausible/analytics>
Community edition (self-host): <https://github.com/plausible/community-edition>
Stats API docs: <https://plausible.io/docs/stats-api>

---

## Archivos bajo tu dominio

| Path | Rol |
|---|---|
| `src/apps/analytics/plausible_client.py` | Cliente HTTP a Stats API (a crear) |
| `src/apps/analytics/internal_signals.py` | Adapter: page views → market_signals (a crear) |
| `scripts/analytics/setup_plausible.py` | Bootstrap: docker-compose + DB init |
| `scripts/analytics/fetch_plausible_stats.py` | CLI runner para fetch periódico |
| `scripts/analytics/analytics_dashboard.py` | Vista CLI de tráfico/conversiones |
| `tests/analytics/` | Suite pytest del dominio |
| `docker-compose.plausible.yml` | Stack Plausible aislado |
| `.github/workflows/refresh-analytics.yml` | Cron (4h fetch + nightly aggregation) |
| `youlikeit-web/public/*.html` | **lectura** — solo para insertar el script tag |

## Archivos que NO puedes tocar

- Capa `signals/*` ajena (market_signals.py, brief_resolver.py, signals_distiller.py) →
  **Signals Agent**. Si tu data debe alimentar briefs, abre sub-tarea.
- Render / rotator / scorer → otros dominios.
- `tokens/*.json`, OAuth, uploads → **Uploads Agent**.

---

## Contratos de datos

### Tabla `plausible_pageviews` (escribe este agente)

```sql
CREATE TABLE IF NOT EXISTS plausible_pageviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page TEXT NOT NULL,             -- ruta normalizada (/, /dashboard.html, /persona/deep_mind)
    visitors INTEGER DEFAULT 0,
    pageviews INTEGER DEFAULT 0,
    bounce_rate REAL,
    visit_duration REAL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    source TEXT DEFAULT 'plausible',
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(page, period_start, period_end)
);
```

### Tabla `plausible_events` (custom events)

```sql
CREATE TABLE IF NOT EXISTS plausible_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,       -- 'persona_click', 'cta_signup', 'pdf_view'
    page TEXT,
    count INTEGER DEFAULT 0,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    raw_props TEXT,                 -- JSON de propiedades extras
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_name, page, period_start, period_end)
);
```

### Bridge a `market_signals` (capa interna)

`internal_signals.py` agrega tráfico de una persona como **Signal de dominio
`internal`** que puede competir en el rotator:

```python
Signal(
    source="plausible_internal",
    source_type="own_engagement",
    domain="internal",  # nuevo enum value (requiere migrar signals_validation)
    title=f"Persona {persona} traffic spike +{delta}%",
    raw_score=visitors_24h,
    raw_meta={"page": page, "bounce_rate": br, "visit_duration": vd}
)
```

> ⚠️ Añadir `'internal'` al enum de domains requiere PR coordinada con
> **Signals Agent** y **QA Agent** (test `check_domain_enum`).

---

## Setup en 6 pasos (Definition of Done de la integración inicial)

### Fase 1 · Self-host Plausible (Docker)

- [ ] Crear `docker-compose.plausible.yml` con servicios `plausible`, `plausible_db` (Postgres), `plausible_events_db` (Clickhouse)
- [ ] Configurar `.env` con `SECRET_KEY_BASE`, `BASE_URL=https://analytics.vara-alta.lat`, `DISABLE_REGISTRATION=invite_only`
- [ ] Levantar: `docker compose -f docker-compose.plausible.yml up -d`
- [ ] Crear usuario admin + sitio `youlikeit.vara-alta.lat`
- [ ] Cloudflare Tunnel: añadir route `analytics.vara-alta.lat → plausible:8000`

### Fase 2 · Instrumentar el sitio público

- [ ] Insertar `<script defer data-domain="youlikeit.vara-alta.lat" src="https://analytics.vara-alta.lat/js/script.js"></script>` en `<head>` de:
  - [ ] `youlikeit-web/public/index.html`
  - [ ] `youlikeit-web/public/dashboard.html`
  - [ ] `youlikeit-web/public/contact.html`
  - [ ] `youlikeit-web/public/privacy.html`
  - [ ] `youlikeit-web/public/terms.html`
- [ ] Custom events: añadir `plausible('persona_click', {props: {persona: 'deep_mind'}})` en CTAs relevantes
- [ ] Verificar en panel Plausible que las visitas llegan (test manual)

### Fase 3 · Cliente de Stats API

- [ ] Crear `src/apps/analytics/plausible_client.py` con:
  - [ ] `fetch_aggregate(site_id, period, metrics)` → Stats API `/api/v1/stats/aggregate`
  - [ ] `fetch_breakdown(site_id, property, period)` → `/api/v1/stats/breakdown`
  - [ ] `fetch_timeseries(site_id, period)` → `/api/v1/stats/timeseries`
  - [ ] Auth con `PLAUSIBLE_API_KEY` env var
  - [ ] Cache 1h en SQLite para no martillar
- [ ] Tests con `responses` mock de cada endpoint

### Fase 4 · Persistencia + bridge a signals

- [ ] Añadir las 2 tablas al `SCHEMA` de `db.py` (idempotente)
- [ ] Crear `internal_signals.py` con `signals_from_plausible(conn, persona) → list[Signal]`
- [ ] Coordinación con Signals Agent: añadir `'internal'` al `domain` enum + actualizar `check_domain_enum`
- [ ] Test integración: mock Plausible → persist → bridge crea Signal → distill genera brief

### Fase 5 · CLI + cron

- [ ] `scripts/analytics/fetch_plausible_stats.py` con flags `--period`, `--metrics`, `--persist`, `--json`
- [ ] `scripts/analytics/analytics_dashboard.py` con paneles (top pages, custom events, conversion funnel)
- [ ] GHA `.github/workflows/refresh-analytics.yml` cada 4h + agregación nightly

### Fase 6 · Tests del dominio

- [ ] `tests/analytics/test_plausible_client.py` — mock HTTP de cada endpoint
- [ ] `tests/analytics/test_internal_signals.py` — bridge end-to-end
- [ ] `tests/analytics/test_analytics_dashboard.py` — render OK con datos sintéticos
- [ ] `scripts/testing/run_analytics.ps1` — runner del dominio

---

## Comando único de verificación

```powershell
.\scripts\testing\run_analytics.ps1
```

Fases del runner:
1. `pytest tests/analytics/`
2. Smoke contra Plausible local (si `PLAUSIBLE_API_KEY` set): fetch `aggregate` → debe retornar JSON
3. Smoke bridge: pageview sintético → `Signal` válido → persist → distill produce brief

---

## Métricas que sigues

| Métrica | Baseline | Cómo medir |
|---|---|---|
| Plausible uptime | ≥ 99% | docker healthcheck |
| Latency p95 Stats API | < 500ms | log en `plausible_client.py` |
| Coverage `plausible_client.py` | ≥ 80% | pytest --cov |
| Signals internos por persona | ≥ 1 / día | `SELECT COUNT(*) FROM market_signals WHERE source='plausible_internal'` |
| Custom events tracked | ≥ 5 | panel Plausible |
| Costo Plausible | $0 (self-host) | n/a |

---

## Anti-patrones específicos

- ❌ Llamar a `plausible.io/api/...` directo en producción sin self-host
  (rompe el discurso de privacy + introduce vendor lock-in)
- ❌ Persistir IPs o user agents en `plausible_events` (rompe GDPR)
- ❌ Modificar `market_signals` o `persona_briefs` directamente — solo a través
  del bridge `internal_signals.py`
- ❌ Insertar tracking en páginas legales (privacy, terms) sin que la propia
  política lo declare (auto-contradicción)
- ❌ Hardcodear `BASE_URL` (debe venir de env var)
- ❌ Tests que hacen requests reales a Plausible sin `@pytest.mark.network`

---

## Tareas abiertas conocidas

Tracking de este dominio (estado 2026-06-02):

- [~] **AN01**: Self-host Plausible (Fase 1) — **código listo**
      (`docker-compose.plausible.yml`, `.env.plausible.example`, configs
      Clickhouse, `infra/plausible/README.md`). Falta la mano del owner:
      `docker compose up -d`, crear admin, route en Cloudflare Tunnel.
- [x] **AN02**: Instrumentar páginas del sitio (Fase 2) — index/dashboard/contact
      con script tag `defer` + `assets/analytics.js` (eventos `cta_click`,
      helper `persona_click`). Legales (privacy/terms) NO instrumentadas;
      privacy.html § 4.1 declara el uso de Plausible. Falta verificación manual
      en panel (requiere AN01 vivo).
- [x] **AN03**: Cliente Stats API + tests (Fase 3) — `plausible_client.py`
      (aggregate/breakdown/timeseries + cache 1h SQLite + healthcheck),
      coverage 88.6%.
- [x] **AN04**: Schema + bridge a signals (Fase 4) — 3 tablas en `db.py`
      (`plausible_cache/pageviews/events`) + `internal_signals.py`. Sub-tarea
      abierta para Signals Agent (ver SIGNALS_AGENT.md § domain += internal).
- [x] **AN05**: CLI + cron GHA (Fase 5) — `scripts/analytics/` (setup, fetch,
      dashboard, README) + `.github/workflows/refresh-analytics.yml`.
- [x] **AN06**: Suite tests/analytics/ + runner (Fase 6) — 27 tests verdes,
      `run_analytics.ps1` exit 0.
- [~] **AN07**: Coordinar con Signals Agent el enum `domain += 'internal'` —
      sub-tarea documentada (SIG-INT-1..4); pendiente de su PR.

Leyenda: `[x]` hecho · `[~]` código listo, bloqueado por infra/owner u otro agente.

### Estado de las fases (Setup en 6 pasos)

- Fase 1 — [~] código listo, infra pendiente del owner (`infra/plausible/README.md`)
- Fase 2 — [x] hecho (verificación manual de panel pendiente de AN01)
- Fase 3 — [x] hecho (`plausible_client.py`, cov 88.6%)
- Fase 4 — [x] hecho (schema + `internal_signals.py`)
- Fase 5 — [x] hecho (CLI + GHA)
- Fase 6 — [x] hecho (`tests/analytics/`, runner exit 0)

---

*Owner: este agente. Última actualización: 2026-06-02.*
