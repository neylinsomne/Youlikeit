# Diagrama de flujo de edicion (Shorts)

```mermaid
flowchart TD
    A[ex04 Descubrir peliculas/frases] --> B[ex05 Descargar subtitulos]
    B --> C[ex06 Matching frases y timestamps]
    C --> D[ex07 Buscar escenas por query]
    D --> E[ex09 Curar y rankear matches]
    E --> F{Elegir grupo ganador}
    F --> G[DaVinci: montaje vertical 1080x1920]
    G --> H[Audio mix + subtitulos]
    H --> I[QC final]
    I --> J[ex08 Metadata y hashtags]
    J --> K[Publicar YouTube/TikTok]
    K --> L[Medir retencion y feedback]
    L --> D
```

## Lectura rapida

- ex09 es el filtro clave antes de editar: evita cortar material mediocre.
- ex08 se usa al final para publicar con contexto de tendencia.
- El loop vuelve a ex07 para mejorar la siguiente tanda.
