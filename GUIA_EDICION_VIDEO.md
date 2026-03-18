# Guia de agrupacion y edicion de video

Esta guia explica como pasar de candidatos (ex09) a una pieza final lista para publicar.

## 1. Que entrega ex09

ex09 produce:

- Ranking de mejores matches por query (score combinado)
- Grupos sugeridos de clips (con diversidad por pelicula)
- Reporte texto para revision humana
- Cutlist CSV para uso en editores

Archivos de salida:

- outputs/curation/ex09_curation_*.json
- outputs/curation/ex09_curation_*.txt
- outputs/curation/ex09_davinci_cutlist_*.csv

## 2. Como decidir que grupo editar

Criterios sugeridos:

1. Mejor avg_score del grupo
2. Duracion total entre 18s y 35s
3. Claridad narrativa (inicio fuerte + 1 cambio + cierre)
4. Variedad de peliculas/planos

## 3. DaVinci Resolve vs automatizacion

## Opcion A: DaVinci Resolve (recomendada para acabado)

Ventajas:

- Mejor control visual/sonoro
- Subtitulos y keyframes mas finos
- Color y dinamica profesional

Flujo:

1. Abrir proyecto vertical 1080x1920
2. Importar fuentes de video
3. Aplicar cutlist de ex09 como guia (in/out por clip)
4. Ajustar ritmo y transiciones
5. Exportar H.264/H.265 para Shorts

## Opcion B: FFmpeg/automatizado (rapido y repetible)

Ventajas:

- Repetible y barato
- Facil de programar por lote

Limites:

- Menos control creativo
- Ajustes visuales mas toscos

## Recomendacion practica

- Primera fase: usar ex09 + DaVinci para validar formato ganador.
- Segunda fase: automatizar solo el 80% repetible con FFmpeg y dejar 20% manual (hook/titulos/ajuste final).

## 4. Plantilla de flujo editorial

1. Query tematica (ex07)
2. Curacion/ranking y grupos (ex09)
3. Seleccion de grupo ganador
4. Edicion (DaVinci o FFmpeg)
5. Metadata final (ex08)
6. Publicacion y analitica

## 5. Objetivo de calidad por short

- Hook en 2 segundos
- 3 a 5 clips (4 a 7 segundos cada uno)
- Texto legible siempre
- Audio principal claro + musica de soporte
- CTA corto al final
