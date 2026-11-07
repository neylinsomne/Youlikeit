# Docs · Índice

> Documentación organizada por **propósito**, no por cronología.
> Cada agente debe entrar por su handbook en `agents/`.
> El producto actual es **"aprender empatía con el cine"**: ETL media → moments → supercut → publish,
> estudio local y sitio público `web/`. Los docs del producto anterior (personas, hooks, Plausible)
> siguen aquí marcados como legacy.

```
docs/
├── README.md                    ← estás aquí
├── CHANGELOG.md                 historial de cambios (keep-a-changelog)
├── architecture/                ← cómo está diseñado el sistema
│   ├── SUPERCUT_ETL.md          ETL de lecciones: media → moments → supercut → publish
│   ├── STUDIO_API.md            contrato de la API del estudio local + puente de web/
│   ├── DATA_MODEL.md            schema SQLite (shorts_pipeline.db + web.db)
│   ├── MLOPS_FLOW.md            mapa Sculley + flujo end-to-end
│   ├── DECISIONS/               ADRs (formato MADR)
│   ├── PERSONAS.md              diseño multi-persona (legacy)
│   ├── ESTRATEGIA_CPS_HOOKS.md  spec de hooks (producto anterior)
│   └── ANALYTICS_COVERAGE.md    cobertura analítica con Plausible (legacy)
├── operations/                  ← cómo operarlo
│   ├── INDEX_A_FILM.md          runbook: de una película a una lección publicada
│   ├── UPLOADS.md               publicar en TikTok (borrador) y YouTube
│   ├── TIKTOK_APP_REVIEW.md     configuración del portal y revisión de la app de TikTok
│   ├── TIKTOK_DEMO_VIDEO.md     guion de los videos demo para la revisión
│   ├── RUNBOOK.md               incidentes: síntoma → diagnóstico → fix → rollback
│   └── SECURITY.md              secrets + modelo de amenazas
├── testing/                     ← cómo verificar que funciona
│   ├── INTEGRATION_CHECKLIST.md checklist marcable de integraciones (producto anterior)
│   └── PENDING_TESTS.md         items diferidos con DoD individual
├── _internal/                   ← scratchpads del owner (no documentan el producto)
├── _archive/                    ← docs legacy conservados por historia
├── _audit_report.md             audit de docs del 2026-06-02 (histórico; pendiente moverlo a _archive/)
└── agents/                      ← cómo delegar tareas a agentes
    ├── AGENT_TASKS.md           catálogo central de delegación
    ├── MEDIA_AGENT.md           dominio media (Extract)
    ├── MOMENTS_AGENT.md         dominio moments (Transform)
    ├── SIGNALS_AGENT.md         dominio signals (legacy)
    ├── PRODUCTION_AGENT.md      dominio production (legacy)
    ├── SCORING_AGENT.md         dominio scoring (legacy)
    ├── ANALYTICS_AGENT.md       dominio analytics (Plausible, legacy)
    ├── QA_AGENT.md              dominio QA / testing
    ├── DOCS_AGENT.md            dominio docs (owner de docs/)
    └── prompts/                 prompts paste-ready para sesiones de agente
        ├── DOCS_AUDIT_PROMPT.md
        └── PLAUSIBLE_INTEGRATION_PROMPT.md
```

Fuera de `docs/`: [README.md](../README.md), [ROADMAP.md](../ROADMAP.md),
[SETUP_CUENTAS.md](../SETUP_CUENTAS.md), [web/README.md](../web/README.md),
[frontend-react/README.md](../frontend-react/README.md), [tests/README.md](../tests/README.md),
[scripts/README.md](../scripts/README.md) y [MANIFIESTO.md](../MANIFIESTO.md) (del dueño).

## Cuándo leer qué

| Si vas a... | Lee primero |
|---|---|
| Entender el ETL de lecciones | [architecture/SUPERCUT_ETL.md](architecture/SUPERCUT_ETL.md) |
| Tocar la API del estudio o el front | [architecture/STUDIO_API.md](architecture/STUDIO_API.md) |
| Tocar el sitio público | [../web/README.md](../web/README.md) |
| Indexar una película y armar una lección | [operations/INDEX_A_FILM.md](operations/INDEX_A_FILM.md) |
| Publicar en TikTok o YouTube | [operations/UPLOADS.md](operations/UPLOADS.md) |
| Pasar la revisión de TikTok | [operations/TIKTOK_APP_REVIEW.md](operations/TIKTOK_APP_REVIEW.md) |
| Conocer el schema de la DB | [architecture/DATA_MODEL.md](architecture/DATA_MODEL.md) |
| Saber por qué se tomó una decisión | [architecture/DECISIONS/](architecture/DECISIONS/README.md) |
| Operar / resolver un incidente | [operations/RUNBOOK.md](operations/RUNBOOK.md) |
| Manejar secrets / threat model | [operations/SECURITY.md](operations/SECURITY.md) |
| Ver qué cambió y cuándo | [CHANGELOG.md](CHANGELOG.md) |
| Modificar fuentes, extracción o ASR | [agents/MEDIA_AGENT.md](agents/MEDIA_AGENT.md) |
| Modificar momentos, vocabulario o búsqueda | [agents/MOMENTS_AGENT.md](agents/MOMENTS_AGENT.md) |
| Asignar una tarea a un agente | [agents/AGENT_TASKS.md](agents/AGENT_TASKS.md) |
| Tocar tests / coverage / CI | [agents/QA_AGENT.md](agents/QA_AGENT.md) + [../tests/README.md](../tests/README.md) |
| Auditar/limpiar docs | [agents/DOCS_AGENT.md](agents/DOCS_AGENT.md) + [prompts/DOCS_AUDIT_PROMPT.md](agents/prompts/DOCS_AUDIT_PROMPT.md) |
| Producto anterior: señales, render de personas, hooks | [architecture/MLOPS_FLOW.md](architecture/MLOPS_FLOW.md), [agents/SIGNALS_AGENT.md](agents/SIGNALS_AGENT.md), [agents/PRODUCTION_AGENT.md](agents/PRODUCTION_AGENT.md), [agents/SCORING_AGENT.md](agents/SCORING_AGENT.md) |
| Ver qué está pendiente de tests | [testing/PENDING_TESTS.md](testing/PENDING_TESTS.md) |

## Reglas de oro

1. **Un cambio → un dominio**. Si toca 2+, abrir sub-tarea por dominio.
2. **Definition-of-Done explícita** en cada tarea. Sin DoD no se mergea.
3. **Comando de verificación obligatorio**: `python -m pytest tests/<dominio>` (y `web/` con su propio pytest).
4. **Contratos primero**: un cambio en la API del estudio se escribe antes en `STUDIO_API.md`.
5. **Cambios estructurales** (Tier 3 en AGENT_TASKS.md) requieren coordinación QA.

---

*Última actualización: 2026-11-04.*
