# MEDIA_AGENT · Dominio `apps.media` (Extract del ETL de supercuts)

## Scope

Conseguir video **con derechos usables** y dejarlo listo para entender momentos:
fuentes → índice de obras/assets → proxy de análisis → audio + cortes de plano →
transcripción con tiempos por palabra → extracción de regiones por rango HTTP.

Fuera de scope: `apps/content/movie_source.py` (Torrentio + qBittorrent) — no se
importa ni se extiende desde este dominio.

## Piezas

| Módulo | Qué hace |
|---|---|
| `sources.py` | Protocolo `SourceProvider` + `search_all` (filtra por derechos usables) |
| `archive_org.py` | Internet Archive: master = original indexado de mayor bitrate; proxy = derivado más liviano **del mismo master**; derechos por `licenseurl`; marca ítems DVD partidos (`partial`) |
| `local_library.py` | Biblioteca en `MOVIES_DIR` (E:), detecta S01E01 / 1x02, título desde carpeta de la serie; derechos `owned` |
| `analysis.py` | `download_parallel` (N conexiones, reanudable) + `single_pass` (audio 16 kHz + `scdet` en una lectura) |
| `transcribe.py` | ASR `local` (faster-whisper, GPU) o `groq` (API), `ASR_BACKEND=auto` |
| `shots.py` | Cortes de plano: PySceneDetect o ffmpeg `scdet`; funde flashes < 400 ms |
| `fetch.py` | `extract_segment` (stream copy por rango, timestamps originales, caché) + `cut_exact` (corte al frame, 1 recodificación) |
| `range_proxy.py` | Proxy local que cuenta bytes (verifica que solo baja el rango) |
| `indexer.py` | ETL: `prepare_asset` (red/CPU) → `asr_asset` (GPU/API); `index_many` en pipeline; tiempos en `media_index_runs` |
| `schema.py` | `works`, `media_assets`, `shots`, `transcript_segments`, `transcript_words`, `media_index_runs` |

## Almacenamiento (`storage.py`)

| Capa | Dónde | Vida |
|---|---|---|
| Crudo | `MOVIES_DIR` (o Internet Archive) | permanente, **solo lectura**: nunca se borra |
| DB | `shorts_pipeline.db` | permanente (índice, momentos, recetas, IDs de subida) |
| Segmentos | `media_cache/segments` | caché LRU con tope `MEDIA_CACHE_MAX_GB` (default 5) |
| Análisis | `media_cache/analysis/<id>` | proxy + wav se borran tras transcribir y detectar momentos; queda `loudness.npy` (~200 KB vs ~600 MB) |
| Trabajo | `media_cache/work/<job>` | render efímero: se borra al terminar bien, se conserva si falla |

Los Shorts se renderizan en disco (no en RAM): `+faststart` necesita un archivo con
seek y la subida debe poder reintentarse. Lo que se guarda es la receta (EDL), no el MP4.

## Comandos

```bash
ylk doctor                                     # keys/tokens/stack (sin mostrar valores)
ylk media ingest "Horror Express" --year 1973  # buscar + registrar + indexar
ylk media index-many --pending --asr-backend groq
ylk media runs                                 # segundos por etapa
ylk media fetch <asset> <start_ms> <end_ms> --measure --exact clip.mp4
ylk media storage                              # uso por capa
ylk media gc                                   # tope de segmentos + limpiar análisis ya usado
```

## Medido (2026-11-03, Internet Archive real)

| Qué | Resultado |
|---|---|
| Clip de 10 s de un master MKV de 11,5 GB | 41,7 MB bajados (**0,36 %** del archivo), 27 s con corte exacto |
| Corte exacto vs frame de referencia del master | PSNR = inf (mismo frame); el frame vecino da ~25 dB |
| Proxy 543 MB (6 conexiones) | 101 s (**5,4 MB/s**; 1 conexión ≈ 1,2–1,4 MB/s) |
| Audio + 730 cortes de plano (88 min) en una pasada | 11,6 s |

## Definition of Done (Fase 1)

- [x] Clip de 10 s < 5 % del archivo (`tests/media/test_live_archive.py`, marker `network`)
- [x] Corte exacto ±1 frame (mismo test)
- [ ] Cortes de plano F1 ≥ 0.9 sobre 10 min **etiquetados a mano** (pendiente: requiere etiquetas humanas)
- [ ] ASR real de una película completa (pendiente: `GROQ_API_KEY` o modelo local descargado)

## Verificación

```bash
python -m pytest tests/media -q                       # offline
python -m pytest tests/media -m network -v            # contra Internet Archive real
```
