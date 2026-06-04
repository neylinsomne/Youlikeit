# Scoring Agent · Handbook

> **Scope**: calidad post-render. Hook scoring, A/B testing, calibración
> contra retention.
> Este agente **NO** toca ingestión, NO toca render (solo lee output).

---

## Archivos bajo tu dominio

| Archivo | Rol |
|---|---|
| [src/apps/scoring/hook_scorer.py](../../src/apps/scoring/hook_scorer.py) | RMS + CPS + accent + LLM opcional. Tabla `hook_scores` |
| [src/apps/scoring/ab_testing.py](../../src/apps/scoring/ab_testing.py) | TESTABLE_VARIABLES, Welch's t-test, bandit |
| [scripts/scoring/score_hooks.py](../../scripts/scoring/score_hooks.py) | Batch CLI sobre videos producidos |
| [scripts/scoring/setup_hook_ab_tests.py](../../scripts/scoring/setup_hook_ab_tests.py) | Sembrado de A/B tests |
| [tests/scoring/](../../tests/scoring/) | Suite pytest del dominio |
| [docs/architecture/ESTRATEGIA_CPS_HOOKS.md](../architecture/ESTRATEGIA_CPS_HOOKS.md) | Spec de la estrategia CPS |

## Archivos que NO puedes tocar

- Pipeline de render (`video_director`, `panel_matcher`) → **Production Agent**
- `script_generator.HOOK_RULES` → coordinar con **Production Agent**
- Cualquier cosa de `signals_*` → **Signals Agent**

---

## Contratos de datos

### Tabla `hook_scores` (escribe este agente)

- 1 fila por video × persistencia (NO sobrescribe — historial)
- `overall_score` ∈ [0, 1]
- `passed = 1 ⇔ overall_score ≥ MIN_HOOK_SCORE`
- Sub-scores: `audio_energy_score`, `cps_score`, `accent_word_score`, `llm_score`
- `notes` JSON array con observaciones

### Tabla `ab_tests` (escribe + lee este agente)

- 1 fila por experimento vivo
- `metric` ∈ {retention_at_3s, retention_at_30s, engagement_rate}
- `min_samples` ≥ 3 obligatorio para evitar significancia espuria
- `p_threshold` default 0.10

---

## Definition of Done por tipo de tarea

### Cambiar `SCORE_WEIGHTS`

- [ ] Suma de weights = 1.0 (verificable en `TestHookScoreWeighting`)
- [ ] Redistribución sin LLM sigue funcionando (sin div/0)
- [ ] Test `TestHookScoreWeighting::test_overall_no_llm_redistribute_weights` pasa
- [ ] Justificación: por qué este peso vs el anterior

### Calibrar `MIN_HOOK_SCORE` con datos reales

- [ ] ≥ 30 videos por persona × vtype con score persistido
- [ ] Notebook `notebooks/calibrate_hook_score.ipynb` con regresión
- [ ] Correlación Pearson `overall_score` vs `retention_at_3s` ≥ 0.4
- [ ] `MIN_HOOK_SCORE` actualizado en `hook_scorer.py` con comentario que cite el notebook
- [ ] `block_on_fail=True` activado en `produce_for_series.py`

### Añadir nuevo sub-score

- [ ] Función `_extract_<feature>()` en `hook_scorer.py`
- [ ] Columna nueva en `hook_scores` (schema actualizado en `db.py` y módulo)
- [ ] Entrada en `SCORE_WEIGHTS` con weight justificado
- [ ] Suma de weights re-balanceada
- [ ] Test específico en `tests/scoring/test_hook_scorer.py`

### Setup A/B test nuevo

- [ ] Variable en `TESTABLE_VARIABLES`
- [ ] Bootstrap idempotente en `setup_hook_ab_tests.py`
- [ ] `min_samples` ≥ 3, `p_threshold` ≤ 0.10
- [ ] Metric clara y medible (no abstracta)

---

## Comando único de verificación

```powershell
.\scripts\testing\run_scoring.ps1
```

Esto corre:
1. `pytest tests/scoring/ -v`
2. Si hay videos en `outputs/produce/` → `python scripts/scoring/score_hooks.py --csv out/hook_scores.csv` y valida que el CSV se escribió

---

## Métricas que sigues

| Métrica | Baseline | Cómo medir |
|---|---|---|
| Coverage `hook_scorer.py` | ≥ 60% | `pytest --cov=apps.scoring.hook_scorer` (parte de ffmpeg no se ejecuta sin video) |
| Tests scoring suite | < 3s | `pytest tests/scoring/ --durations=0` |
| Correlación hook_score ↔ retention | ≥ 0.4 (objetivo) | notebook calibrate |
| Pass rate por persona | TBD | `SELECT persona, AVG(passed) FROM hook_scores GROUP BY persona` |

---

## Anti-patrones específicos

- ❌ Modificar pesos sin documentar por qué (los pesos son hipótesis falseable)
- ❌ Activar `block_on_fail=True` antes de calibrar (cortarías producción legítima)
- ❌ Persistir scores sin pasar por `persist_hook_score()` (rompe tracking)
- ❌ Hardcodear umbrales fuera de `MIN_HOOK_SCORE` (umbral única fuente de verdad)
- ❌ Llamar a LLM por cada video sin gate de presupuesto

---

## Tareas abiertas conocidas

Ver [docs/testing/PENDING_TESTS.md](../testing/PENDING_TESTS.md) items:
- **#3** Calibración `MIN_HOOK_SCORE` contra retention real
- **#10** Benchmark vs AutoClip

---

*Owner: este agente. Última actualización: 2026-06-02.*
