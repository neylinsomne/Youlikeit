# YouTube Automatizacion - Ejercicios

Base de trabajo para practicar automatizacion de tareas de YouTube en Python.

## Objetivo

Este proyecto organiza ejercicios progresivos para:

- Navegacion automatizada (Playwright)
- Extraccion de metadata (yt-dlp)
- Monitoreo de canales (RSS)
- Uso de variables de entorno (.env)
- Manejo de datos y salidas por carpetas

## Estructura

- `src/exercises/ex01_search_and_open.py`: busqueda automatizada y captura de pantalla
- `src/exercises/ex02_video_metadata.py`: extrae metadata de un video
- `src/exercises/ex03_channel_rss_monitor.py`: revisa feed RSS de un canal
- `src/main.py`: lanzador de ejercicios
- `data/`: datos de entrada/salida para ejercicios
- `outputs/`: logs y capturas

## Requisitos

- Python 3.11+
- PowerShell

## Setup rapido (Windows)

```powershell
cd D:\Youlikeit\youtube-automatizacion-ejercicios
.\setup.ps1
```

## Setup recomendado (Docker)

Si tu Python local no esta disponible, usa este flujo:

```powershell
cd D:\Youlikeit\youtube-automatizacion-ejercicios
.\docker-setup.ps1
```

Despues ejecuta ejercicios con:

```powershell
.\run-exercise.ps1 -Exercise ex00
```

## Configuracion de entorno

1. Copia `.env.example` a `.env`
2. Ajusta variables segun tu caso

## Uso

```powershell
# Activa el entorno (si no lo tienes activo)
.\.venv\Scripts\Activate.ps1

# Lista ejercicios disponibles
python src\main.py --list

# Ejecuta ejercicio 1
python src\main.py ex01 --query "python automation"

# Ejecuta ejercicio 2
python src\main.py ex02 --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# Ejecuta ejercicio 3
python src\main.py ex03 --channel-id "UC_x5XG1OV2P6uZZ5FSM9Ttw"
```

### Flujo sugerido de ejercicios

1. `ex00` valida conexiones y llaves del `.env`
2. `ex01` prueba automatizacion browser (captura de pantalla)
3. `ex02` extrae metadata de un video
4. `ex03` monitorea publicaciones de canal por RSS
5. `ex04` descubre peliculas y frases para materia prima
6. `ex05` descarga subtitulos
7. `ex06` asigna timestamps a frases
8. `ex07` busca escenas por tematica
9. `ex09` rankea matches y sugiere grupos antes de edicion
10. `ex08` genera pack de crecimiento (hashtags + canciones TikTok + checklist)

## Ex08: Metadata de publicacion

Genera automaticamente:

- Hashtags sugeridos para YouTube Shorts
- Hashtags sugeridos para TikTok
- Candidatos de canciones trending de TikTok (fuente publica)
- Plantillas de titulo/caption y checklist de subida

Ejemplo:

```powershell
python src\main.py ex08 --query "villain monologue" --country-code CO --period-days 7
```

## Ex09: Curacion y agrupacion antes de editar

Muestra los mejores matches para una query y propone grupos de clips.

```powershell
python src\main.py ex09 --query "villain monologue" --max-results 20 --group-size 3
```

## Notas

- Usa esta base con fines educativos.
- Revisa los Terminos de Servicio de YouTube antes de automatizar flujos en produccion.

## YouTube vs TikTok: costos y acceso a metricas

### YouTube

- Para este proyecto puedes empezar gratis con YouTube Data API v3.
- Google da cuota diaria gratuita (normalmente 10,000 unidades por proyecto/dia).
- El costo aparece si superas cuota de forma recurrente y necesitas ampliacion para produccion.
- Para ejercicios de descubrimiento/metadata normalmente no deberias pagar.

### TikTok

- Cambiar a cuenta Business es gratis.
- Lo que cuesta en TikTok es pautar anuncios, no la cuenta empresarial en si.
- Para tendencias (hashtags/canciones), Creative Center suele ser la fuente mas practica.
- No siempre existe una API publica simple para todo el bloque de trends; depende de permisos y producto.

### Recomendacion para este repo

1. YouTube: usar API oficial para discovery/metadata.
2. TikTok: usar Creative Center para detectar trends y validar audio permitido para uso comercial.
3. Medir resultados con tus publicaciones y ajustar hashtags/audio por retencion.

Guia completa: ver [GUIA_APIS_YOUTUBE_TIKTOK.md](GUIA_APIS_YOUTUBE_TIKTOK.md).
Guia de edicion: ver [GUIA_EDICION_VIDEO.md](GUIA_EDICION_VIDEO.md).
Metodo DaVinci: ver [METODOLOGIA_EDICION_DAVINCI.md](METODOLOGIA_EDICION_DAVINCI.md).
Diagrama visual: ver [DIAGRAMA_FLUJO_EDICION.md](DIAGRAMA_FLUJO_EDICION.md).

## Automatizacion cada 3 dias

Scripts incluidos:

- `run-content-flow.ps1`: ejecuta pipeline ex00 -> ex08 en orden.
- `schedule-flow-every-3-days.ps1`: crea tarea programada en Windows cada 3 dias.
- `unschedule-flow.ps1`: elimina la tarea programada.

Guia operativa: ver [FLUJO_PUBLICACION_CADA_3_DIAS.md](FLUJO_PUBLICACION_CADA_3_DIAS.md).
