# Signals Agent · Handbook

> **Scope**: ingesta de fuentes externas → señales crudas → briefs por persona.
> Este agente **NO** toca render, NO toca scoring de hooks, NO toca upload.

---

## Archivos bajo tu dominio

| Archivo | Rol |
|---|---|
| [src/apps/signals/market_signals.py](../../src/apps/signals/market_signals.py) | Scrapers de gaming/foros/editorial/release-tracker. Registry `SOURCES` |
| [src/apps/signals/signals_distiller.py](../../src/apps/signals/signals_distiller.py) | Dedupe (capa 1+2) + scoring por persona + LLM angle opcional |
| [src/apps/signals/signals_validation.py](../../src/apps/signals/signals_validation.py) | 8 invariantes hard/soft sobre `market_signals` y `persona_briefs` |
| [src/apps/signals/brief_resolver.py](../../src/apps/signals/brief_resolver.py) | Puente texto-libre → CATALOG slug. `ALIAS_MAP` y `validate_alias_map` |
| [src/apps/signals/topic_clusters.py](../../src/apps/signals/topic_clusters.py) | Scheduler de clusters (priority + interval) |
| [scripts/signals/refresh_market_signals.py](../../scripts/signals/refresh_market_signals.py) | CLI runner (ingest + prune + distill) |
| [scripts/signals/briefs_dashboard.py](../../scripts/signals/briefs_dashboard.py) | Inspector CLI con 4 paneles |
| [scripts/signals/verify_signals_flow.py](../../scripts/signals/verify_signals_flow.py) | Smoke E2E sobre DB real con namespace `verify_` |
| [tests/signals/](../../tests/signals/) | Suite pytest del dominio |
| [.github/workflows/refresh-signals.yml](../../.github/workflows/refresh-signals.yml) | Cron (4h sin LLM + diario con LLM) |

## Archivos que NO puedes tocar

- `src/apps/production/video_director.py`, `panel_matcher.py`, `animated_subs.py` — pertenece a **Production Agent**
- `src/apps/scoring/hook_scorer.py`, `script_generator.py` (hook rules) — pertenece a **Scoring Agent**
- `produce_for_series.py`, `run_rotation_batch.py` — pertenece a **Production Agent**

Si tu cambio los necesita → abre sub-tarea para el dominio dueño.

---

## Contratos de datos

### Tabla `market_signals` (escribe este agente)

Invariantes que SIEMPRE deben cumplirse:
- `UNIQUE(source, normalized_title)` — dedupe capa 0 a nivel DB
- `domain ∈ {gaming, anime_manga, movies_tv, music, latam}` — enum hard
- `title`, `normalized_title`, `domain` no vacíos en filas < 24h
- `fetched_at` siempre en UTC ISO format

### Tabla `persona_briefs` (escribe este agente, lee Production)

- `UNIQUE(persona, cluster_key, created_at)` — evita duplicar por corrida
- `consumed_at IS NULL` ⇔ disponible para el rotator
- Rotator marca `consumed_at` al elegir → este agente NO lo modifica

### Tabla `unresolved_briefs_queue` (escribe el sweep, lee humano)

- `UNIQUE(brief_id)` — un brief solo se encola 1 vez
- `decision ∈ {NULL, 'added_to_catalog', 'discarded'}`

---

## Definition of Done por tipo de tarea

### Añadir fuente nueva

- [ ] Función `fetch_<source>()` en `market_signals.py` con shape `() → list[Signal]`
- [ ] Entrada en `SOURCES` con `(name, domain, fetcher)`
- [ ] `SERVICE_RATE_LIMITS` actualizado en `http_client.py` si necesario
- [ ] Test integración con `responses` mock en `tests/signals/test_market_signals.py`
- [ ] `python scripts/signals/refresh_market_signals.py --sources <name>` ingiere ≥ 1 fila
- [ ] Actualizar tabla "Fuentes" en `MLOPS_FLOW.md`

### Añadir aliases al ALIAS_MAP

- [ ] Solo aliases para slugs que **YA existen** en `CATALOG`
- [ ] `validate_alias_map(CATALOG)` retorna `[]`
- [ ] `alias_map_stats.coverage_pct` ≥ 80
- [ ] Test parametrize en `test_brief_resolver.py::test_real_world_brief_resolution`

### Bumpear threshold de validación

- [ ] Default en `signals_validation.THRESHOLDS` actualizado
- [ ] Env var documentada en docstring del módulo
- [ ] Override del GHA workflow si aplica
- [ ] Entrada en `PENDING_TESTS.md` § "Calibración thresholds"

### Cambiar scoring del distiller

- [ ] Test `TestScoreCluster::test_score_deterministic` sigue pasando
- [ ] Test `TestScoreCluster::test_score_decays_with_age` sigue pasando
- [ ] Documentar el cambio en `signals_distiller.py` docstring header
- [ ] Justificación numérica del peso nuevo (no "porque sí")

---

## Comando único de verificación

```powershell
.\scripts\testing\run_signals.ps1
```

Esto corre, en orden:
1. `pytest tests/signals/ -v` (unit + integration del dominio)
2. `python scripts/signals/verify_signals_flow.py --cleanup` (smoke E2E)
3. `python scripts/signals/briefs_dashboard.py --validate` (snapshot final)

Exit 0 = todo verde. Exit ≠ 0 = revisar output, **no commitear** hasta resolver.

---

## Métricas que sigues

Reportar en cualquier PR que modifique este dominio:

| Métrica | Valor actual baseline | Cómo medir |
|---|---|---|
| Coverage `brief_resolver.py` | ≥ 85% | `pytest --cov=apps.signals.brief_resolver` |
| Coverage `market_signals.py` | ≥ 70% | idem |
| Coverage `signals_distiller.py` | ≥ 80% | idem |
| Coverage `signals_validation.py` | ≥ 90% | idem |
| Tiempo total suite signals | < 10s | `pytest tests/signals/ --durations=0` |
| Coverage ALIAS_MAP sobre CATALOG | ≥ 80% | `alias_map_stats(CATALOG)["coverage_pct"]` |

Si una métrica baja en un PR → justificar o subir.

---

## Anti-patrones específicos

- ❌ Llamar HTTP real desde un test sin marker `@pytest.mark.network`
- ❌ Añadir alias a slug que no existe en CATALOG (rompe `validate_alias_map`)
- ❌ Modificar `consumed_at` desde un fetcher (eso es rol del rotator)
- ❌ Hardcodear un threshold sin pasar por `THRESHOLDS` env-overridable
- ❌ Saltarse `normalize_title()` al persistir (rompe dedupe UNIQUE)
- ❌ Insertar señales sin pasar por `_persist_signal/_persist_many` (omite contadores de scraper_health)

---

## Pendiente: `domain += internal` (sub-tarea del Analytics Agent)

> Abierta por **Analytics Agent** (2026-06-02). Requiere TU mano: toca tu enum.

El Analytics Agent añadió un bridge `src/apps/analytics/internal_signals.py` que
convierte tráfico propio de Plausible en `Signal(domain='internal')`
(source `plausible_internal`, source_type `own_engagement`). Esas señales
**aún no se persisten** en `market_signals` porque tu invariante hard
`check_domain_enum` solo acepta `{gaming, anime_manga, movies_tv, music, latam}`
— una fila `internal` haría fallar el check.

Para activar el loop interno se necesita, en una PR tuya (coordinada con QA Agent):

- [ ] **SIG-INT-1**: añadir `'internal'` al set `valid` en
      `signals_validation.check_domain_enum`.
- [ ] **SIG-INT-2**: añadir afinidad `internal` por persona en
      `signals_distiller.PERSONA_ALIGNMENT[...]["domains"]` (sugerido 1.1–1.3,
      es demanda de primera parte) para que los briefs internos puedan ganar.
- [ ] **SIG-INT-3**: actualizar `tests/signals/test_signals_validation.py` para
      cubrir el nuevo valor del enum.
- [ ] **SIG-INT-4**: una vez verde, el Analytics Agent puede llamar
      `internal_signals.persist_signals_to_market()` desde su cron.

Contrato congelado (no cambiar sin avisar al Analytics Agent): el bridge emite
`raw_meta` con `{persona, page, bounce_rate, visit_duration, delta_pct, period_end}`
y `raw_score = visitors`. Cero PII.

---

## Tareas abiertas conocidas

Ver [docs/testing/PENDING_TESTS.md](../testing/PENDING_TESTS.md) items:
- **#1** Smoke E2E con LLM real (con `GEMINI_API_KEY`)
- **#4** Calibración thresholds en `signals_validation`
- **#5** Expansión continua ALIAS_MAP (especialmente LatAm + gaming)
- **#6** Embeddings dedupe (capa 3 + capa 4)

---

*Owner: este agente. Última actualización: 2026-06-02.*
