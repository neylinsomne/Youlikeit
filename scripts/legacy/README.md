# scripts/legacy · Scripts deprecados

> **No usar.** Estos scripts predataron la introducción de pytest y
> el harness MLOps actual. Quedan para referencia histórica.

## Archivos

| Script | Reemplazado por |
|---|---|
| `check_berserk_eclipse_en.py` | tests/signals/ + DB queries |
| `check_manga_en.py` | tests + briefs_dashboard |
| `test_culture_feed.py` | tests/signals/test_market_signals.py |
| `test_director_v2.py` | tests/production/ |
| `test_director_v3.py` | tests/production/ |
| `full_pipeline_test.py` | tests/integration/test_integration_e2e.py |
| `test_content_cycle.py` | tests/integration/ |
| `test_content_cycle_v2.py` | tests/integration/ |
| `test_hook_render.py` | tests/scoring/test_hook_scorer.py |
| `test_pipeline_no_llm.py` | verify_signals_flow.py + tests |
| `verify_all_sources.py` | scripts/signals/briefs_dashboard.py + signals_validation |

## Política

- Borrar **gradualmente** según se valide que los reemplazos cubren lo mismo
- Antes de borrar: confirmar con QA Agent que no se referencia desde nada vivo
- Si necesitas restaurar lógica de alguno → portarla al test correspondiente, no usar el script directamente
