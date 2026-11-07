# Pending Tests & Calibration

> Cosas que se dejan **explícitamente** para después de cerrar la arquitectura
> principal del flujo de información. No bloquean el diseño; sí bloquean activar
> el `block_on_fail=True` del hook scorer y reemplazar el CATALOG fallback.
>
> Cada pendiente declara: **qué**, **por qué se difiere**, **señal de "hacer
> ahora"**, y **definición de hecho**.

---

## 1. Smoke test E2E con datos reales (sin `--no-llm`)

**Qué**
- Correr `python scripts/signals/refresh_market_signals.py` con `GEMINI_API_KEY` real.
- Inspeccionar con `python scripts/signals/briefs_dashboard.py --validate --resolve-preview`.
- Validar que los `suggested_angle` tengan sentido editorial (revisión humana).
- Verificar que `validate_alias_map(CATALOG)` no tenga huérfanos tras cualquier
  cambio futuro.

**Por qué se difiere**
- Requiere internet en vivo y cuotas de API; mejor hacerlo cuando la
  arquitectura esté estable y nadie esté tocando schemas.

**Señal de "hacer ahora"**
- Antes de la primera publicación real a YouTube/TikTok.
- Cuando `briefs_dashboard.py --validate` reporte hard‑FAIL persistente.

**Definición de hecho**
- Reporte JSON adjunto al PR con: ≥80 signals/24h, ≥3 briefs unconsumed por
  persona, ≥1 brief que matcheó por capa `alias`, ≥1 por capa `fuzzy`,
  ≥1 entry queueada como `unresolved`.

---

## 2. Smoke `alias_map_consistency` en CI

**Qué**
Test corto que ejecuta al cargar el módulo:

```python
from apps.signals.brief_resolver import validate_alias_map, alias_map_stats
from apps.production.content_rotator import CATALOG

errors = validate_alias_map(CATALOG)
assert not errors, f"ALIAS_MAP huérfanos: {errors}"

stats = alias_map_stats(CATALOG)
assert stats["coverage_pct"] >= 80, f"cobertura baja: {stats}"
```

**Por qué se difiere**
Aún no hay carpeta `tests/` activa con pytest configurado. Crear el harness
es trabajo aparte.

**Señal de "hacer ahora"**
Cuando montemos pytest para los otros módulos (hook_scorer, signals_distiller,
content_rotator).

**Definición de hecho**
- `tests/test_alias_map.py` corre en GitHub Actions en cada PR.
- Cobertura ≥80% del CATALOG declarada como umbral mínimo.

---

## 3. Calibración de `MIN_HOOK_SCORE`

**Qué**
- Generar 30+ videos por persona × vtype con `hook_scorer` activo.
- Subirlos como `unlisted` durante 28 días.
- Correlacionar `hook_scores.overall_score` con `retention_at_3s` real.
- Ajustar `MIN_HOOK_SCORE` y los `SCORE_WEIGHTS` (`audio_energy`, `cps`,
  `accent_word`, `llm`) según la regresión.
- Si Pearson r > 0.4 → activar `block_on_fail=True` en `produce_for_series.py`.

**Por qué se difiere**
Necesita datos reales de retención = necesita publicación = necesita TikTok
review aprobada + YouTube canales listos.

**Señal de "hacer ahora"**
Cuando tengamos 90 días de retention data en `analytics` para los 3 personas.

**Definición de hecho**
- Notebook `notebooks/calibrate_hook_score.ipynb` con regresión.
- `MIN_HOOK_SCORE` actualizado en `hook_scorer.py` con valor justificado.
- `block_on_fail=True` activo en `produce_for_series.py`.

---

## 4. Calibración de thresholds en `signals_validation.py`

**Qué**
Re‑evaluar los thresholds default:
- `MIN_SIGNALS_24H=80` ← prior conservador
- `MIN_SIGNALS_7D=1000`
- `MAX_DUP_PCT=25`
- `MIN_BRIEFS_PER_PERSONA=3`
- `MAX_SCRAPER_FAIL_RATE_PCT=30`
- `MAX_STALE_BRIEF_DAYS=14`

**Por qué se difiere**
Son priors razonables; recalibrar requiere ≥14 días de datos en producción
para tener baseline.

**Señal de "hacer ahora"**
Cuando `briefs_dashboard.py --validate` reporte hard‑FAIL más de 2 corridas
consecutivas en un mismo check.

**Definición de hecho**
- Override vía env vars en `refresh-signals.yml` documentado.
- Tabla en `docs/architecture/MLOPS_FLOW.md` actualizada con valores reales.

---

## 5. Expansión LatAm + gaming del CATALOG

**Qué**
- Validar tmdb_id correctos para todos los slugs LatAm (algunos podrían
  apuntar a la película en vez de la serie).
- Reemplazar `tmdb_id=0` en gaming por `igdb_id` real cuando integremos
  IGDB / GiantBomb API para enriquecimiento.
- Añadir 5‑10 series LatAm adicionales (telenovelas turcas dobladas,
  Café con Aroma de Mujer, La Usurpadora, Maria la del Barrio).
- Añadir 5‑10 juegos AAA + indie según ranking de Steam Charts (rotación).

**Por qué se difiere**
La estructura del CATALOG ya está; añadir entradas es operación de mantenimiento
recurrente, no diseño.

**Señal de "hacer ahora"**
Cuando `unresolved_briefs_queue` acumule >10 entradas con score >3.0 para
la misma persona durante una semana.

**Definición de hecho**
- `briefs_dashboard.py` muestra `unresolved` < 5 entries de manera sostenida.

---

## 6. Embedding‑based dedupe (capa 3)

**Qué**
- Añadir `sentence-transformers/all-MiniLM-L6-v2` (local, ~80MB) para
  resolver casos tipo `'Frieren'` vs `'Sousou no Frieren'` que la
  rapidfuzz 88 no atrapa.
- Usar también en `brief_resolver` como capa 4 antes de tirar a unresolved.

**Por qué se difiere**
- Añade ~80MB de dep y 1‑2s de cold start.
- Hoy la capa 2 (fuzzy 88) + alias map manual cubren la mayoría.

**Señal de "hacer ahora"**
- Si vemos en logs >15% de briefs duplicados tras la capa 2.
- O si la cobertura de `alias_map_stats` cae bajo 60%.

**Definición de hecho**
- Capa 3 en `signals_distiller._fuzzy_merge_clusters`.
- Capa 4 en `brief_resolver.resolve_brief`.
- Benchmark documentado: % dedupe ganado vs latency added.

---

## 7. Bandit Thompson sobre `PERSONA_ALIGNMENT`

**Qué**
Reemplazar los pesos manuales por bandit Thompson sampling que aprende qué
keywords/dominios producen videos con mejor retención.

**Por qué se difiere**
Necesita ≥50 videos producidos por persona × tono para tener señal estadística
útil. Hoy los priors son razonables.

**Señal de "hacer ahora"**
- Cuando `content_produced` tenga ≥50 filas/persona con retention asociado.

**Definición de hecho**
- `src/apps/scoring/bandit_persona.py` con Thompson sampler.
- Pesos actualizados nightly por GHA.

---

## 8. Streamlit dashboard (Analysis Tools)

**Qué**
Reemplazar `briefs_dashboard.py` CLI por Streamlit con:
- Tab salud de scrapers (timeline)
- Tab briefs por persona (clickable → ver señales que lo formaron)
- Tab unresolved queue (con botones "agregar al CATALOG" / "descartar")
- Tab retention curves (cuando exista data)
- Tab A/B running

**Por qué se difiere**
El CLI es suficiente mientras el equipo es 1 persona. Streamlit añade
servidor + auth + deploy.

**Señal de "hacer ahora"**
- Cuando haya ≥2 personas curando el flujo simultáneamente.

**Definición de hecho**
- `app/dashboard.py` Streamlit corriendo en `vara-alta.lat/inmu` (con
  reverse proxy y Turnstile).

---

## 9. Migración a Postgres + pgvector

**Qué**
- Cambiar `sqlite3` por Postgres para concurrencia real.
- Añadir `pgvector` para embeddings.
- Mantener el schema (es compatible salvo `AUTOINCREMENT` → `SERIAL`).

**Por qué se difiere**
SQLite + WAL es suficiente bajo 100K filas. Migrar antes de necesitarlo
introduce ops sin ganancia.

**Señal de "hacer ahora"**
- Cuando `market_signals` cruce ~500K filas.
- O cuando dos procesos necesiten escribir simultáneamente.

**Definición de hecho**
- Docker Compose con Postgres + pgvector.
- `db.py` con `DATABASE_URL` switch entre SQLite/Postgres.
- Migración Flyway versionada.

---

## 10. Benchmark vs AutoClip

**Qué**
- Tomar 5 videos largos por canal de cada persona.
- Cortarlos con AutoClip (Qwen LLM scoring).
- Generar shorts equivalentes con YouLikeIt.
- Subir ambos como unlisted al mismo canal.
- Comparar `retention_at_3s` y `retention_at_30s` a 28 días.

**Por qué se difiere**
- Necesita publicación habilitada.
- Es trabajo de evaluación, no de arquitectura.

**Señal de "hacer ahora"**
- Después de validar el pipeline propio con 1 mes de datos en producción.

**Definición de hecho**
- Reporte en `docs/BENCHMARK_AUTOCLIP.md` con tabla comparativa por persona.
- Decisión documentada: qué adoptamos del approach de AutoClip vs mantener.

---

## Apéndice · Orden recomendado de ataque

Cuando se vuelva a esto, el orden óptimo según costo/valor:

1. **#2 Smoke alias_map_consistency** (cheap, alta protección) — 1h
2. **#1 Smoke E2E con LLM real** (medio, valida todo) — 2h + esperas
3. **#5 Expansión CATALOG** (operacional continuo, no proyecto) — N/A
4. **#3 Calibración hook score** (necesita datos reales, valor alto) — 30d
5. **#4 Calibración thresholds validation** (paralelizable con #3) — 14d
6. **#6 Embeddings dedupe** (mejora capacidad, alto cost) — 1d + benchmark
7. **#8 Streamlit dashboard** (cuando crezca equipo) — 2d
8. **#7 Bandit Thompson** (cuando haya datos) — 3d
9. **#9 Postgres** (cuando duela SQLite) — 1‑2d
10. **#10 Benchmark vs AutoClip** (último) — 30d

---

*Última actualización: 2026-05-29.*
