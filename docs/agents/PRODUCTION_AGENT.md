# Production Agent · Handbook

> **Scope**: orquestación de producción de videos. Rotator → script generator
> → audio TTS → image pool → render FFmpeg → output MP4.
> Este agente **NO** toca ingestión, NO toca scoring, NO toca subida.

---

## Archivos bajo tu dominio

| Archivo | Rol |
|---|---|
| [src/apps/production/content_rotator.py](../../src/apps/production/content_rotator.py) | CATALOG + score_candidate + pick_next (consume briefs) |
| [src/apps/production/script_generator.py](../../src/apps/production/script_generator.py) | HOOK_RULES, accent words, voice params por vtype |
| [src/apps/production/algorithmic_script_generator.py](../../src/apps/production/algorithmic_script_generator.py) | JSON templates → script determinista |
| [src/apps/production/video_director.py](../../src/apps/production/video_director.py) | EditDecision, expand_hook, pacing, Ken Burns |
| [src/apps/production/panel_matcher.py](../../src/apps/production/panel_matcher.py) | Matching segmento → imagen |
| [src/apps/production/animated_subs.py](../../src/apps/production/animated_subs.py) | ASS styles (Hook, HookKey) |
| [src/apps/production/treatment_tones.py](../../src/apps/production/treatment_tones.py) | Tonos A/B (critical/narrative/...) |
| [src/apps/content/thematic_classifier.py](../../src/apps/content/thematic_classifier.py) | Themes + scene moments |
| [src/apps/production/thematic_stills.py](../../src/apps/production/thematic_stills.py) | Fandom + TMDb fallback |
| [src/apps/production/cross_ref_images.py](../../src/apps/production/cross_ref_images.py) | Cross-reference characters |
| [src/apps/content/personas.py](../../src/apps/content/personas.py) | Persona prompts, voice, edit_style |
| [scripts/production/produce_for_series.py](../../scripts/production/produce_for_series.py) | CLI core de producción 1 serie |
| [scripts/production/run_rotation_batch.py](../../scripts/production/run_rotation_batch.py) | Orquestador batch |
| [scripts/production/clean_and_produce.py](../../scripts/production/clean_and_produce.py) | Reset + produce |
| [tests/production/](../../tests/production/) | Suite pytest del dominio |

> ✅ Estos scripts ya viven en `scripts/production/`. `run_rotation_batch.py`
> invoca a `produce_for_series.py` por subprocess con path
> `scripts/production/produce_for_series.py` (cwd = repo root vía `os.chdir`).

## Archivos que NO puedes tocar

- `src/apps/signals/market_signals.py`, `signals_distiller.py`, `signals_validation.py`,
  `brief_resolver.py` → **Signals Agent**
- `src/apps/scoring/hook_scorer.py`, hook_cps en script_generator → **Scoring Agent**
- `tokens/*.json`, upload_*.py → **Uploads Agent**

---

## Contratos de datos

### Tabla `content_produced` (escribe este agente)

- 1 fila por video efectivamente renderizado
- `persona`, `series_slug`, `series_title`, `video_type` obligatorios
- `produced_at` ≥ `created_at` del brief consumido
- Lee de `persona_briefs.brief_ids` para marcar consumed_at vía rotator

### Tabla `series_themes` y `scene_moments` (lee este agente)

- Producto del `thematic_classifier`. NO modifica directamente.
- Si una serie no está clasificada → `ensure_series_classified()` la clasifica
  antes de proceder.

---

## Definition of Done por tipo de tarea

### Añadir serie nueva al CATALOG

- [ ] Entrada en `CATALOG` con `title`, `tmdb_id`, `primary_personas`, `tags`
- [ ] ≥ 2 aliases para el slug en `brief_resolver.ALIAS_MAP`
  (este cambio es de **Signals Agent** — abre sub-tarea)
- [ ] `TestCatalog::test_no_duplicate_slugs` pasa
- [ ] `TestCatalog::test_all_personas_have_catalog_entries` sigue ≥ 4 por persona
- [ ] Smoke manual: `pick_next` puede elegirla

### Cambiar pacing / EDL

- [ ] No romper retrocompat con `expand_hook` (ver test `TestHookScorer`)
- [ ] CPS por vtype documentado en `script_generator.HOOK_RULES`
- [ ] Regenerar 1 video por persona × tipo y validar visualmente

### Añadir nuevo `treatment_tone`

- [ ] Entrada en `TESTABLE_VARIABLES` de `ab_testing.py`
- [ ] Plantilla JSON en `data/script_templates/`
- [ ] A/B test sembrado vía `setup_hook_ab_tests.py` (Scoring Agent)
- [ ] min_samples ≥ 3, p < 0.10

### Modificar rotator scoring

- [ ] Test `TestScoreCandidate::test_brief_boost_increases_score` sigue pasando
- [ ] Test `TestPickNext::test_consume_briefs_marks_them` sigue pasando
- [ ] Documentar cambio en `content_rotator.score_candidate` docstring
- [ ] Justificación: por qué este peso, no otro

---

## Comando único de verificación

```powershell
.\scripts\testing\run_production.ps1
```

Esto corre:
1. `pytest tests/production/ -v`
2. Smoke en seco del rotator: pick para las 3 personas sin consumir briefs

Para verificación full con render (lento, requiere GPU):
```powershell
python scripts/production/produce_for_series.py --series "Berserk" --persona deep_mind --dry-run
```

---

## Métricas que sigues

| Métrica | Baseline | Cómo medir |
|---|---|---|
| Coverage `content_rotator.py` | ≥ 70% | `pytest --cov=apps.production.content_rotator` |
| Tests production suite | < 5s | `pytest tests/production/ --durations=0` |
| Videos producibles por persona | ≥ 4 | `len([s for s,e in CATALOG.items() if persona in e["primary_personas"]])` |
| Tiempo render 1 short | < 15s | output del CLI |
| Tamaño short renderizado | 8-15 MB | `Path(final).stat().st_size` |

---

## Anti-patrones específicos

- ❌ Hardcodear paths absolutos (`C:/Users/...`) — todo relativo a ROOT
- ❌ Subir archivos directamente desde el render (eso es **Uploads Agent**)
- ❌ Modificar `consumed_at` desde el script_generator (solo el rotator)
- ❌ Llamar a `produce_for_series` sin `series_slug` clasificada
- ❌ Forzar voces/CPS sin pasar por las funciones canónicas del módulo
- ❌ Saltar `expand_hook` en segmentos marcados `is_hook=True`

---

## Movimiento ejecutado (2026-06-03)

Los 3 runners se movieron de `scripts/` plano a `scripts/production/`:

1. ✅ Path de subprocess en `run_rotation_batch.py` → `scripts/production/produce_for_series.py`
2. ✅ Path-math interno corregido (`__file__/../..` = repo root) + `os.chdir(ROOT)`
3. ✅ GHA `content-rotation.yml` actualizado a la ruta nueva

---

## Tareas abiertas conocidas

Ver [docs/testing/PENDING_TESTS.md](../testing/PENDING_TESTS.md) items:
- **#5** Expansión continua CATALOG (operacional)
- **#7** Bandit Thompson sobre `PERSONA_ALIGNMENT` (necesita data)
- **#10** Benchmark vs AutoClip

---

*Owner: este agente. Última actualización: 2026-06-02.*
