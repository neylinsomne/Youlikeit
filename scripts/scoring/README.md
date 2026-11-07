# scripts/scoring · Hook scoring + A/B

> **Owner**: [SCORING_AGENT](../../docs/agents/SCORING_AGENT.md)

## Archivos

| Script | Propósito |
|---|---|
| `score_hooks.py` | Batch CLI sobre `outputs/produce/` con cache + CSV/JSON export |
| `setup_hook_ab_tests.py` | Bootstrap idempotente de A/B tests de hooks |

## Comandos

```powershell
# Scorear todos los videos producidos
python scripts/scoring/score_hooks.py

# Con LLM scoring opcional
python scripts/scoring/score_hooks.py --use-llm

# Export CSV para Sheets / pandas
python scripts/scoring/score_hooks.py --csv out/hook_scores.csv

# Setup A/B tests del hook engine
python scripts/scoring/setup_hook_ab_tests.py
```

## Verificación del dominio

```powershell
.\scripts\testing\run_scoring.ps1
```

## Anti-patrones

- ❌ Modificar pesos sin documentar la hipótesis
- ❌ Activar `block_on_fail=True` antes de calibrar contra retention real
