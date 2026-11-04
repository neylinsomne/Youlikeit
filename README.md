# YouLikeIt

**Aprender empatía con el cine.** YouLikeIt encuentra los momentos clave de películas de dominio
público o con licencia (Internet Archive y la biblioteca local `MOVIES_DIR`), los clasifica con un
vocabulario controlado (61 tropos, 13 emociones, beats, roles y temas) y arma **lecciones verticales
cortas (≤ 60 s)** con escenas de **obras distintas**, con texto en pantalla y narración opcional.
Cada lección se revisa a mano y se publica: en TikTok como **borrador** y en YouTube como video privado.

- La música **no se mezcla**: se elige dentro de TikTok o YouTube.
- Solo fuentes legítimas. El conector Torrentio/qBittorrent (`src/apps/content/movie_source.py`) queda
  congelado y los dominios nuevos no lo usan ([ADR 0004](docs/architecture/DECISIONS/0004-legit-sources-only.md)).

## Dos superficies

| Superficie | Dónde corre | Para qué |
|---|---|---|
| **Sitio público** `web/` | Railway: <https://youlikeit-web-production.up.railway.app> | Explorar películas por emoción, términos y privacidad, TikTok Login Kit (`user.info.basic` + `video.upload`), "Send to TikTok as draft", archivos de verificación de URL y el **puente** `/api/studio/*` que usa el estudio. Ver [web/README.md](web/README.md). |
| **Estudio local** | Tu PC, solo `127.0.0.1` | API `src/apps/studio` en `:8001` (`ylk studio`, Bearer `STUDIO_TOKEN`) y front `frontend-react` (Vite) en `:5180`. Biblioteca, momentos, editor de lecciones, render, revisión y publicación. Ver [STUDIO_API.md](docs/architecture/STUDIO_API.md) y [frontend-react/README.md](frontend-react/README.md). |

El video nunca pasa por Railway: el estudio pide al puente un `upload_url` y sube los bytes directo
de tu PC a TikTok. El token de TikTok nunca sale de Railway.

## El ETL, en una línea

```
media (fuentes con derechos → rango HTTP → audio + planos → ASR por palabra)
  → moments (candidatos ajustados a planos → señales por película → anclas Wikiquote/Wikipedia
             → etiquetas LLM validadas contra el vocabulario → búsqueda entre obras con MMR)
  → supercut (plan ≤ 60 s → guion IA o plantilla → voz edge-tts → render 1080x1920, −14 LUFS)
  → revisión humana en el estudio
  → publish (TikTok borrador vía puente · YouTube privado con publishAt opcional)
```

Detalle por etapa: [docs/architecture/SUPERCUT_ETL.md](docs/architecture/SUPERCUT_ETL.md).

## Inicio rápido (Windows, PowerShell)

```powershell
python -m pip install -r requirements.txt        # base: estudio, ETL por API (Groq), tests
python -m pip install -r requirements-gpu.txt    # opcional: ASR local (faster-whisper), OCR, PySceneDetect
python -m pip install -r requirements-dev.txt    # pytest y herramientas de desarrollo
python -m pip install -e .                       # instala el paquete y el CLI `ylk`

if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # y llena las keys (SETUP_CUENTAS.md)
ylk doctor                                       # estado de keys, tokens y stack, sin mostrar valores

.\scripts\ops\studio.ps1                         # API + front en 127.0.0.1 y abre http://127.0.0.1:5180
```

`studio.ps1` revisa los requisitos (ylk, Node.js, ffmpeg, `STUDIO_TOKEN` en `.env`, puertos libres),
corre `npm install` la primera vez y arranca todo. `-Check` solo revisa y `-Stop` lo apaga.

Indexar una película de punta a punta (CLI o UI): [docs/operations/INDEX_A_FILM.md](docs/operations/INDEX_A_FILM.md).

## Por dónde empezar

| Si vas a... | Lee |
|---|---|
| Entender el ETL de lecciones | [docs/architecture/SUPERCUT_ETL.md](docs/architecture/SUPERCUT_ETL.md) |
| Ver el índice de la documentación | [docs/README.md](docs/README.md) |
| Configurar cuentas y keys | [SETUP_CUENTAS.md](SETUP_CUENTAS.md) |
| Publicar en TikTok o YouTube | [docs/operations/UPLOADS.md](docs/operations/UPLOADS.md) |
| Operar o resolver un incidente | [docs/operations/RUNBOOK.md](docs/operations/RUNBOOK.md) |
| Secrets y modelo de amenazas | [docs/operations/SECURITY.md](docs/operations/SECURITY.md) |
| Ver el estado por fases | [ROADMAP.md](ROADMAP.md) |
| Conocer la misión y la voz del canal | [MANIFIESTO.md](MANIFIESTO.md) |

## Estructura del repo

```
src/
├── core/          config + db (SQLite WAL, esquema completo en get_db)
├── utils/         logger, ffmpeg, websocket_hub, gpu_lock
├── apps/
│   ├── media/     Extract: fuentes, rangos HTTP, audio + planos, ASR, almacenamiento
│   ├── moments/   Transform: candidatos, señales, anclas, etiquetas, búsqueda entre obras
│   ├── supercut/  Load: plan, guion, voz, render y preview de lecciones
│   ├── publish/   TikTok (puente de web/) y YouTube (OAuth de app instalada)
│   ├── studio/    API FastAPI del estudio local + cola de jobs
│   └── signals/ production/ scoring/ analytics/ content/   producto anterior (personas)
├── integrations/  ai/ (ASR + LLM intercambiables), credentials_check (ylk doctor), clientes externos
└── cli/           `ylk` (media, moments, studio, doctor, signals, analytics, …)
web/               sitio público (FastAPI + Jinja) desplegado en Railway
frontend-react/    UI del estudio local (Vite + React, en español)
data/vocab/        vocabulario controlado (tropos, taxonomía, pesos de importancia)
scripts/ops/       studio.ps1 y demás .ps1 de operación
scripts/web/       export_catalog.py y make_demo_lesson.py (contenido del sitio)
scripts/legacy/    ejercicios ex00–ex40, incluidos ex15/ex28/ex29 (solo referencia)
tests/<dominio>/   pytest por dominio; web/tests corre en el job "web" de CI
docs/              documentación (entrar por docs/README.md)
```

## Producto anterior (legacy)

Los dominios `signals`, `production`, `scoring` y `analytics` (shorts multi-persona sobre manga y
anime) siguen en el repo y con tests, pero no son el foco. La API ex29 y su contenedor se retiraron de
`docker-compose.yml` por inseguros (token admin sin contraseña y `/api/files` servía `.env`). ex15,
ex28 y ex29 quedan solo en `scripts/legacy/`.

## Notas

- Uso educativo. Solo material de dominio público, con licencia abierta o copias propias.
- Las métricas son solo las del canal propio.
