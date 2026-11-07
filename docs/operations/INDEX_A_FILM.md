# Runbook · De una película a una lección publicada

> Paso a paso real (probado el 2026-11-04 con *Night of the Living Dead*, *Horror Express* y
> *Grave of the Vampire*). Dos caminos equivalentes: **CLI** (`ylk`) o **estudio** (UI en
> `http://127.0.0.1:5180`). Arquitectura: [SUPERCUT_ETL.md](../architecture/SUPERCUT_ETL.md).

## 0. Antes de empezar

```powershell
ylk doctor                          # Groq, ffmpeg, MOVIES_DIR, faster-whisper + CUDA… (sin mostrar valores)
.\scripts\ops\studio.ps1 -Check     # requisitos del estudio (si vas a usar la UI)
```

- ASR: con `GROQ_API_KEY` usa `--asr-backend groq` (no usa la GPU). El backend local
  (`faster-whisper`) baja el modelo `large-v3-turbo` (~1,6 GB) la primera vez y usa la GPU:
  **pide permiso al dueño antes de correrlo**.
- LLM para etiquetar: `--provider groq` (Groq `openai/gpt-oss-120b`).
- Solo se registran obras con derechos usables (`public_domain`, `open_license`, `owned`).

## 1. Buscar y registrar la obra

**CLI**

```powershell
ylk media search "Night of the Living Dead" --year 1968            # candidatos con derechos usables
ylk media add archive_org Night.Of.The.Living.Dead_1080p --title "Night of the Living Dead" --year 1968
ylk media assets                                                    # id del asset y estado
```

Atajo de un comando (busca, registra la mejor copia no partida e indexa):
`ylk media ingest "Horror Express" --year 1972 --asr-backend groq`.

Biblioteca local: `ylk media scan` registra todo `MOVIES_DIR` con derechos `owned`
(nombres como `<MOVIES_DIR>/Horror Express (1972)/Horror Express (1972).mkv`).

**Estudio**: **Biblioteca** → buscar (Internet Archive o local) → **Registrar** en una copia usable.
Las copias con derechos dudosos se ven pero no se pueden registrar (`409`).

## 2. Indexar (probe → proxy → audio + planos → ASR)

**CLI**

```powershell
ylk media index 1 --asr-backend groq                 # un asset
ylk media index-many --pending --asr-backend groq    # todos los que falten (pipeline red/GPU)
ylk media runs                                       # segundos por etapa
```

**Estudio**: Biblioteca → asset → **Indexar** (job `index`). El progreso se ve en vivo en **Trabajos**
y en la tarjeta del asset (`probe`, `proxy`, `analyze`, `asr`, `shots`).

Referencia: indexar las 3 películas de la corrida real tomó 6,4 min en total con Groq.

## 3. Detectar y etiquetar momentos

**CLI**

```powershell
ylk moments detect 1                   # candidatos + señales + anclas Wikiquote/Wikipedia
ylk moments label 1 --provider groq    # top-40 al LLM, en lotes de 6
ylk moments show 1 --top 15            # importancia, "por qué" y etiquetas
# o los dos pasos juntos:
ylk moments run 1 --provider groq
```

**Estudio**: Biblioteca → **Detectar** (job `detect`) → **Etiquetar** (job `label`). En **Momentos**:
filtrar por emoción, tropo u obra, ver el preview, leer el "por qué", rechazar o etiquetar a mano.

Comprobar que la obra aporta a la búsqueda entre obras:

```powershell
ylk moments find emotion:fear --min-works 3
ylk moments find trope:the_dead_return --min-works 3 --min-confidence 0.25   # incluye etiquetas léxicas
```

## 4. Armar la lección

Necesita al menos **2 obras** con el tema pedido (si no, `409`). No hay comando CLI para lecciones:
se arman desde el estudio (o con la API, ver [STUDIO_API.md](../architecture/STUDIO_API.md)).

**Estudio** → **Editor**:

1. **Nueva lección por tema** → elegir el tema (`emotion:fear`, `trope:monster_reveal`…) → **Armar**: el planificador elige una escena por
   obra, recorta para que quepa en ≤ 60 s con la tarjeta final y ordena por año.
2. Ajustar el orden (arrastrar), los recortes `mm:ss.s` y el texto en pantalla de cada tramo.
3. **Guion**: **Generar con IA** (gancho, narración por tramo, cierre) o escribirlo a mano. Si no hay LLM
   queda la plantilla.
4. **Guardar** y **Renderizar** (con o sin narración). El progreso sale en vivo; el MP4 queda en
   `outputs/lessons/<id>.mp4`.

Referencia: "El miedo antes del monstruo" (3 películas, 43,5 s, 1080x1920, −14,0 LUFS, con narración)
se renderizó en 54 s.

## 5. Revisar

**Estudio** → **Revisión**: ver el video 9:16, marcar issues con rango de tiempo ("Ahora" toma el
tiempo actual del video) y **Aprobar**, o **Rechazar** con motivo. Editar una lección aprobada o
rechazada la devuelve a borrador (hay que volver a renderizar y aprobar).

Chequeo técnico opcional del archivo:

```powershell
ffprobe -v error -show_entries stream=width,height -show_entries format=duration outputs/lessons/1.mp4
ffmpeg -i outputs/lessons/1.mp4 -af ebur128 -f null - 2>&1 | Select-String "I:"   # ≈ -14 LUFS
```

## 6. Publicar

Lección aprobada → **Enviar a TikTok como borrador** (elegir cuenta) y/o **Subir a YouTube** (privado,
fecha opcional). Requisitos y errores: [UPLOADS.md](UPLOADS.md).

## 7. Liberar espacio

```powershell
ylk media storage      # uso por capa
ylk media gc           # recorta la caché de segmentos y borra proxy + wav ya aprovechados
```

El crudo (`MOVIES_DIR`) nunca se borra.

## Si algo falla

Ver [RUNBOOK.md](RUNBOOK.md) § incidentes del ETL (Wikiquote, años, IA 500, MPEG-PS, Groq 429/400,
GPU lock, jobs colgados).
