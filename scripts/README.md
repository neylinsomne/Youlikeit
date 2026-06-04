# Scripts · Índice por dominio

> Scripts organizados por dominio. Cada subcarpeta tiene un README con su
> propósito. Para correr verificaciones, ver `testing/`.

```
scripts/
├── README.md          ← estás aquí
├── signals/           Ingesta + distill + verify (dominio Signals)
├── production/        Rotator + render + batch orchestrator
├── scoring/           Hook scorer + A/B setup
├── analytics/         Plausible: setup + fetch stats + dashboard (dominio Analytics)
├── testing/           Runners pytest por dominio + audit completo
├── setup/             Voces, OAuth, descargas iniciales
├── uploads/           Subida a YouTube / TikTok
└── legacy/            Scripts pre-pytest — no usar, referencia histórica
```

## Comandos esenciales

```powershell
# Verificación rápida (< 20s)
.\scripts\testing\run_tests.ps1 -Mode quick

# Audit completo por dominios
.\scripts\testing\run_all.ps1 -WithCoverage

# Solo un dominio
.\scripts\testing\run_signals.ps1
.\scripts\testing\run_production.ps1
.\scripts\testing\run_scoring.ps1

# Operación día a día
python scripts/signals/refresh_market_signals.py
python scripts/signals/briefs_dashboard.py --validate
python scripts/signals/verify_signals_flow.py --cleanup
```

## Mapping con dominios y agentes

| Carpeta | Handbook del owner |
|---|---|
| `signals/` | [docs/agents/SIGNALS_AGENT.md](../docs/agents/SIGNALS_AGENT.md) |
| `production/` | [docs/agents/PRODUCTION_AGENT.md](../docs/agents/PRODUCTION_AGENT.md) |
| `scoring/` | [docs/agents/SCORING_AGENT.md](../docs/agents/SCORING_AGENT.md) |
| `analytics/` | [docs/agents/ANALYTICS_AGENT.md](../docs/agents/ANALYTICS_AGENT.md) |
| `testing/` | [docs/agents/QA_AGENT.md](../docs/agents/QA_AGENT.md) |
| `setup/` | _(pendiente)_ |
| `uploads/` | _(pendiente — diferido hasta TikTok review)_ |
| `legacy/` | nadie. Solo lectura. |

---

*Última actualización: 2026-06-02.*
