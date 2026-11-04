# Changelog

Todos los cambios notables de YouLikeIt. Formato basado en
[Keep a Changelog](https://keepachangelog.com/). Las fechas son UTC.

Categorías: `Added` · `Changed` · `Deprecated` · `Removed` · `Fixed` · `Security`.

## [Unreleased]

### Rama `feat/supercut-media` (2026-11-03 → 2026-11-04): lecciones de empatía con cine

#### Added
- **`apps/media`** (Extract): proveedores Internet Archive y biblioteca local (`MOVIES_DIR`) con capa
  de derechos; extracción por rango HTTP con corte exacto; descarga paralela del proxy; audio + cortes
  de plano en una pasada; ASR local (faster-whisper) o por API (Groq); tiempos por etapa en
  `media_index_runs`; ciclo de vida del almacenamiento (`ylk media storage`, `ylk media gc`).
- **`apps/moments`** (Transform): vocabulario controlado en `data/vocab/` (61 tropos, 13 emociones,
  beats, roles, temas); candidatos ajustados a planos; señales con percentiles por película; anclas
  Wikiquote/Wikipedia; etiquetado LLM validado; búsqueda entre obras con MMR (`ylk moments find`).
- **`apps/supercut`**: planificador (≤ 60 s, una escena por obra, orden por año), guion con IA y
  plantilla de respaldo, narración edge-tts, render 1080x1920 a −14 LUFS, previews de momentos.
- **`apps/publish`**: TikTok como borrador vía el puente de `web/` (PUT directo PC → TikTok) y YouTube
  con OAuth de app instalada, tokens cifrados con Fernet y subida privada con `publishAt`.
- **`apps/studio`**: API FastAPI local (127.0.0.1:8001, `ylk studio`) con token, guardia de origen,
  allowlist de archivos, cola de jobs de un solo worker y progreso por `/ws`. Contrato en
  `docs/architecture/STUDIO_API.md`.
- **`frontend-react`** convertido en el estudio local en español (Inicio, Biblioteca, Momentos, Editor,
  Revisión, Trabajos, Vocabulario); `scripts/ops/studio.ps1` arranca API + front.
- **`web/`**: sitio público en Railway (explorar por emoción, términos, privacidad, TikTok Login Kit,
  "Send to TikTok as draft", archivos de verificación de URL en lista permitida y puente
  `/api/studio/*`). Job `web` en CI. `scripts/web/export_catalog.py` y `make_demo_lesson.py`.
- `src/integrations/ai/` (ASR y LLM JSON intercambiables: ollama, groq, gemini) y `ylk doctor`
  (`integrations/credentials_check.py`).
- Tablas nuevas: `works`, `media_assets`, `shots`, `transcript_segments`, `transcript_words`,
  `media_index_runs`, `vocab`, `work_texts`, `moments`, `moment_labels`, `lessons`, `lesson_items`,
  `lesson_issues`, `publications`, `studio_jobs`, `cross_references`; en el sitio, `web.db`
  (`tiktok_accounts`, `publishes`).
- Docs: `SUPERCUT_ETL.md`, `INDEX_A_FILM.md`, `TIKTOK_APP_REVIEW.md`, `web/README.md`, ADRs 0004–0008,
  handbooks `MEDIA_AGENT.md` y `MOMENTS_AGENT.md`.

#### Changed
- `core.db.get_db` usa WAL y `busy_timeout=5000`; `utils.websocket_hub.notify` es seguro desde hilos.
- Modelo de Groq por defecto: `openai/gpt-oss-120b` (`llama-3.3-70b-versatile` fue retirado).
- `requirements.txt` (base) separado de `requirements-gpu.txt` (pesado, incluye la base).
- `tests/core` renombrado a `tests/schema` (el paquete tapaba a `src/core`).
- README, ROADMAP, SETUP_CUENTAS, SECURITY, UPLOADS y RUNBOOK reescritos para el producto actual.

#### Removed
- Servicio de la API ex29 y del front viejo en `docker-compose.yml` (inseguros). ex15/ex28/ex29 quedan
  solo en `scripts/legacy/`.
- `data/shorts_pipeline.db` dejó de versionarse.

#### Fixed
- ASR local robusto en Windows/Docker y lock de GPU que detecta procesos muertos por PID.
- Groq: espera `Retry-After` en `429` y reintenta `400 json_validate_failed`; saneo por ítem de valores
  fuera del vocabulario.
- Anclas: títulos exactos primero (la búsqueda de Wikiquote devolvía páginas de personas), tolerancia
  de ±2 años entre fuentes y caché de anclas vacías que vence a los 7 días.
- Internet Archive: masters MPEG-PS de DVD sin índice → derivado h.264 del mismo original; reintentos
  y caída al proxy cuando un nodo responde 500.

#### Security
- `tokens/` y `.claude/settings.local.json` fuera de git. Quedan en el historial una key de TMDB y la
  contraseña de qBittorrent: rotar (ver `docs/operations/SECURITY.md`).
- Tokens de TikTok (Railway) y de YouTube (local) cifrados en reposo.

### Reorganización y producto anterior (2026-06)

#### Added
- Capa de señales de mercado: `market_signals.py` (ingesta multi-fuente),
  `signals_distiller.py` (clusters + scoring por persona), `signals_validation.py`
  (8 invariantes hard/soft), `brief_resolver.py` (texto→slug, alias map + fuzzy).
- `topic_clusters.py` y `market_signals` / `persona_briefs` / `scraper_health` en el schema.
- Hook quality gate post-render: `hook_scorer.py` (audio energy + CPS + accent +
  LLM opcional) con gate en `produce_for_series.py` (`block_on_fail=False` mientras se calibra).
- Generador de scripts algorítmico (cero dependencia de LLM en el camino crítico).
- Queue `unresolved_briefs_queue` para briefs sin match (curación humana).
- GHA cron `refresh-signals.yml` (4h sin LLM + diario con LLM).
- Suite de tests por dominio (`tests/signals`, `tests/production`, `tests/scoring`,
  `tests/integration`) + `pyproject.toml` + `requirements-dev.txt`.
- Documentación reorganizada por propósito: `docs/architecture`, `docs/testing`,
  `docs/operations`, `docs/agents` con handbooks por dominio.
- `docs/architecture/DECISIONS/` con 3 ADRs retroactivas (algorítmico vs LLM,
  SQLite vs Postgres, CATALOG fijo).
- `docs/architecture/PERSONAS.md` (movido desde root), `docs/operations/UPLOADS.md`
  (movido desde root), `docs/_audit_report.md`.

#### Changed
- `scripts/` reorganizado en carpetas por dominio (`signals/`, `scoring/`,
  `production/`, `testing/`, `uploads/`, `setup/`, `legacy/`).
- `README.md` raíz reescrito como entry-point del sistema multi-persona
  (antes describía el pipeline de ejercicios viejo).
- `docs/architecture/MLOPS_FLOW.md`: paths corregidos a
  `scripts/signals/refresh_market_signals.py` y workflow `refresh-signals.yml`.

#### Removed
- Docs legacy al root: `ARCHITECTURE.md`, `DIAGRAMA_FLUJO_EDICION.md`,
  `FLUJO_PUBLICACION_CADA_3_DIAS.md`, `GUIA_EDICION_VIDEO.md`, `PLAN_FASE_2.md`.
- Artefactos TikTok duplicados en `docs/`: `privacy.html`, `terms.html`,
  `callback/index.html`, `tiktok…JXF.txt` (la fuente viva está en `youlikeit-web/public/`).

#### Deprecated
- Flag `--use-llm=True` en `script_generator.py` (dead path legacy; eliminar si nadie lo usa en 3 meses).
