# scripts/production · Producción de videos

> **Owner**: [PRODUCTION_AGENT](../../docs/agents/PRODUCTION_AGENT.md)

## Runners

| Script | Qué hace |
|---|---|
| `produce_for_series.py` | Produce 1 serie × 1 vtype (render completo) |
| `run_rotation_batch.py` | Orquestador batch (3 personas × 3 vtypes); invoca `produce_for_series.py` por subprocess |
| `clean_and_produce.py` | Reset + produce |

## Comandos

```powershell
# Dentro de Docker (recomendado — ver regla en scripts/README.md):
docker compose run --rm ytlab python scripts/production/produce_for_series.py --series "Berserk" --persona deep_mind
docker compose run --rm ytlab python scripts/production/run_rotation_batch.py --personas deep_mind pop_oracle latam

# Dry-run (solo scripts, sin render):
docker compose run --rm ytlab python scripts/production/produce_for_series.py --series "Berserk" --persona deep_mind --dry-run
```

> `run_rotation_batch.py` hace `os.chdir(repo_root)` y llama a
> `scripts/production/produce_for_series.py` por subprocess (path relativo al root).

## Verificación del dominio

```powershell
.\scripts\testing\run_production.ps1
```
