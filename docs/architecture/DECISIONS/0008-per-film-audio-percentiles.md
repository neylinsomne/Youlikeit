# 0008 · Señales de audio con percentiles por película

- **Status:** accepted
- **Date:** 2026-11-03 (documentada retroactivamente el 2026-11-04)
- **Deciders:** owner del repo + agente de desarrollo

## Context and Problem Statement

Dos señales de importancia de un momento vienen del audio: volumen (`loudness`) y subidas bruscas
(`sudden_onset`: sustos, golpes, disparos). Hace falta un umbral para decidir qué es "fuerte" o
"brusco" en películas con mezclas muy distintas.

## Decision Drivers

- Las mezclas de cine varían entre películas y décadas.
- Medido en cine real: la desviación absoluta mediana del volumen es ≈ 9 dB por los silencios, así que
  un z-score global casi no detecta picos (máximo z ≈ 1,8).
- Las señales tienen que ser interpretables (se muestran como "por qué").

## Considered Options

1. Umbrales absolutos en dB para todas las películas.
2. z-score global por película.
3. **Percentiles de cada película + un margen absoluto mínimo.**

## Decision Outcome

Elegida la **opción 3** (`AudioProfile` en `src/apps/moments/features.py`): el volumen se compara con
la distribución de la propia película y las subidas con su p99.9, y además se exige un margen absoluto
de 6 dB (sobre la mediana o como subida). Así, en una mezcla plana el "1 % más fuerte" no se cuenta como
pico. Se descartan picos en créditos (primeros 90 s y último 3 %).

### Consequences

**Buenas:**
- Funciona igual en mezclas de los 60 y de los 2000; los mejores candidatos sin diálogo caen en los
  clímax (medido en *Night of the Living Dead* y *Horror Express*).
- Cada señal se guarda normalizada a 0-1 con su contribución a la importancia.

**Malas / trade-offs:**
- "Fuerte" es relativo: una película entera muy ruidosa no gana puntos frente a otra tranquila.
- Hace falta el audio completo para calcular los percentiles (se conserva `loudness.npy`, ~200 KB).

## More Information

- [MOMENTS_AGENT.md § Medido](../../agents/MOMENTS_AGENT.md)
- [SUPERCUT_ETL.md § Moments](../SUPERCUT_ETL.md#2-moments-transform--srcappsmoments)
