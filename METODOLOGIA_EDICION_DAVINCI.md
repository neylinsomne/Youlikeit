# Metodologia de edicion para Shorts (DaVinci Resolve)

Esta guia convierte el output tecnico del pipeline (ex07/ex09/ex08) en una pieza final lista para publicar.

## 1. Objetivo editorial

- Duracion objetivo: 20 a 35 segundos
- Hook: primeros 2 segundos
- Estructura: 3 a 5 clips, cambio visual cada 1.5 a 3 segundos
- CTA final: 1 linea corta (seguir/comentar/parte 2)

## 2. Inputs del pipeline

Antes de editar, usa estos archivos:

- outputs/curation/ex09_curation_*.txt (ranking de mejores matches)
- outputs/curation/ex09_davinci_cutlist_*.csv (in/out por clip)
- outputs/metadata/ex08_growth_pack_*.json (hashtags/songs/caption)

## 3. Estructura recomendada de timeline

- 0.0s a 2.0s: Hook (frase fuerte + texto grande)
- 2.0s a 12.0s: Desarrollo (2 clips)
- 12.0s a 24.0s: Escalada emocional (1 o 2 clips)
- 24.0s a 30.0s: Cierre + CTA

## 4. Settings en DaVinci Resolve

- Timeline: 1080x1920 (vertical)
- FPS: 30 (o 24 si material original lo requiere)
- Audio loudness objetivo: -14 LUFS aprox
- Export: H.264, 10-16 Mbps, AAC 320 kbps

## 5. Metodo de seleccion de clips

1. Tomar Group 1 de ex09 (mejor avg_score)
2. Verificar que total este entre 18 y 35 segundos
3. Cambiar 1 clip si hay repeticion de tono/ritmo
4. Mantener diversidad de planos/peliculas

## 6. Metodo visual ("imagen" del short)

Direcciones recomendadas (elige una por serie):

- Cine oscuro: contraste alto, subtitulo blanco con borde negro
- Motivacional: tono calido, subtitulo amarillo/blanco
- Drama: leve desaturacion + grain suave

Reglas tipograficas:

- Maximo 2 lineas por subtitulo
- 36 a 54 px equivalente en 1080x1920
- Zona segura: no pegar texto al borde inferior

## 7. Flujo de audio

1. Voz/dialogo como pista principal
2. Musica de fondo al 12% a 22%
3. Ducking manual o por keyframes durante frases clave
4. Corte de musica al final para CTA claro

## 8. Control de calidad antes de exportar

Checklist:

- Hook se entiende sin contexto en 2 segundos
- Texto legible en movil
- No hay clips > 7 segundos sin cambio
- Transiciones no distraen del mensaje
- CTA final visible al menos 1.2 segundos

## 9. Repos/herramientas que ayudan

Para pre-edicion automatizada (antes de DaVinci):

- auto-editor (WyattBlue/auto-editor)
- PySceneDetect (Breakthrough/PySceneDetect)
- moviepy (Zulko/moviepy)
- ffmpeg (FFmpeg/FFmpeg)
- editly (mifi/editly)

Para DaVinci:

- Usar DaVinci Resolve Scripting API oficial (incluida con Resolve Studio)
- Buscar ejemplos comunitarios de "DaVinci Resolve scripting" para generar timelines desde CSV/JSON

## 10. Recomendacion operativa

- Etapa 1: ex09 te da ranking + grupos
- Etapa 2: montas en DaVinci con cutlist CSV
- Etapa 3: tomas metadata de ex08
- Etapa 4: publicas y comparas retencion por variante
