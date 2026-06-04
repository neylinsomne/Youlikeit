# YouLikeIt

Sistema de **producción algorítmica de contenido analítico** para YouTube Shorts
/ TikTok. Tres personas (Deep Mind, Pop Oracle, Voz Latina) generan shorts cada
3 días a partir del **consumo cultural real** (qué está viendo / jugando / leyendo
el mundo), con A/B testing continuo sobre retención.

Es algorítmico por diseño (no LLM en el camino crítico): reproducible, costo
cercano a cero, y con tests A/B limpios donde la variable es el tono, no la
lotería del modelo.

## Por dónde empezar

| Si vas a... | Lee |
|---|---|
| Entender el sistema completo | [docs/architecture/MLOPS_FLOW.md](docs/architecture/MLOPS_FLOW.md) |
| Ver el índice de toda la documentación | [docs/README.md](docs/README.md) |
| Delegar/recoger una tarea | [docs/agents/AGENT_TASKS.md](docs/agents/AGENT_TASKS.md) |
| Verificar que todo funciona | [docs/testing/INTEGRATION_CHECKLIST.md](docs/testing/INTEGRATION_CHECKLIST.md) |
| Conocer la misión y la voz del canal | [MANIFIESTO.md](MANIFIESTO.md) |
| Ver el roadmap | [ROADMAP.md](ROADMAP.md) |
| Configurar cuentas y API keys | [SETUP_CUENTAS.md](SETUP_CUENTAS.md) |

## El flujo, en una línea

```
señales de mercado → distill (clusters + scoring por persona) → briefs
→ resolver (texto→slug) → rotator → script algorítmico → render (FFmpeg NVENC)
→ hook quality gate → upload (en pausa)
```

Detalle completo con el mapa Sculley en
[docs/architecture/MLOPS_FLOW.md](docs/architecture/MLOPS_FLOW.md).

## Estructura del repo

```
src/
├── core/          config + db (infra central)
├── utils/         logger, http_client, websocket_hub (transversal)
├── apps/          dominios: signals, production, scoring, analytics, content
└── integrations/  clientes de fuentes externas (tmdb, mangadex, llm, …)
scripts/<dominio>/ runners por dominio (signals, scoring, production, testing, uploads, setup)
scripts/legacy/    exercises ex00–ex40 + main.py (launcher legacy)
tests/<dominio>/   pytest por dominio (unit / integration / e2e)
docs/              documentación (entrar por docs/README.md)
.github/workflows/ crons (refresh-signals, content-rotation, pipeline)
```

## Setup rápido

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt   # pytest + dev tooling
.\scripts\testing\run_tests.ps1 -Mode quick      # sanity check (< 20s)
```

## Notas

- Uso educativo. Métricas solo del canal propio (Analytics API).
- La publicación YT/TT está **deshabilitada** hasta que la calidad de contenido
  esté validada — ver [docs/operations/UPLOADS.md](docs/operations/UPLOADS.md).
