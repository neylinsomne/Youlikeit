# Integration Checklist · YouLikeIt MLOps

> Checklist marcable para verificar **todas las integraciones** del flujo
> de información. Cada item tiene comando exacto, expected output, y qué
> mirar si falla. Estilo "state-of-the-art": pytest + responses + freezegun
> + coverage + smoke E2E + invariantes runtime.
>
> Ordenado de **rápido a lento**. En CI corre todo; localmente usa solo lo
> que necesites.

---

## 0. Setup (una sola vez)

```powershell
# Desde la raíz del repo
python -m pip install -r requirements.txt        # runtime
python -m pip install -r requirements-dev.txt    # pytest + responses + freezegun + coverage
```

- [ ] `pytest --version` ≥ 8.0
- [ ] `python -c "import responses, freezegun, rapidfuzz"` no crashea
- [ ] Docker activo (`docker ps` lista servicios) — necesario solo para video, **no** para flujo de información

---

## 1. Smoke estático — el ALIAS_MAP no tiene huérfanos

**Por qué primero**: si un alias apunta a un slug que no existe, la pipeline
silenciosamente nunca matchearía esos briefs. Es el test más barato y el más
importante de toda la arquitectura.

```powershell
python -m pytest tests/signals/test_brief_resolver.py::TestAliasMapIntegrity -v
```

**Expected:** 3 tests pasan en < 200ms.

- [ ] `test_no_orphans_in_real_alias_map` ✓
- [ ] `test_catalog_coverage_threshold` ✓ (≥80% de slugs con ≥1 alias)
- [ ] `test_validate_detects_orphan` ✓

**Si falla:** mirar el output — dice exactamente qué alias apunta fuera del
CATALOG. Editar `src/apps/signals/brief_resolver.py` ALIAS_MAP o
`src/apps/production/content_rotator.py` CATALOG.

---

## 2. Unit tests — lógica pura sin I/O

Cubre normalización, scoring, weighting, dataclasses.

```powershell
python -m pytest -m unit -v
```

**Expected:** ~30 tests, < 5 segundos total, todos verdes.

- [ ] `TestNormalize` (5 tests) — `_norm()` idempotente
- [ ] `TestNormalizeTitle` (7 tests) — `normalize_title()` con parametrize
- [ ] `TestSignalDataclass` (2 tests) — default factories
- [ ] `TestAliasMapIntegrity` (3 tests)
- [ ] `TestResolveBriefLayers` (12 tests con parametrize)
- [ ] `TestScoreCluster` (4 tests) — determinismo + decay
- [ ] `TestValidationReport` (3 tests)
- [ ] `TestHookScoreWeighting` (2 tests)
- [ ] `TestCatalog` (2 tests) — sanidad estructural
- [ ] `TestFuzzyMerge` (1 test) — fail-soft sin rapidfuzz

---

## 3. Integration tests — DB SQLite temp + HTTP mock

Cubre persistencia, parsers RSS/JSON, distillation end-to-end.

```powershell
python -m pytest -m integration -v
```

**Expected:** ~25 tests, < 15 segundos.

- [ ] `TestPersistence` — UNIQUE constraint, idempotencia
- [ ] `TestRSSParser` — XML válido / 500 / malformado
- [ ] `TestRedditFetcher` — skip stickied, empty response
- [ ] `TestOrchestration` — refresh_source/all, prune
- [ ] `TestBuildClusters` — agrupación capa 1
- [ ] `TestDistillE2E` — distill produce briefs ordenados
- [ ] `TestSignalsVolume` — invariante hard con override env
- [ ] `TestRequiredFields` / `TestDomainEnum` — invariantes hard
- [ ] `TestBriefsPerPersona` — cada persona ≥1
- [ ] `TestRunAll` — `ValidationReport.to_dict()` JSON-serializable
- [ ] `TestScoreCandidate` — cooldown, brief_boost
- [ ] `TestPickNext` — consume_briefs marca consumed_at
- [ ] `TestBoostIntegration` — boost ∈ [0, 1]
- [ ] `TestUnresolvedQueue` — encolar idempotente + decisión humana
- [ ] `TestHookScorePersistence` — schema idempotente
- [ ] `TestScoreHookRobustness` — video missing → score 0

**Si falla:** `pytest --tb=long --showlocals` para ver state local.

---

## 4. End-to-End — pipeline completo sin red

Smoke del flujo: ingesta sintética → distill → resolver → rotator → validación.

```powershell
python -m pytest -m e2e -v
```

**Expected:** 2 tests, < 5 segundos.

- [ ] `TestFullInfoFlow::test_full_pipeline_synthetic` ✓
- [ ] `TestRotatorBriefAwareness::test_rotator_prefers_slug_with_brief` ✓

**Si falla:** el test muestra exactamente qué FASE (1–5) se rompió.

---

## 5. Coverage — cuánto del flujo estamos probando

```powershell
python -m pytest --cov --cov-report=term-missing --cov-report=html
```

**Expected:**
- Coverage total ≥ **75%** sobre `src/{core,utils,apps,integrations}/`
- Por módulo:

| Módulo | Target |
|---|---|
| `brief_resolver.py` | ≥ 85% |
| `market_signals.py` | ≥ 70% (HTTP fetchers solo parcialmente cubiertos) |
| `signals_distiller.py` | ≥ 80% |
| `signals_validation.py` | ≥ 90% |
| `hook_scorer.py` | ≥ 60% (ffmpeg path no se ejecuta en CI) |
| `content_rotator.py` | ≥ 70% |

- [ ] `htmlcov/index.html` abre con tabla coloreada
- [ ] Sin módulos en rojo (<50%) que sean del flujo de información

---

## 6. Smoke E2E contra DB real

Inserta señales con prefijo `verify_` (no toca el corpus de prod) y verifica
que las 6 etapas funcionan extremo a extremo. **Esto es lo que corres cuando
quieres ver "que funciona AHORA"**.

```powershell
python scripts/signals/verify_signals_flow.py
# o con limpieza automática:
python scripts/signals/verify_signals_flow.py --cleanup
```

**Expected output (todas con ✓):**

```
========================================================================
  VERIFY SIGNALS FLOW · checklist E2E sobre DB real
========================================================================
  [✓] Inserción de señales sintéticas (namespace verify_)        insertadas=10
  [✓] Distill produce briefs por persona                          insertados=N · live por persona={...}
  [✓] Resolver mapea briefs a CATALOG (alias / fuzzy)             resolved=X · unresolved=Y
  [✓] Sweep encola briefs sin match                                queue size=N · dandadan_in_queue=True
  [✓] Rotator hace pick aprovechando briefs vivos                  picks_ok=3/3 · slugs_distintos≥2
  [✓] Invariantes de Data Verification                             hard_fails=0 · soft_fails=N
  Resultado: 6/6 stages OK   (✓ FLOW VERDE)
========================================================================
```

- [ ] Las 6 etapas en ✓
- [ ] `--cleanup` borra todo el namespace `verify_` sin tocar producción

**Si falla una etapa:** el output dice qué etapa y qué error. Re-correr con
flags de debug.

---

## 7. Dashboard CLI — vista humana del estado

```powershell
python scripts/signals/briefs_dashboard.py --validate --resolve-preview
```

**Expected:** 4 paneles renderizados (scraper health, briefs por persona,
unresolved queue, resolve preview) + reporte de validación al final.

- [ ] Panel "SCRAPER HEALTH" muestra rows o "(sin datos)"
- [ ] Panel "BRIEFS POR PERSONA" lista briefs vivos por las 3 personas
- [ ] Panel "UNRESOLVED" muestra el queue (o vacío)
- [ ] Panel "RESOLVE PREVIEW" indica qué slug elegiría el resolver
- [ ] Panel "VALIDATION REPORT" muestra HARD: PASS/FAIL

---

## 8. CLI refresh contra red real (opcional)

⚠️ Hace llamadas HTTP reales. Usa `--no-llm` para no gastar cuota.

```powershell
python scripts/signals/refresh_market_signals.py --no-llm --domains gaming --sources steam_charts
```

**Expected:** señales nuevas insertadas; reporte impreso al final.

- [ ] `total_new` > 0 si steam_charts respondió
- [ ] DB tiene rows con `source = 'steam_charts'`

```powershell
# Verificar contenido:
python -c "import sqlite3; c=sqlite3.connect('data/shorts_pipeline.db'); print(list(c.execute('SELECT COUNT(*), source FROM market_signals WHERE source = ''steam_charts'' GROUP BY source')))"
```

**Si falla con HTTP error:** steamcharts.com puede haber cambiado su HTML —
revisar `fetch_steam_charts` regex.

---

## 9. Hook scorer sobre videos ya producidos (si los hay)

```powershell
python scripts/scoring/score_hooks.py --csv out/hook_scores.csv
```

**Expected:** tabla con scores por video + CSV escrito.

- [ ] Cada video tiene un overall_score
- [ ] Modo `--rescore` regenera sin tirar de cache

Si no hay videos en `outputs/produce/`, este paso muestra "Encontrados 0 videos"
— normal cuando el render no se ha corrido aún.

---

## 10. GHA workflow validation (sin pushear)

```powershell
# Si tienes gh CLI:
gh workflow view refresh-signals.yml
```

- [ ] YAML válido (no errores de sintaxis)
- [ ] 2 cron schedules + 1 workflow_dispatch
- [ ] `permissions:` no expuesto donde no debería

---

## 11. Coverage thresholds bloqueantes (cuando ya tengas confianza)

Edita `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 75
```

Esto hace que `pytest --cov` falle si coverage baja del 75%. Activar
después de que la suite esté estable.

- [ ] Threshold activado
- [ ] CI lo respeta

---

## 12. Analytics — Plausible + bridge

Dominio del **Analytics Agent**. Verifica la integración de Plausible
(self-host) y el bridge de tráfico propio a signals.

```powershell
# Suite aislada + smoke bridge (no requiere Plausible vivo)
.\scripts\testing\run_analytics.ps1

# Solo pytest del dominio
python -m pytest tests/analytics/ -q

# Coverage de los módulos nuevos (DoD ≥ 80%)
python -m pytest tests/analytics/ --cov=apps.analytics.plausible_client --cov=apps.analytics.internal_signals --cov-report=term-missing
```

Smoke contra Plausible vivo (requiere `PLAUSIBLE_API_KEY` + stack levantado):

```powershell
python scripts/analytics/setup_plausible.py --health
python scripts/analytics/fetch_plausible_stats.py --period 7d --json
python scripts/analytics/analytics_dashboard.py --live --period 30d
```

- [ ] `pytest tests/analytics/` verde (27 tests)
- [ ] Coverage `plausible_client.py` ≥ 80% · `internal_signals.py` ≥ 80%
- [ ] `run_analytics.ps1` exit 0
- [ ] (infra) `curl https://analytics.vara-alta.lat/api/health` → 200
- [ ] (infra) panel muestra visitas tras hard refresh desde 3 navegadores

> El bridge `internal_signals` produce `Signal(domain='internal')` pero NO
> persiste a `market_signals` hasta que Signals Agent extienda el enum
> (`check_domain_enum`). Ver SIGNALS_AGENT.md § "domain += internal".

---

## Resumen — runner unificado

Para correr **todo en orden** con un solo comando:

```powershell
.\scripts\testing\run_tests.ps1 -Mode all
```

Esto ejecuta:
1. pytest suite completa con coverage
2. genera `htmlcov/`
3. corre `verify_signals_flow.py --cleanup`
4. retorna exit code 0 si todo verde

**Otros modos:**

```powershell
.\scripts\testing\run_tests.ps1 -Mode quick       # unit + integration sin coverage (< 20s)
.\scripts\testing\run_tests.ps1 -Mode unit        # solo lógica pura
.\scripts\testing\run_tests.ps1 -Mode integration # solo DB + HTTP mocks
.\scripts\testing\run_tests.ps1 -Mode e2e         # solo pipeline completo
.\scripts\testing\run_tests.ps1 -Mode coverage    # con HTML report
.\scripts\testing\run_tests.ps1 -Install          # instala dev deps antes

# Por dominio (audit ágil mientras desarrollas en un solo dominio):
.\scripts\testing\run_signals.ps1       # solo Signals (pytest + smoke E2E)
.\scripts\testing\run_production.ps1    # solo Production (pytest + smoke rotator)
.\scripts\testing\run_scoring.ps1       # solo Scoring (pytest + batch score)
.\scripts\testing\run_analytics.ps1     # solo Analytics (pytest + smoke bridge)
.\scripts\testing\run_all.ps1           # audit completo por dominios
```

---

## Anti-checklist — qué NO debe pasar

- ❌ Tests que llamen a internet sin marker `@pytest.mark.network`
  → el fixture `no_real_http` los bloquea con error claro.
- ❌ Tests que dependan del orden — cada test recibe DB nueva via fixture.
- ❌ Tests que dejen archivos en disco fuera de `tmp_path`.
- ❌ Tests que tarden > 2s sin marker `@pytest.mark.slow`.
- ❌ Coverage por debajo del 75% en módulos del flujo de información.
- ❌ Cambios al ALIAS_MAP o CATALOG sin re-correr el smoke 1.

---

## Mapa rápido de archivos

| Archivo | Qué hace |
|---|---|
| [pyproject.toml](../../pyproject.toml) | Config pytest + coverage + ruff |
| [requirements-dev.txt](../../requirements-dev.txt) | pytest, responses, freezegun, coverage |
| [tests/conftest.py](../../tests/conftest.py) | Fixtures (conn, sample_signals, frozen_time, mocked_http) |
| [tests/signals/test_brief_resolver.py](../../tests/signals/test_brief_resolver.py) | 24 tests · capa puente |
| [tests/signals/test_market_signals.py](../../tests/signals/test_market_signals.py) | 19 tests · ingesta + HTTP |
| [tests/signals/test_signals_distiller.py](../../tests/signals/test_signals_distiller.py) | 14 tests · clusters + scoring |
| [tests/signals/test_signals_validation.py](../../tests/signals/test_signals_validation.py) | 11 tests · invariantes |
| [tests/production/test_content_rotator.py](../../tests/production/test_content_rotator.py) | 13 tests · score + pick |
| [tests/scoring/test_hook_scorer.py](../../tests/scoring/test_hook_scorer.py) | 5 tests · scoring + persistencia |
| [tests/integration/test_integration_e2e.py](../../tests/integration/test_integration_e2e.py) | 2 tests · pipeline completo |
| [scripts/signals/verify_signals_flow.py](../../scripts/signals/verify_signals_flow.py) | Smoke E2E contra DB real |
| [scripts/testing/run_tests.ps1](../../scripts/testing/run_tests.ps1) | Runner unificado (modos quick/all) |
| [scripts/testing/run_signals.ps1](../../scripts/testing/run_signals.ps1) | Runner solo dominio Signals |
| [scripts/testing/run_production.ps1](../../scripts/testing/run_production.ps1) | Runner solo dominio Production |
| [scripts/testing/run_scoring.ps1](../../scripts/testing/run_scoring.ps1) | Runner solo dominio Scoring |
| [scripts/testing/run_all.ps1](../../scripts/testing/run_all.ps1) | Audit por dominios secuencial |
| [scripts/signals/briefs_dashboard.py](../../scripts/signals/briefs_dashboard.py) | Inspector CLI (4 paneles) |
| [scripts/signals/refresh_market_signals.py](../../scripts/signals/refresh_market_signals.py) | CLI runner cron-friendly |
| [docs/agents/AGENT_TASKS.md](../agents/AGENT_TASKS.md) | Catálogo central de delegación |

---

*Última actualización: 2026-05-29.*
