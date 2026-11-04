# tests/ · Suite pytest por dominio

> Tests organizados en subcarpetas espejando los dominios de `src/apps/`.
> Configuración global en [conftest.py](conftest.py) y `pyproject.toml` (`[tool.pytest.ini_options]`).
> El sitio público tiene su propia suite en `web/tests/` (ver abajo).

```
tests/
├── README.md             ← estás aquí
├── conftest.py           Fixtures compartidos (conn, sample_signals, mocked_http, frozen_time) + defensas
├── media/                apps.media: Internet Archive, biblioteca local, rango HTTP, análisis,
│                         planos + ASR, proveedores de IA, GPU lock, ylk doctor, esquema/indexer
│   └── test_live_archive.py   contra Internet Archive real (marker `network`)
├── moments/              apps.moments: vocabulario, escenas, señales, anclas, etiquetado,
│                         búsqueda entre obras, ciclo de vida del almacenamiento,
│                         regresiones de la corrida real (test_real_run_regressions.py)
├── supercut/             apps.supercut: lecciones (máquina de estados), planificador, guion,
│                         TTS, render con ffmpeg real sobre clips sintéticos, preview y demo
├── publish/              apps.publish: servicio, puente de TikTok y YouTube (APIs simuladas)
├── studio/               apps.studio: API (biblioteca, momentos, lecciones, revisión, jobs,
│                         publicación) y seguridad (token, origen, CORS, /api/files, WebSocket)
├── schema/               core.db: esquema completo en una DB fresca
├── signals/              producto anterior: señales de mercado → briefs
├── production/           producto anterior: content rotator
├── scoring/              producto anterior: hook scorer
├── analytics/            producto anterior: Plausible
└── integration/          E2E cross-dominio del producto anterior
```

`tests/schema` se llamaba `tests/core`; se renombró porque el paquete tapaba a `src/core`.

## Comandos rápidos

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pip install -e .

python -m pytest -q                   # suite completa offline (excluye network y gpu)
python -m pytest tests/media -q       # un dominio
python -m pytest tests/studio tests/supercut tests/publish -q

python -m pytest tests/media -m network -v   # Internet Archive real (opt-in)

cd web; python -m pytest -q; cd ..    # sitio público (sus propias deps: web/requirements.txt)
```

Los tests de `supercut` (render y preview) usan **ffmpeg real**: tiene que estar en el `PATH`.

## CI (`.github/workflows/tests.yml`)

| Job | Qué corre |
|---|---|
| `pytest` | `requirements.txt` + `requirements-dev.txt` + `pip install -e . --no-deps` + ffmpeg; `python -m pytest -q` en la raíz |
| `web` | En `web/`: `web/requirements.txt` + pytest; `python -m pytest -q` (TikTok simulado) |

Se dispara en push a `main`, `feat/**`, `fix/**`, en pull requests y a mano.

## Convenciones

- **Naming**: `test_<módulo>.py`, uno o más por módulo de `src/apps/<dominio>/`.
- **Markers** (declarados en `pyproject.toml`, `--strict-markers`):
  - `unit` → puro Python, sin I/O
  - `integration` → SQLite temporal + HTTP simulado
  - `e2e` → pipeline completo
  - `slow` → tarda > 2 s
  - `network` / `gpu` → opt-in; excluidos por defecto (`-m "not network and not gpu"`)
- **Fixtures**: en `conftest.py` si se comparten entre dominios; cada dominio nuevo tiene el suyo
  (`tests/<dominio>/conftest.py`).
- **HTTP simulado**: `responses` o fakes por monkeypatch del cliente (TikTok, YouTube, Groq).
- **Tiempo**: `freezegun`.
- **Sin GPU**: el ASR local, Ollama y Qwen3-TTS nunca corren en la suite.

## Defensas globales

`conftest.py` instala 2 fixtures autouse:
- `no_real_http` → bloquea HTTP real salvo en tests con `@pytest.mark.network`
- `clean_env` → borra API keys del entorno

## Cobertura objetivo

Ver [docs/agents/QA_AGENT.md § Métricas globales](../docs/agents/QA_AGENT.md).

| Dominio | Coverage objetivo |
|---|---|
| media, moments, supercut, publish, studio | sin objetivo fijado todavía (pendiente QA) |
| signals | ≥ 80% |
| production | ≥ 70% |
| scoring | ≥ 60% |
| analytics | ≥ 80% |
| total `src/` | ≥ 75% |
