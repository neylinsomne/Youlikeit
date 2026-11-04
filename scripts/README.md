# Scripts · Índice por dominio

> Punto de entrada recomendado: el CLI **`ylk`** (instalado con `pip install -e .`,
> ya incluido en la imagen Docker). Los scripts por dominio siguen disponibles para
> uso directo; `ylk` es un front-door delgado sobre ellos.

```
scripts/
├── README.md          ← estás aquí
├── _TEMPLATE_runner.py  plantilla para un runner nuevo (clónala)
├── signals/           Ingesta + distill + verify (dominio Signals)
├── production/        Rotator + render + batch orchestrator
├── scoring/           Hook scorer + A/B setup
├── analytics/         Plausible: setup + fetch stats + dashboard
├── testing/           Runners pytest por dominio + audit completo
├── setup/             Voces, OAuth, descargas iniciales (producto anterior)
├── uploads/           Subida por persona a YouTube / TikTok (producto anterior; ver apps/publish)
├── web/               Contenido del sitio público: export_catalog.py, make_demo_lesson.py
├── ops/               .ps1 de operación: studio.ps1 (estudio local), docker-*, run*, schedule*, sync-to-usb
└── legacy/            Pre-pytest + exercises ex00–ex40 (incluye ex15/ex28/ex29) + main.py — solo referencia
```

## Operación (scripts/ops/)

Los `.ps1` de operación viven en `scripts/ops/` y computan el repo root con
`$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path`, así que se
pueden invocar desde cualquier cwd:

```powershell
.\scripts\ops\studio.ps1               # estudio local: API (ylk studio) + front (Vite) en 127.0.0.1
.\scripts\ops\studio.ps1 -Check        # solo revisar requisitos (ylk, node, ffmpeg, STUDIO_TOKEN, puertos)
.\scripts\ops\studio.ps1 -Stop         # apagar API + front
.\scripts\ops\docker-setup.ps1          # levantar entorno + deps + playwright
.\scripts\ops\run.ps1 manga             # punto de entrada multi-pipeline
.\scripts\ops\run-content-flow.ps1      # ciclo de contenido (Docker)
.\scripts\ops\sync-to-usb.ps1           # backup outputs a USB E:
```

> `setup.ps1` (bootstrap del venv local) y `start-all.ps1`/`stop-all.ps1`
> (lanzador multi-proyecto del owner) se quedan en el root.
> `studio.ps1` guarda logs y PIDs en `%TEMP%\youlikeit-studio` (fuera del repo) y nunca imprime el token.

## Sitio público (scripts/web/)

```powershell
python scripts/web/export_catalog.py                 # DB local → web/app/data/catalog.json (dominio público + licencia abierta)
python scripts/web/export_catalog.py --include-owned # incluye copias propias
python scripts/web/make_demo_lesson.py               # lección demo "Fear" → web/app/lessons/ (+ lessons.json)
```

Después se despliega desde `web/` (ver [web/README.md](../web/README.md)).

## CLI unificado `ylk`

```bash
ylk --help                         # lista dominios + verbos
ylk signals refresh --no-llm       # = scripts/signals/refresh_market_signals.py
ylk signals verify --cleanup
ylk signals dashboard --validate
ylk produce --series "Berserk" --persona deep_mind --dry-run
ylk rotate --personas deep_mind pop_oracle latam
ylk score --rescore
ylk analytics dashboard
ylk media ingest "Horror Express" --year 1972   # fuente legítima → índice → ASR
ylk media index-many --pending --asr-backend groq
ylk media runs                     # tiempos por etapa del ETL
ylk moments run 1 --provider groq  # detectar + etiquetar un asset
ylk moments find emotion:fear --min-works 3
ylk studio                         # API del estudio en 127.0.0.1:8001 (sin el front)
ylk doctor                         # keys/tokens/stack sin mostrar valores
```

Los subcomandos del producto anterior reenvían sus flags al runner subyacente (passthrough);
`media`, `moments`, `studio` y `doctor` llaman directo a `src/apps/` y `src/integrations/`.
Runbook completo de una película: [docs/operations/INDEX_A_FILM.md](../docs/operations/INDEX_A_FILM.md). El CLI vive
en [src/cli/](../src/cli/); agregar un comando es agregar una función en
`src/cli/commands/<dominio>.py`.

## Regla de oro — cómo agregar funcionalidad de forma organizada

Toda funcionalidad nueva es una **tupla de 4**, alineada por dominio:

| Capa | Dónde | Qué |
|---|---|---|
| Lógica | `src/apps/<dominio>/` | el código de negocio (importable, testeable) |
| Entrada | `ylk <dominio> <acción>` (o `scripts/<dominio>/`) | runner **delgado**: parsea args y llama a `apps/<dominio>` |
| Tests | `tests/<dominio>/` | pytest del dominio |
| Handbook | `docs/agents/<DOMINIO>_AGENT.md` | scope, DoD, comando de verificación |

Un **runner** no contiene lógica de negocio: orquesta y delega. Plantilla en
[`_TEMPLATE_runner.py`](_TEMPLATE_runner.py).

## Regla Docker (integraciones / dependencias)

- **Dependencias e integraciones de librerías van por Docker.** Una dep liviana se
  agrega a [`requirements.txt`](../requirements.txt) (base: CI + crons); una pesada
  (torch, whisper, OCR, scenedetect) a [`requirements-gpu.txt`](../requirements-gpu.txt).
  Luego se reconstruye la imagen
  (`docker compose build ytlab`). **Nunca** `pip install` suelto en el host.
- El paquete se instala editable en la imagen (`pip install -e .`), por eso los
  scripts importan `from apps.signals… import` sin trucos de `sys.path`.
- Forma canónica de correr un runner:
  ```bash
  docker compose run --rm ytlab ylk signals refresh --no-llm
  docker compose run --rm ytlab python scripts/production/produce_for_series.py --series "Berserk" --persona deep_mind
  ```

## Comandos esenciales

```powershell
.\scripts\testing\run_tests.ps1 -Mode quick      # verificación rápida (< 20s)
.\scripts\testing\run_all.ps1 -WithCoverage       # audit completo por dominios
.\scripts\testing\run_signals.ps1                 # un solo dominio
```

## Mapping con dominios y agentes

| Carpeta | Handbook del owner |
|---|---|
| `signals/` | [docs/agents/SIGNALS_AGENT.md](../docs/agents/SIGNALS_AGENT.md) |
| `production/` | [docs/agents/PRODUCTION_AGENT.md](../docs/agents/PRODUCTION_AGENT.md) |
| `scoring/` | [docs/agents/SCORING_AGENT.md](../docs/agents/SCORING_AGENT.md) |
| `analytics/` | [docs/agents/ANALYTICS_AGENT.md](../docs/agents/ANALYTICS_AGENT.md) |
| `testing/` | [docs/agents/QA_AGENT.md](../docs/agents/QA_AGENT.md) |
| `web/` | [web/README.md](../web/README.md) |
| `ops/studio.ps1` | [docs/architecture/STUDIO_API.md](../docs/architecture/STUDIO_API.md) |
| `setup/` | _(sin handbook; producto anterior)_ |
| `uploads/` | _(producto anterior; la publicación actual está en `src/apps/publish`, ver [UPLOADS.md](../docs/operations/UPLOADS.md))_ |
| `legacy/` | nadie. Solo lectura. |

---

*Última actualización: 2026-11-04.*
