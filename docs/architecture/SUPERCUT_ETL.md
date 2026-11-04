# Supercut ETL · de una película a una lección publicada

> Arquitectura del producto actual ("aprender empatía con el cine"). Fuente de verdad: el código en
> `src/apps/{media,moments,supercut,publish,studio}`; si este doc y el código divergen, gana el código.
> Contrato HTTP del estudio: [STUDIO_API.md](STUDIO_API.md). Tablas: [DATA_MODEL.md](DATA_MODEL.md).
> Última revisión: 2026-11-04.

## Vista general

```
media (Extract)          moments (Transform)                supercut (Load)             publish
───────────────          ───────────────────                ───────────────             ───────
search_all + derechos    candidatos ajustados a planos      plan (≤ 60 s)               TikTok: puente web/ → inbox
register_candidate       señales por película (8)           guion IA | plantilla        YouTube: privado / publishAt
probe → proxy            anclas Wikiquote / Wikipedia        voz edge-tts
audio + planos (1 pasada) etiquetas LLM validadas (top-K)    render 1080x1920, −14 LUFS
ASR por palabra          find entre obras (MMR)              revisión humana (estudio)
```

Todo corre en el PC del creador. Lo único en la nube es el sitio `web/` (Railway), que guarda el token
de TikTok y entrega `upload_url`s ([ADR 0005](DECISIONS/0005-railway-only-for-public-site.md)).
La IA es intercambiable entre local y API ([ADR 0007](DECISIONS/0007-swappable-local-api-ai.md)).

## 1. Media (Extract) · `src/apps/media`

| Paso | Módulo | Qué hace |
|---|---|---|
| Buscar | `sources.search_all` | Consulta `local` (`MOVIES_DIR`) e `archive_org`; por defecto solo devuelve derechos usables |
| Derechos | `archive_org.classify_rights`, `models.USABLE_RIGHTS` | `public_domain`, `open_license` y `owned` son usables; ante la duda, `unknown` (no usable) |
| Registrar | `indexer.register_candidate` | `works` + `media_assets` (master, proxy, derechos, licencia) |
| `probe` | `indexer` | Duración, resolución, fps, soporte de HTTP Range |
| `proxy` | `analysis.download_parallel` | Baja el derivado liviano del **mismo** master con N conexiones (6 por defecto), reanudable |
| `audio` + `shots` | `analysis.single_pass`, `shots.py` | Audio 16 kHz mono y cortes de plano (`scdet` o PySceneDetect) en una sola lectura; funde flashes < 400 ms |
| `asr` | `transcribe.py`, `integrations/ai/asr_api.py` | `ASR_BACKEND=auto`: local (faster-whisper `large-v3-turbo`, GPU) si hay CUDA; si no, Groq Whisper. Groq parte el audio en tramos de 10 min (MP3 48 kbps, 2 s de solape) por el límite de 25 MB |
| Clip | `fetch.extract_segment`, `cut_exact` | Rango HTTP con stream copy y caché; corte exacto al frame con una recodificación |

- `index_many` hace pipeline: la red baja el siguiente asset mientras la GPU/API transcribe el actual.
- Cada etapa deja su tiempo en `media_index_runs` (`ylk media runs`).
- Masters sin índice (MPEG-PS de DVD, `.mpg`, `.ts`, `.vob`) no permiten saltar por rango: se elige un
  derivado h.264 indexado del mismo original.
- `extract_segment_resilient` reintenta el master remoto (3 intentos) y cae al proxy si un nodo de
  Internet Archive responde 500.
- `utils/gpu_lock.py`: una etapa pesada de GPU a la vez entre procesos; el lock se libera solo si el PID
  dueño ya no existe.

### Almacenamiento (`storage.py`)

| Capa | Dónde | Vida |
|---|---|---|
| Crudo | `MOVIES_DIR` o Internet Archive | Permanente y **solo lectura** |
| DB | `DATA_DIR/shorts_pipeline.db` | Permanente (índice, momentos, recetas, publicaciones) |
| Segmentos | `media_cache/segments` | Caché LRU con tope `MEDIA_CACHE_MAX_GB` (5 por defecto) |
| Análisis | `media_cache/analysis/<id>` | Proxy y wav se borran tras transcribir y detectar; queda `loudness.npy` |
| Previews | `media_cache/previews` | Clips de 480 px de alto por momento; desechables |
| Trabajo | `media_cache/work/<job>` | Render efímero; se conserva solo si falla |
| Lecciones | `outputs/lessons/<id>.mp4` | El MP4 final de cada lección |

Lo que importa es la receta (`lesson_items`); cualquier MP4 se regenera desde la DB + el crudo.

## 2. Moments (Transform) · `src/apps/moments`

**Vocabulario controlado** (`data/vocab/` + `vocab.py`): 61 tropos, 13 beats, 13 emociones, 13 roles
y 32 temas. Una búsqueda se escribe `dimension:valor` (p. ej. `emotion:fear`, `trope:siege`).

`detect_moments(asset)`:

1. **Candidatos** (`scenes.py`): bloques de diálogo de 4–15 s ajustados a cortes de plano y a palabras,
   más picos de audio sin diálogo. Se descartan picos en créditos (primeros 90 s y último 3 %).
2. **Señales** (`features.py`): 8 señales normalizadas a 0-1 (`quote_anchor`, `plot_anchor`, `loudness`,
   `sudden_onset`, `shot_tempo`, `speech_intensity`, `climax_position`, `trope_cues`). El audio se mide
   con **percentiles de cada película** más un margen absoluto de 6 dB
   ([ADR 0008](DECISIONS/0008-per-film-audio-percentiles.md)).
3. **Anclas** (`anchors.py`): citas de Wikiquote alineadas con la transcripción y frases de la trama de
   Wikipedia (TF-IDF + programación dinámica monótona). La página se resuelve por **título exacto**
   (`Title (YEAR film)`, luego `Title (film)`, luego `Title`) y se acepta si el año aparece con ±2 de
   tolerancia; la búsqueda de texto completo queda de respaldo. Se guardan en `work_texts`; una
   respuesta vacía se vuelve a pedir tras 7 días.
4. **Importancia**: suma lineal con los pesos de `data/vocab/importance_weights.json`; las
   contribuciones quedan en `features_json` (el "por qué" que muestra el estudio).
5. Etiquetas débiles: léxicas (frases clave de tropos) y de posición (beat por posición).

`label_asset(asset, top_k=40, batch_size=6)`: el top-K por importancia (más lo anclado a una cita) va al
LLM en lotes. La salida se **sanea por ítem** (se descartan valores fuera del vocabulario) y se valida
contra el esquema; la importancia final mezcla señales y LLM (`llm_blend` = 0.4). Etiquetas con
`source = llm:<proveedor>`.

`find_moments(dimension, value)` (`retrieval.py`): puntaje = importancia × confianza; selección **MMR**
(misma obra = parecido 1, si no coseno TF-IDF del texto, `diversity` 0.35) para juntar obras distintas.
Solo derechos usables y nunca momentos `rejected`.

## 3. Supercut (Load) · `src/apps/supercut`

| Pieza | Módulo | Regla clave |
|---|---|---|
| Plan | `planner.py` | `find_moments(min_works=2, max_per_work=1)`; presupuesto = `max_duration_s` (58 por defecto) − 4 s de tarjeta final; tramos ≥ 2,5 s; reparto "water-filling" que conserva el inicio de cada momento; orden por año. Menos de 2 obras → `PlanError` (`409`) |
| Guion | `script.py` | LLM con esquema validado; títulos y años **solo** desde la DB (se rechaza una respuesta con un año ajeno). Sin LLM queda la plantilla y la API responde `502`. `script_source`: `llm:<proveedor>`, `template` o `manual` |
| Voz | `tts.py` | `TTS_BACKEND=edge` (por defecto, online y gratis): `es-MX-DaliaNeural`, `es-CO-SalomeNeural`, `en-US-AriaNeural`, con tiempos por palabra. `local` (Qwen3-TTS) **no** está implementado a propósito: requiere permiso para usar la GPU |
| Render | `render.py` | Por tramo, una recodificación: fondo desenfocado + toma completa, rótulo del tema, gancho en el primer tramo, texto en pantalla, lower-third "Título (año)", narración con ducking (`sidechaincompress`). Tarjeta final "Pausa. Respira lento." (4 s). Concat + `loudnorm` en dos pasadas a −14 LUFS + AAC + `faststart`. 1080x1920, 30 fps |
| Preview | `preview.py` | Clip de 480 px de alto por momento, en caché |
| Lecciones | `lessons.py` | CRUD + máquina de estados + issues + publicaciones |

Si la voz falla, el render falla: no se entrega un Short mudo sin avisar. Un render fallido devuelve la
lección a `draft`.

### Máquina de estados de `lessons.status`

```
draft ──render──► rendering ──ok──► rendered ──approve──► approved ──publish──► published
  ▲                   │
  └──── falla ────────┘

reject(reason):   rendered | approved            → rejected
editar:           rendered | approved | rejected → draft
render:           desde draft | rendered | approved | rejected
bloqueadas:       rendering y published no se editan ni se re-renderizan (409)
```

## 4. Revisión y publicación

- La revisión es humana, en la página **Revisión** del estudio: issues con rango de tiempo
  (`voice`, `caption`, `timing`, `image`, `rights`, `other`), aprobar, o rechazar con motivo.
- Publicar exige `approved` (o `published`, para la otra plataforma). Música: no se mezcla
  ([ADR 0006](DECISIONS/0006-no-mixed-music-drafts-60s.md)).
- TikTok: borrador al inbox vía el puente de `web/`, bytes directo del PC a TikTok. YouTube: OAuth de
  app instalada, privado por defecto, `publishAt` opcional. Detalle: [UPLOADS.md](../operations/UPLOADS.md).

## 5. Orquestación

- **CLI** (`ylk media …`, `ylk moments …`): cada paso por separado, útil para depurar.
- **Estudio** (`src/apps/studio/jobs.py`): cola en `studio_jobs` con **un solo worker** (los trabajos
  usan red o GPU y de a uno no compiten). Tipos: `index`, `detect`, `label`, `render`, `publish_tiktok`,
  `publish_youtube`. Al arrancar, lo que quedó `running` pasa a `error` y las lecciones `rendering`
  vuelven a `draft`. Progreso por `/ws`.

## Medido en la corrida real (2026-11-04, Groq)

| Qué | Resultado |
|---|---|
| Obras | *Night of the Living Dead* (1968), *Horror Express* (1972), *Grave of the Vampire* (1974), todas de dominio público en Internet Archive |
| Indexado completo de las 3 | 6,4 min en total; Groq Whisper transcribió 96 min de audio en 75 s |
| Momentos | 1206 candidatos, 199 etiquetados (Groq `openai/gpt-oss-120b`) |
| Anclas | NOTLD: 100 de 105 citas de Wikiquote alineadas; Horror Express: 17 de 19 |
| Búsqueda entre obras | Las 3 películas aparecen para `emotion:fear`, `emotion:dread`, `emotion:shock`, `trope:the_dead_return`, `trope:monster_reveal` |
| Primera lección | "El miedo antes del monstruo": 3 películas, 43,5 s, 1080x1920, −14,0 LUFS, con narración; render en 54 s; aprobada en el estudio |

Mediciones de la Fase 1 (rango HTTP, PSNR, descarga paralela): [MEDIA_AGENT.md](../agents/MEDIA_AGENT.md).
Problemas encontrados en esta corrida y su arreglo: [RUNBOOK.md](../operations/RUNBOOK.md).

## Pendiente

- precision@5 por tema sobre un set etiquetado a mano.
- F1 de cortes de plano con etiquetas humanas.
- TTS local (Qwen3-TTS) cuando el dueño autorice usar la GPU.
