# scripts/analytics — Plausible CLI

> Owner: [docs/agents/ANALYTICS_AGENT.md](../../docs/agents/ANALYTICS_AGENT.md)
> Infra (Docker + Tunnel): [infra/plausible/README.md](../../infra/plausible/README.md)

CLI del dominio analytics. Lee la Stats API de Plausible self-hosted y la
puentea a las tablas `plausible_*` (y, gateado, a `market_signals`).

## Env

```
PLAUSIBLE_BASE_URL=https://analytics.vara-alta.lat
PLAUSIBLE_API_KEY=<panel: Site Settings → API Keys>
PLAUSIBLE_SITE_ID=youlikeit.vara-alta.lat
```

## Comandos típicos

```powershell
# 0. ¿Está todo listo para levantar el stack?
python scripts/analytics/setup_plausible.py --health

# 1. Leer métricas de los últimos 7 días (no toca DB)
python scripts/analytics/fetch_plausible_stats.py --period 7d

# 2. Leer + persistir a plausible_pageviews / plausible_events
python scripts/analytics/fetch_plausible_stats.py --period 7d --persist

# 3. Salida JSON para CI / dashboards
python scripts/analytics/fetch_plausible_stats.py --period 30d --json

# 4. Solo resumen de lo que ya hay en la DB local (sin API)
python scripts/analytics/fetch_plausible_stats.py --report-only

# 5. Dashboard CLI Plausible (4 paneles)
python scripts/analytics/analytics_dashboard.py
python scripts/analytics/analytics_dashboard.py --live --period 30d

# 6. Vista CONJUNTA (nuestra analítica + Plausible) — embudo completo
python scripts/analytics/unified_dashboard.py                 # las 4 capas + rollup persona
python scripts/analytics/unified_dashboard.py --source plausible  # solo embudo web
python scripts/analytics/unified_dashboard.py --demo          # datos sintéticos (no toca data/)
python scripts/analytics/unified_dashboard.py --json
```

## Vista conjunta vs solo-Plausible

`analytics_dashboard.py` muestra **solo** el tráfico de Plausible.
`unified_dashboard.py` une las **4 capas del embudo** (demanda externa →
demanda web 1ª parte → calidad de hook → distribución YT/TT) con un rollup por
persona. La agregación vive en `src/apps/analytics/unified_analytics.py` (solo lectura).
Ver [docs/architecture/ANALYTICS_COVERAGE.md](../../docs/architecture/ANALYTICS_COVERAGE.md)
para el modelo completo de qué teníamos, qué faltaba y qué suple Plausible.

## Flags de `fetch_plausible_stats.py`

| Flag | Efecto |
|---|---|
| `--period` | day \| 7d \| 30d \| month \| 6mo \| 12mo (default 7d) |
| `--metrics` | métricas para aggregate (default visitors pageviews bounce_rate visit_duration) |
| `--persist` | escribe pageviews + events a las tablas `plausible_*` |
| `--json` | salida JSON estructurada |
| `--report-only` | no llama a la API; resume la DB local |
| `--no-cache` | ignora la cache de 1h |

## Cron

`.github/workflows/refresh-analytics.yml` corre cada 4h (`--persist`) +
agregación nocturna. Secrets de GHA: `PLAUSIBLE_API_KEY`, `PLAUSIBLE_SITE_ID`,
`PLAUSIBLE_BASE_URL`.

## Bridge a signals

`src/apps/analytics/internal_signals.py` convierte tráfico propio en
`Signal(domain='internal')`. Persistir a `market_signals` está **gateado** a
una sub-tarea de Signals Agent (ver SIGNALS_AGENT.md § "domain += internal").
