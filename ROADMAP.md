# YouLikeIt · Roadmap

> Estado por fases del rework de supercuts ("aprender empatía con el cine"), rama
> `feat/supercut-media`. Última revisión: 2026-11-04.
> El roadmap anterior (manga, Fish Speech, personas) quedó obsoleto; su historia está en git.

## Resumen

| Fase | Qué | Estado |
|---|---|---|
| 0 | Higiene: secrets, deps base/GPU separadas, CI, esquema `cross_references` | ✅ Hecha |
| 1 | `apps/media`: fuentes con derechos, extracción por rango, audio + planos, ASR | ✅ Hecha (falta F1 de planos con etiquetas humanas) |
| 2 | `apps/moments`: vocabulario, señales, anclas, etiquetas LLM, búsqueda entre obras | ✅ Hecha (falta precision@5 sobre un set etiquetado a mano) |
| 3 | `apps/supercut`: plan, guion, voz, render, preview | ✅ Hecha (TTS local pendiente de permiso de GPU) |
| 4 | Estudio local + `apps/publish` + sitio `web/` en Railway | ✅ Código hecho · ⚠️ publicación real bloqueada por credenciales |

## Fase 0 · Higiene

- [x] `tokens/` y `.claude/settings.local.json` fuera de git; `data/shorts_pipeline.db` des-versionada.
- [x] `requirements.txt` (base, CI) y `requirements-gpu.txt` (pesado, incluye la base).
- [x] Tabla `cross_references` en `core/db.py`.
- [ ] Rotar la key de TMDB filtrada en el historial (acción del dueño).

## Fase 1 · Media (Extract)

- [x] Proveedores Internet Archive y biblioteca local con capa de derechos (`public_domain`,
  `open_license`, `owned`; el resto no se usa).
- [x] Extracción por rango HTTP: un clip de 10 s baja 0,36 % de un master de 11,5 GB.
- [x] Descarga paralela del proxy, audio + cortes de plano en una sola pasada.
- [x] ASR local (faster-whisper) o por API (Groq Whisper), con lock de GPU por PID.
- [x] Ciclo de vida del almacenamiento: crudo de solo lectura, caché de clips con tope, análisis desechable.
- [x] ASR real de películas completas: 96 min de audio en 75 s con Groq (corrida del 2026-11-04).
- [ ] Cortes de plano F1 ≥ 0.9 sobre 10 min etiquetados a mano.

## Fase 2 · Moments (Transform)

- [x] Vocabulario controlado en `data/vocab/` (61 tropos, 13 emociones, 13 beats, 13 roles, 32 temas).
- [x] Candidatos ajustados a planos; percentiles de audio por película.
- [x] Anclas Wikiquote/Wikipedia con resolución por título exacto.
- [x] Etiquetado LLM (Groq `openai/gpt-oss-120b`) validado y saneado por ítem.
- [x] Búsqueda entre obras con MMR (`ylk moments find`).
- [x] Corrida real: 3 películas, 1206 momentos, 199 etiquetados; `find` devuelve las 3 obras para
  `emotion:fear`, `emotion:dread`, `emotion:shock`, `trope:the_dead_return` y `trope:monster_reveal`.
- [ ] precision@5 por tema sobre ~50 momentos etiquetados a mano (5 obras).

## Fase 3 · Supercut (Load)

- [x] Planificador: una escena por obra, ≤ 60 s con tarjeta final, orden por año.
- [x] Guion con IA (hechos solo desde la DB) y plantilla de respaldo.
- [x] Narración con edge-tts y tiempos por palabra.
- [x] Render 1080x1920, fondo desenfocado, rótulos, ducking, −14 LUFS.
- [x] Primera lección real: "El miedo antes del monstruo" (3 películas, 43,5 s, render en 54 s, aprobada).
- [ ] TTS local (Qwen3-TTS): la interfaz existe; correrlo requiere permiso explícito para usar la GPU.

## Fase 4 · Estudio, publicación y sitio

- [x] API del estudio en 127.0.0.1 con token, guardia de origen y allowlist de archivos.
- [x] Front del estudio en español (Inicio, Biblioteca, Momentos, Editor, Revisión, Trabajos, Vocabulario).
- [x] Sitio `web/` en Railway con Login Kit, borrador a TikTok y puente para el estudio.
- [x] YouTube: OAuth de app instalada, tokens cifrados, subida privada con `publishAt`.
- [ ] Llaves del Sandbox de TikTok en Railway y conectar la cuenta en `/studio` (dueño).
- [ ] Revisión de la app de TikTok ([TIKTOK_APP_REVIEW.md](docs/operations/TIKTOK_APP_REVIEW.md)).
- [ ] YouTube: key nueva de Google, pantalla de consentimiento "En producción" y reconectar (dueño).
- [ ] Video del recorrido del estudio local (Playwright headless).

## Siguiente

- Más obras indexadas (meta: ≥ 5 por tema) para que el planificador tenga de dónde elegir.
- Medir la calidad de los momentos (precision@5) antes de automatizar más.
- Volver a conectar analítica del canal cuando haya publicaciones reales.

Ver también: [docs/CHANGELOG.md](docs/CHANGELOG.md) y [docs/architecture/SUPERCUT_ETL.md](docs/architecture/SUPERCUT_ETL.md).
