# MLOps Flow · YouLikeIt

> Mapa completo del sistema usando como brújula el diagrama de **Sculley et al., NIPS 2015 — "Hidden Technical Debt in Machine Learning Systems"**.
> La caja naranja "ML Code" es minúscula comparada con la infraestructura que la rodea. Este documento traza qué pieza del repo corresponde a cada caja, qué está implementado, qué es pseudocódigo y qué falta.
>
> **Actualización 2026-11-04.** El producto actual es el ETL de lecciones de empatía con cine
> (sección siguiente). Desde "Posicionamiento del proyecto" en adelante el doc describe el producto
> anterior (señales → briefs → shorts por persona, mayo–junio 2026), que sigue en el repo como legacy.
> Detalle por etapa del ETL nuevo: [SUPERCUT_ETL.md](SUPERCUT_ETL.md).

---

## Producto actual (2026-11): ETL de lecciones

```
 FUENTES CON DERECHOS                      ETL LOCAL (PC del creador, RTX 5060 opcional)                      SERVING
 ─────────────────────                     ───────────────────────────────────────────────                    ───────
 Internet Archive ─┐   apps.media                 apps.moments                 apps.supercut
 (public_domain,   ├─► probe → proxy → audio  ──► candidatos (planos)   ──►  plan (≤ 60 s, 1 escena/obra)
  open_license)    │   + planos (1 pasada)        señales por película        guion IA | plantilla
 MOVIES_DIR (owned)┘   → ASR por palabra          anclas Wikiquote/Wiki       voz edge-tts
                       (local | Groq)             etiquetas LLM validadas     render 1080x1920, −14 LUFS
                       rango HTTP por clip        find entre obras (MMR)            │
                                                                                     ▼
                                       apps.studio (127.0.0.1:8001) + frontend-react (127.0.0.1:5180)
                                       cola de jobs (1 worker) · revisión humana · aprobar/rechazar
                                                                                     │
                                       apps.publish ── YouTube (OAuth app instalada, privado/publishAt)
                                                    └─ TikTok: web/ en Railway (puente) → PUT directo → inbox
```

| Caja Sculley | Estado | Implementación |
|---|---|---|
| **Configuration** | 🟢 | `.env` (local), variables de Railway (sitio), `data/vocab/*.json` (vocabulario y pesos), `ylk doctor` |
| **Data Collection** | 🟢 | `apps/media/archive_org.py`, `local_library.py`, `sources.search_all` (solo derechos usables) |
| **Data Verification** | 🟢 | Capa de derechos en ingesta, plan y render; salida del LLM validada y saneada contra el vocabulario; hechos del guion solo desde la DB |
| **Feature Extraction** | 🟢 | `apps/moments/features.py` (8 señales 0-1, percentiles por película), `anchors.py`, `scenes.py` |
| **ML Code** | 🟢 | `labeling.py` (LLM top-K), `retrieval.py` (MMR entre obras), `supercut/planner.py`, `script.py` |
| **Analysis Tools** | 🟡 | `ylk media runs` (segundos por etapa), "por qué" de cada momento (contribuciones), página Momentos del estudio |
| **Process Management** | 🟢 | `apps/studio/jobs.py`: cola en `studio_jobs`, un worker, recuperación al arrancar; `index_many` en pipeline red/GPU |
| **Machine Resource Management** | 🟢 | `utils/gpu_lock.py` (lock entre procesos por PID), `apps/media/storage.py` (crudo de solo lectura, caché con tope) |
| **Serving Infrastructure** | 🟢 | Estudio local (FastAPI + Vite) y sitio `web/` en Railway (`/healthz`) |
| **Monitoring** | 🟡 | `media_index_runs`, `studio_jobs`, eventos por `/ws`, healthcheck de Railway. Sin alertas ni métricas de calidad (precision@5 pendiente) |

---

## Posicionamiento del proyecto

> Producto anterior (legacy). Ver la sección anterior para el producto actual.

YouLikeIt **no es** un canal de YouTube tradicional. Es un **sistema de producción algorítmica de contenido analítico** donde:

- 3 personas (Deep Mind, Pop Oracle, Voz Latina) generan 3 tipos de short cada 3 días.
- La señal de entrada es **el consumo cultural real** (qué está viendo/jugando/leyendo el mundo).
- La señal de salida es **retención por video** (analítica YT/TT) + ratio de engagement.
- El loop completo es un experimento continuo de A/B testing con hipótesis comprobables.

La fase actual (mayo 2026) prioriza **calidad de contenido y analítica de mercado por encima de la integración de publicación YT/TT**. Por eso este documento se enfoca en las cajas izquierdas del diagrama (Data Collection → Feature Extraction).

---

## Mapa Sculley → repo

| Caja Sculley | Estado | Implementación actual | TODO / mejora |
|---|---|---|---|
| **Configuration** | 🟢 Parcial | `src/core/config.py` (Settings), `.env`, `tokens/personas.json` | Centralizar feature flags en `config.yaml`; consolidar `personas.json` + cuentas en un solo lugar versionado |
| **Data Collection** | 🟡 En construcción | `market_signals.py` (NEW), `culture_feed.py`, `trends.py`, `trending_anime.py`, `fandom_scraper.py`, `mangadex.py`, `tmdb_enriched.py` | Añadir Famitsu/4Gamer (JP gaming), fuentes LatAm RSS, podcasts via RSS |
| **Data Verification** | 🟡 Parcial | `signals_distiller.py` dedupe capa 1 + fuzzy 88; **`signals_validation.py`** con 8 invariantes (hard/soft) | Migrar a Pandera cuando escale a DataFrames; hoy sin dependencias |
| **Feature Extraction** | 🟡 En construcción | `signals_distiller._score_cluster()`, `panel_matcher.py`, `thematic_classifier.py` | Migrar a embeddings (sentence-transformers MiniLM); feature store estilo Feast |
| **ML Code** (caja naranja) | 🟢 Funcional | `algorithmic_script_generator.py`, `script_generator.py`, `video_director.py`, `panel_matcher.py`, `treatment_tones.py`, `ab_testing.py` | Es deliberadamente algorítmico, no LLM. Próximo paso: bandit Thompson sobre `treatment_tones` |
| **Analysis Tools** | 🟡 Parcial | Logs + `analytics` + `hook_scores` table; **`briefs_dashboard.py`** CLI (4 paneles + resolve preview + validation) | Migrar a Streamlit/Grafana cuando el CLI deje de ser suficiente |
| **Brief Resolver** (puente texto→slug) | 🟢 Funcional | `brief_resolver.py` (alias map + fuzzy 75 + series_themes lookup); queue `unresolved_briefs_queue` para curación humana | Capa 4 con embeddings (sentence-transformers) cuando justifique la dep |
| **Hook Quality Gate** (post-render) | 🟢 Funcional | `hook_scorer.py` (audio energy + CPS + accent + LLM opcional); gate en `produce_for_series.py` (block_on_fail=False mientras calibramos) | Activar `block_on_fail=True` cuando MIN_HOOK_SCORE esté calibrado contra retention real (>30 videos/persona/vtype) |
| **Process Management Tools** | 🟡 Parcial | `run_rotation_batch.py`, `topic_clusters.py` scheduler, GitHub Actions cron cada 3d | Airflow/Prefect si crece; hoy GHA + scripts CLI es suficiente |
| **Machine Resource Management** | 🟢 Funcional | Docker Compose + `start-all.ps1`, GPU NVENC para FFmpeg | Optimizar: hot-cache de subindices, paralelismo de renders |
| **Serving Infrastructure** | 🔴 No empezado (en este producto) | `cli uploader` directo a YT/TT (deshabilitado por usuario) | Superado: el producto actual sirve por el estudio local y `web/` (ver arriba) |
| **Monitoring** | 🟡 En construcción | `scraper_health` table, retention_curves table; **Plausible self-host** (`plausible_client.py` + `docker-compose.plausible.yml`) sobre el sitio público + dashboard CLI `analytics_dashboard.py` (4 paneles) | Alertas por scraper caído > 24h; SLO de "briefs nuevos por persona por semana"; conectar uptime de Plausible a alertas |
| **Internal Signals** (loop de 1ª parte) | 🟢 Funcional | `internal_signals.py` bridge: tráfico propio de Plausible → `Signal(domain='internal')`; tablas `plausible_pageviews` / `plausible_events` | Persistir a `market_signals` (gateado a sub-tarea Signals Agent: `domain += internal`); ponderar afinidad por persona en el distiller |

---

## El flujo end-to-end (estado actual)

```
                ┌───────────────────────────────────────────────────────────┐
                │                  EXTERNAL WORLD                           │
                │                                                           │
  ┌─────────────┴──────────┐  ┌──────────────────┐  ┌────────────────────┐ │
  │   Editorial RSS        │  │  Foros (Reddit,  │  │  Charts (Steam,    │ │
  │   (ANN, Polygon,       │  │   Letterboxd,    │  │   OpenCritic,      │ │
  │   Variety, RPS, IGN,   │  │   MAL)           │  │   Trakt, Trending  │ │
  │   Eurogamer)           │  │                  │  │   AniList)         │ │
  └─────────────┬──────────┘  └─────────┬────────┘  └─────────┬──────────┘ │
                │                       │                     │            │
                └───────────────────────┼─────────────────────┘            │
                                        │                                  │
                                        ▼                                  │
        ┌──────────────────────────────────────────────────────────┐       │
        │  market_signals.py                                       │       │
        │  · refresh_all_sources(conn, domains=[…])                │       │
        │  · normalize_title (lowercase + strip)                   │       │
        │  · UNIQUE(source, normalized_title) guard                │       │
        │  · scraper_health bookkeeping                            │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼   table: market_signals                           │
        ┌──────────────────────────────────────────────────────────┐       │
        │  signals_distiller.py                                    │       │
        │  · _build_clusters  (dedupe capa 1)                      │       │
        │  · _fuzzy_merge     (rapidfuzz ratio ≥ 88, capa 2)       │       │
        │  · _score_cluster   (freq · recency · domain · kw · src) │       │
        │  · _llm_angle       (LLM solo para 1 frase suggested)    │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼   table: persona_briefs                           │
        ┌──────────────────────────────────────────────────────────┐       │
        │  brief_resolver.py   (texto → slug)                      │       │
        │  · alias map (override exacto)                           │       │
        │  · fuzzy token_set_ratio ≥ 75 contra CATALOG titles      │       │
        │  · lookup contra series_themes                           │       │
        │  · si no matchea → unresolved_briefs_queue (humano)      │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼                                                   │
        ┌──────────────────────────────────────────────────────────┐       │
        │  content_rotator.py                                      │       │
        │  · score = persona_aff + freshness + trending +          │       │
        │            briefs_boost(slug, persona)                   │       │
        │  · pick_next(consume_briefs=True) → mark_brief_consumed  │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼                                                   │
        ┌──────────────────────────────────────────────────────────┐       │
        │  algorithmic_script_generator.py + script_generator.py   │       │
        │  · JSON templates (narration/personality/test)           │       │
        │  · CPS hook rules                                        │       │
        │  · seeded RNG por series (reproducible)                  │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼                                                   │
        ┌──────────────────────────────────────────────────────────┐       │
        │  produce_for_series.py + video_director.py               │       │
        │  · edge-tts → audio                                      │       │
        │  · panel_matcher → images                                │       │
        │  · expand_hook (CPS sub-cuts)                            │       │
        │  · animated_subs (Hook/HookKey ASS styles)               │       │
        │  · FFmpeg h264_nvenc (GPU)                               │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼   produced_videos/{persona}/{slug}/{vtype}.mp4    │
        ┌──────────────────────────────────────────────────────────┐       │
        │  hook_scorer.py  (POST-RENDER QUALITY GATE)              │       │
        │  · audio_energy (RMS peak 0-0.5s)                        │       │
        │  · cps_score (cuts en 0-1.5s vs target por vtype)        │       │
        │  · accent_word (presencia en primer subtítulo)           │       │
        │  · llm_score (opcional, 1-10 normalizado)                │       │
        │  · persiste en hook_scores; block_on_fail=False hoy      │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼                                                   │
        ┌──────────────────────────────────────────────────────────┐       │
        │  Upload (DESHABILITADO por usuario hasta calidad OK)     │       │
        │  · ex12_upload.py (YouTube Shorts)                       │       │
        │  · TikTok inbox (cuando OAuth pase review)               │       │
        └──────────────┬───────────────────────────────────────────┘       │
                       │                                                   │
                       ▼                                                   │
                  YOUTUBE / TIKTOK ──── retention metrics ─────────────────┘
                                       (Analytics API, only own channel)
```

---

## Decisiones de diseño y trade-offs

### 1. ¿Por qué algorítmico (no LLM) en script_generator?
**Razón:** reproducibilidad y costo cero. La misma serie + persona + tono produce el mismo script. Permite tests A/B limpios donde la variable es el tono, no la "lotería" del LLM.
**Trade-off:** menor diversidad léxica. Se compensa rotando JSON templates con `seeded_extra`.
**Dónde sí usamos LLM:** únicamente para `suggested_angle` (1 frase) en briefs. Costo $0.0001/llamada con Gemini 2.0 Flash.

### 2. ¿Por qué SQLite y no Postgres?
**Razón:** corre sin servidor, sin Docker para el dev local, suficientemente rápido a este volumen. `WAL mode` permite lectura concurrente.
**Trade-off:** no escala a multi-tenant. Si llegamos a "producto" (ver tesis Sec. Conclusiones), migrar a Postgres + pgvector (mismo schema funciona).

### 3. ¿Por qué dedupe en 2 capas (string + fuzzy)?
**Razón:** capa 1 (exact normalized) es O(1) y atrapa 80% de duplicados. Capa 2 (rapidfuzz 88) atrapa los restantes sin caer en el costo de embeddings.
**Trade-off:** falla con transliteración JP↔EN ("Frieren" vs "Sousou no Frieren"). **TODO**: capa 3 con embeddings cuando el LLM provider exponga endpoint barato.

### 4. ¿Por qué scoring determinista vs. ranking aprendido?
**Razón:** no tenemos aún suficientes datos de outcome (retention) para entrenar. Cuando tengamos N≥50 videos por persona × tono, abrimos bandit Thompson.
**Trade-off:** los pesos en `PERSONA_ALIGNMENT` son priors razonables, no aprendidos.

---

## Operación

### Comandos del día a día

```bash
# Refresh completo (cada 4h vía cron / GHA)
python scripts/signals/refresh_market_signals.py

# Solo gaming + foros (más rápido, sin LLM)
python scripts/signals/refresh_market_signals.py --domains gaming --no-llm

# Solo una fuente (debug)
python scripts/signals/refresh_market_signals.py --sources steam_charts

# Estado actual sin tocar nada
python scripts/signals/refresh_market_signals.py --report-only

# Salida JSON para dashboard
python scripts/signals/refresh_market_signals.py --json > out/signals.json
```

### Cron sugerido (`.github/workflows/refresh-signals.yml`)

```yaml
on:
  schedule:
    - cron: "0 */4 * * *"   # cada 4h: ingesta + distill sin LLM
    - cron: "0 6 * * *"     # diario 6 AM UTC: distill con LLM (suggested_angle)
jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - run: pip install -r requirements.txt
      - run: python scripts/signals/refresh_market_signals.py --fail-on-empty --json > signals_report.json
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          TRAKT_CLIENT_ID: ${{ secrets.TRAKT_CLIENT_ID }}
      - uses: actions/upload-artifact@v4
        with:
          name: signals-report
          path: signals_report.json
```

---

## Capa de **Monitoring** (la más floja hoy)

### Métricas que deberían medirse

| Métrica | Cómo | Umbral inicial |
|---|---|---|
| `market_signals.total_new_last_24h` | `SELECT COUNT(*) FROM market_signals WHERE fetched_at > datetime('now', '-24 hour')` | Alerta si < 100 |
| `scraper_health.fail_rate_per_source` | `SELECT scraper_name, failure_count*1.0/(success_count+failure_count)` | Alerta si > 0.3 |
| `persona_briefs.unconsumed_per_persona` | `SELECT persona, COUNT(*) FROM persona_briefs WHERE consumed_at IS NULL GROUP BY persona` | Alerta si < 3 |
| `videos_produced.retention_at_3s` | desde YouTube Analytics | objetivo > 70% |
| `videos_produced.retention_at_30s` | desde YouTube Analytics | objetivo > 50% |
| LLM cost / día | sum costos | budget $0.10/día |

### Dashboard mínimo (no implementado, plan)

- **Tab 1 — Salud de scrapers:** tabla con last_success, fail_rate, latency p95.
- **Tab 2 — Briefs por persona:** top 10 por score, marcando consumed.
- **Tab 3 — Retention por video:** curva por persona × tipo × hook variant.
- **Tab 4 — A/B running:** estado de tests vivos (Welch p-value, min_samples).

**Stack sugerido para implementar:** Streamlit (1 día de trabajo) o Grafana + SQLite datasource si vamos a producción.

---

## Roadmap MLOps (priorizado)

> Roadmap del producto anterior. El estado por fases del producto actual está en [ROADMAP.md](../../ROADMAP.md).

### Sprint actual (mayo–junio 2026)
- [x] Ingestión multi-fuente (`market_signals.py`)
- [x] Distiller con scoring por persona (`signals_distiller.py`)
- [x] Schema (`market_signals`, `persona_briefs`)
- [x] **Conectar `content_rotator.py` a briefs** vía `brief_resolver.suggest_boost_for_slug` (sin reemplazar CATALOG; solo añade boost)
- [x] Queue `unresolved_briefs_queue` para briefs sin match (curación humana)
- [x] GHA cron `refresh-signals.yml` (4h sin LLM + diario con LLM)
- [x] Invariantes de data verification (`signals_validation.py`, hard+soft)
- [x] Dashboard CLI (`briefs_dashboard.py`)
- [x] CATALOG expandido a 4 dominios (anime + cine antihéroes + LatAm + gaming, ~40 slugs)
- [x] `ALIAS_MAP` reconstruido (~160 aliases curados, agrupados por dominio)
- [x] `validate_alias_map()` + `alias_map_stats()` helpers para CI

➡️ Pendientes diferidos: ver [docs/testing/PENDING_TESTS.md](../testing/PENDING_TESTS.md) (10 items priorizados con definition-of-done).

### Sprint próximo (junio–julio)
- [ ] Embeddings para dedupe capa 3 (sentence-transformers all-MiniLM-L6-v2 local)
- [ ] Dashboard Streamlit
- [ ] Pandera schemas para data verification
- [ ] Bandit Thompson sobre treatment_tones
- [ ] Famitsu + 4Gamer (JP gaming) — el mercado JP filtra al global con 2–3 semanas de delay

### Backlog medio plazo
- [ ] Reentrenamiento de `PERSONA_ALIGNMENT` desde outcomes (retention)
- [ ] Migración a Postgres + pgvector (cuando crucemos 1M señales)
- [ ] Feature store estilo Feast (offline parquet + online SQLite)
- [ ] LLM cost tracker per-call con budget gate
- [ ] Modelo de "novedad vs cíclico" — flag si una señal es nueva o un retorno predecible (AOT cada N meses)

---

## Anti-patrones que evitar (lecciones de Sculley)

1. **Glue code**: cada fuente que añadamos debe seguir el contrato `() → list[Signal]`. No proliferar adapters específicos por fuente fuera de `market_signals.py`.
2. **Pipeline jungles**: el flujo `signals → briefs → script → video` está intencionalmente lineal y unidireccional. No introducir feedback loops sin medir.
3. **Dead experimental code paths**: el `--use-llm=True` en `script_generator.py` es legacy. Si en 3 meses nadie lo usa, eliminarlo en vez de mantenerlo "por si acaso".
4. **Configuration debt**: cada nuevo flag debe documentarse aquí o en `docs/CONFIG.md`. Flags huérfanos son veneno.
5. **Undeclared consumers**: `persona_briefs` es leído por `content_rotator`. Si alguien más lee la tabla directamente, declarar acá la dependencia.

---

## Apéndice · contrato de datos

### `market_signals` (raw)

| Campo | Tipo | Notas |
|---|---|---|
| `source` | TEXT | Nombre canónico (`steam_charts`, `reddit_r_anime`, etc.) |
| `source_type` | TEXT | `gaming_chart` \| `gaming_review` \| `reddit_thread` \| `editorial_rss` \| `release_tracker` \| `letterboxd` \| `forum` |
| `domain` | TEXT | `gaming` \| `anime_manga` \| `movies_tv` \| `music` \| `latam` |
| `normalized_title` | TEXT | Lowercase, sin puntuación, espacios colapsados (UNIQUE con source) |
| `raw_score` | REAL | Source-native: upvotes, posición invertida en chart, viewers |
| `raw_meta` | TEXT | JSON con campos específicos de la fuente |
| `fetched_at` | TS | UTC |

**Invariantes:**
- `(source, normalized_title)` es UNIQUE — si Reddit re-promueve un thread no genera duplicado.
- `fetched_at` siempre en UTC ISO format.
- `domain` debe estar en el enum (validar con pandera en futuro).

### `persona_briefs` (distilled)

| Campo | Tipo | Notas |
|---|---|---|
| `persona` | TEXT | `deep_mind` \| `pop_oracle` \| `latam` |
| `cluster_key` | TEXT | `normalized_title` canónico del cluster |
| `headline` | TEXT | Mejor título crudo del cluster |
| `score` | REAL | freq · recency · domain · kw · src |
| `frequency` | INT | Cuántas señales formaron el cluster |
| `sources_json` | TEXT | JSON array de `market_signals.id` |
| `suggested_angle` | TEXT | LLM-generated, opcional |
| `consumed_at` | TS | Set por `content_rotator` al elegir el brief |

**Invariantes:**
- `(persona, cluster_key, created_at)` UNIQUE para evitar duplicados por corrida.
- `consumed_at IS NULL` ⇒ aún disponible para ser elegido por el rotator.

---

## Cambios futuros marcados como TODO/FIXME

Búsqueda rápida en el repo:

```bash
grep -rn "TODO(mlops)" src/ scripts/ docs/
grep -rn "FIXME(mlops)" src/ scripts/ docs/
```

Cada TODO debe responder: (a) qué falta, (b) qué desbloquea, (c) condición de "hecho".

---

*Documento mantenido por el equipo. Última revisión: 2026-11-04 (sección "Producto actual"); el resto, 2026-05-29.*
