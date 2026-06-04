# scripts/signals · Capa de ingesta y briefs

> **Owner**: [SIGNALS_AGENT](../../docs/agents/SIGNALS_AGENT.md)

## Archivos

| Script | Propósito |
|---|---|
| `refresh_market_signals.py` | CLI: ingesta de fuentes → prune → distill → briefs |
| `briefs_dashboard.py` | Inspector CLI con 4 paneles (scraper health, briefs, unresolved, validation) |
| `verify_signals_flow.py` | Smoke E2E sobre DB real con namespace `verify_` |

## Comandos

```powershell
# Ingesta completa cada 4h (default sin LLM)
python scripts/signals/refresh_market_signals.py

# Solo gaming, sin LLM
python scripts/signals/refresh_market_signals.py --domains gaming --no-llm

# Inspector
python scripts/signals/briefs_dashboard.py --validate --resolve-preview

# Smoke E2E (insert verify_ ns + 6 etapas + cleanup)
python scripts/signals/verify_signals_flow.py --cleanup

# Solo report sin tocar nada
python scripts/signals/refresh_market_signals.py --report-only
```

## Verificación del dominio

```powershell
.\scripts\testing\run_signals.ps1
```

## Anti-patrones

- ❌ Modificar `consumed_at` de briefs desde acá (eso es del rotator)
- ❌ Llamar HTTP fuera del registry `SOURCES` de `market_signals.py`
- ❌ Hardcodear thresholds (usar env vars de `signals_validation.THRESHOLDS`)
