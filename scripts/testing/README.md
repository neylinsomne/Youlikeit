# scripts/testing · Runners pytest por dominio

> **Owner**: [QA_AGENT](../../docs/agents/QA_AGENT.md)

## Runners

| Script | Scope | Tiempo |
|---|---|---|
| `run_tests.ps1` | Suite completa con modos quick/unit/integration/e2e/coverage/all | 20s-60s |
| `run_signals.ps1` | Solo dominio Signals (pytest + smoke E2E + dashboard validate) | ~15s |
| `run_production.ps1` | Solo dominio Production (pytest + smoke rotator en seco) | ~5s |
| `run_scoring.ps1` | Solo dominio Scoring (pytest + batch score si hay videos) | ~3s |
| `run_all.ps1` | Audit por dominios secuencial + coverage opcional | < 60s |

## Comandos típicos

```powershell
# Verificación rápida (lo que más usas)
.\scripts\testing\run_tests.ps1 -Mode quick

# Antes de un PR
.\scripts\testing\run_all.ps1 -WithCoverage

# Solo el dominio que tocaste
.\scripts\testing\run_signals.ps1

# Instalar deps primero (una vez)
.\scripts\testing\run_tests.ps1 -Install -Mode quick

# Verbose para debug
.\scripts\testing\run_signals.ps1 -Verbose
```

## Convención de exit codes

- `0` → todo verde
- `≠0` → revisar output; **no commitear** hasta resolver

## Flags compartidos

- `-Verbose` → pytest con `-vv`
- `-WithCoverage` → genera `htmlcov/index.html`
- `-WithLLM` → permite tests/smoke con LLM real (solo si key configurada)

## Anti-patrones

- ❌ Saltarse `run_tests.ps1` "porque es chico"
- ❌ Marcar `xfail` sin entry en `docs/testing/PENDING_TESTS.md`
- ❌ Mergear con coverage en rojo
