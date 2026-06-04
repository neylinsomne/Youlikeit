# Changelog

Todos los cambios notables de YouLikeIt. Formato basado en
[Keep a Changelog](https://keepachangelog.com/). Las fechas son UTC.

Categorías: `Added` · `Changed` · `Deprecated` · `Removed` · `Fixed` · `Security`.

## [Unreleased]

### Added
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

### Changed
- `scripts/` reorganizado en carpetas por dominio (`signals/`, `scoring/`,
  `production/`, `testing/`, `uploads/`, `setup/`, `legacy/`).
- `README.md` raíz reescrito como entry-point del sistema multi-persona
  (antes describía el pipeline de ejercicios viejo).
- `docs/architecture/MLOPS_FLOW.md`: paths corregidos a
  `scripts/signals/refresh_market_signals.py` y workflow `refresh-signals.yml`.

### Removed
- Docs legacy al root: `ARCHITECTURE.md`, `DIAGRAMA_FLUJO_EDICION.md`,
  `FLUJO_PUBLICACION_CADA_3_DIAS.md`, `GUIA_EDICION_VIDEO.md`, `PLAN_FASE_2.md`.
- Artefactos TikTok duplicados en `docs/`: `privacy.html`, `terms.html`,
  `callback/index.html`, `tiktok…JXF.txt` (la fuente viva está en `youlikeit-web/public/`).

### Deprecated
- Flag `--use-llm=True` en `script_generator.py` (dead path legacy; eliminar si nadie lo usa en 3 meses).
