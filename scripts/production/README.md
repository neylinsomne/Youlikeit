# scripts/production · Producción de videos

> **Owner**: [PRODUCTION_AGENT](../../docs/agents/PRODUCTION_AGENT.md)

## Estado

Los scripts core (`produce_for_series.py`, `run_rotation_batch.py`,
`clean_and_produce.py`) **siguen en `scripts/` plano** por motivos de
subprocess calls. Mover acá está en backlog (Tier 3 · T42).

Esta carpeta queda como **placeholder + handbook** hasta esa migración.

## Comandos actuales

```powershell
# Producción 1 serie 1 vtype
python scripts/produce_for_series.py --series "Berserk" --persona deep_mind

# Dry-run (solo scripts, sin render)
python scripts/produce_for_series.py --series "Berserk" --persona deep_mind --dry-run

# Batch orchestrator (3 personas × 3 vtypes)
python scripts/run_rotation_batch.py --personas deep_mind pop_oracle latam
```

## Verificación del dominio

```powershell
.\scripts\testing\run_production.ps1
```
