# Docs · Índice

> Documentación organizada por **propósito**, no por cronología.
> Cada agente debe entrar por su handbook en `agents/`.

```
docs/
├── README.md                    ← estás aquí
├── CHANGELOG.md                 historial de cambios (keep-a-changelog)
├── architecture/                ← cómo está diseñado el sistema
│   ├── MLOPS_FLOW.md            mapa Sculley + diagrama end-to-end
│   ├── ESTRATEGIA_CPS_HOOKS.md  spec de la estrategia de hooks
│   ├── PERSONAS.md              diseño multi-persona + knowledge graph
│   ├── DATA_MODEL.md            schema canónico SQLite (ER + invariantes)
│   └── DECISIONS/               ADRs (formato MADR)
├── testing/                     ← cómo verificar que funciona
│   ├── INTEGRATION_CHECKLIST.md checklist marcable de integraciones
│   └── PENDING_TESTS.md         items diferidos con DoD individual
├── operations/                  ← cómo operarlo en producción
│   ├── RUNBOOK.md               top incidents: síntoma → diagnóstico → fix → rollback
│   ├── SECURITY.md              secrets + threat model
│   └── UPLOADS.md               APIs YT/TT (dominio uploads, en pausa)
├── _internal/                   ← scratchpads del owner (no documentan el producto)
├── _archive/                    ← docs legacy conservados por historia
└── agents/                      ← cómo delegar tareas a agentes
    ├── AGENT_TASKS.md           catálogo central de delegación
    ├── SIGNALS_AGENT.md         handbook dominio signals
    ├── PRODUCTION_AGENT.md      handbook dominio production
    ├── SCORING_AGENT.md         handbook dominio scoring
    ├── QA_AGENT.md              handbook dominio QA / testing
    ├── DOCS_AGENT.md            handbook dominio docs (owner de docs/)
    ├── ANALYTICS_AGENT.md       handbook dominio analytics (Plausible + bridge)
    └── prompts/                 prompts paste-ready para sesiones de agente
        ├── DOCS_AUDIT_PROMPT.md
        └── PLAUSIBLE_INTEGRATION_PROMPT.md
```

## Cuándo leer qué

| Si vas a... | Lee primero |
|---|---|
| Entender el sistema completo | [architecture/MLOPS_FLOW.md](architecture/MLOPS_FLOW.md) |
| Entender el diseño multi-persona | [architecture/PERSONAS.md](architecture/PERSONAS.md) |
| Conocer el schema de la DB | [architecture/DATA_MODEL.md](architecture/DATA_MODEL.md) |
| Saber por qué se tomó una decisión | [architecture/DECISIONS/](architecture/DECISIONS/) |
| Operar / resolver un incidente | [operations/RUNBOOK.md](operations/RUNBOOK.md) |
| Manejar secrets / threat model | [operations/SECURITY.md](operations/SECURITY.md) |
| Reactivar uploads YT/TT | [operations/UPLOADS.md](operations/UPLOADS.md) |
| Ver qué cambió y cuándo | [CHANGELOG.md](CHANGELOG.md) |
| Verificar que todo funciona | [testing/INTEGRATION_CHECKLIST.md](testing/INTEGRATION_CHECKLIST.md) |
| Asignar una tarea a un agente | [agents/AGENT_TASKS.md](agents/AGENT_TASKS.md) |
| Modificar la capa de ingesta | [agents/SIGNALS_AGENT.md](agents/SIGNALS_AGENT.md) |
| Modificar render / rotator | [agents/PRODUCTION_AGENT.md](agents/PRODUCTION_AGENT.md) |
| Modificar hook scorer / A/B | [agents/SCORING_AGENT.md](agents/SCORING_AGENT.md) |
| Tocar tests / coverage / CI | [agents/QA_AGENT.md](agents/QA_AGENT.md) |
| Auditar/limpiar docs | [agents/DOCS_AGENT.md](agents/DOCS_AGENT.md) + [prompts/DOCS_AUDIT_PROMPT.md](agents/prompts/DOCS_AUDIT_PROMPT.md) |
| Integrar Plausible Analytics | [agents/ANALYTICS_AGENT.md](agents/ANALYTICS_AGENT.md) + [prompts/PLAUSIBLE_INTEGRATION_PROMPT.md](agents/prompts/PLAUSIBLE_INTEGRATION_PROMPT.md) |
| Ver qué está pendiente | [testing/PENDING_TESTS.md](testing/PENDING_TESTS.md) |

## Reglas de oro

1. **Un cambio → un dominio**. Si toca 2+, abrir sub-tarea por dominio.
2. **Definition-of-Done explícita** en cada tarea. Sin DoD no se mergea.
3. **Comando de verificación obligatorio**: cada dominio tiene su runner en `scripts/testing/run_<domain>.ps1`.
4. **Cambios estructurales** (Tier 3 en AGENT_TASKS.md) requieren coordinación QA.

---

*Última actualización: 2026-06-02.*
