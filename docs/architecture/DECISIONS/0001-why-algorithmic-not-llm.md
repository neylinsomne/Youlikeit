# 0001 · Generación algorítmica, no LLM, en el camino crítico

- **Status:** accepted
- **Date:** 2026-06-02 (decisión tomada antes; documentada retroactivamente)
- **Deciders:** owner del repo
- **Fuente original:** [MLOPS_FLOW.md § Decisiones de diseño 1](../MLOPS_FLOW.md)

> **Alcance (2026-11-04).** Esta decisión aplica al generador de guiones del producto anterior
> (shorts por persona con A/B de tono). El ETL de lecciones **sí** usa LLM, pero acotado: etiquetar el
> top-K de momentos contra un vocabulario cerrado y redactar el guion, siempre con salida validada,
> hechos solo desde la DB y una plantilla de respaldo que permite renderizar sin LLM. Ver
> [0007](0007-swappable-local-api-ai.md).

## Context and Problem Statement

El generador de scripts (`algorithmic_script_generator.py` / `script_generator.py`)
produce la narración de cada short. La pregunta es si usar un LLM para generar
el guion completo o reglas algorítmicas con plantillas JSON.

El sistema corre A/B tests donde la variable a medir es el **tono**
(`treatment_tones`). Si el guion lo genera un LLM, cada corrida es distinta y la
"lotería" del modelo se vuelve una variable de confusión.

## Decision Drivers

- Reproducibilidad: misma serie + persona + tono ⇒ mismo guion.
- Costo: el objetivo es costo cercano a cero (proyecto zero-cost).
- Limpieza experimental: aislar el tono como única variable del A/B.
- Cero dependencia de disponibilidad/latencia de un proveedor LLM en el camino crítico.

## Considered Options

1. **LLM genera el guion completo** (p.ej. Gemini/GPT por short).
2. **Algorítmico**: plantillas JSON + reglas CPS + RNG sembrado por serie.
3. Híbrido: algorítmico con "relleno" LLM opcional detrás de feature flag.

## Decision Outcome

Elegida la **opción 2 (algorítmico)**. El LLM se usa **solo** para
`suggested_angle` (1 frase) en los briefs — costo ~$0.0001/llamada con Gemini
2.0 Flash, fuera del camino crítico del render.

### Consequences

**Buenas:**
- Reproducibilidad total → A/B tests limpios sobre el tono.
- Costo ~$0 en el render.
- Sin acoplamiento a la disponibilidad de un proveedor.

**Malas / trade-offs:**
- Menor diversidad léxica. Se compensa rotando plantillas JSON con `seeded_extra`.
- El flag `--use-llm=True` en `script_generator.py` quedó como **dead path
  legacy**; si en 3 meses nadie lo usa, eliminarlo (ver anti-patrón "dead
  experimental code paths" en MLOPS_FLOW).

## More Information

- Próximo paso relacionado: bandit Thompson sobre `treatment_tones` cuando haya
  N≥50 videos por persona × tono (ver [0003](0003-why-fixed-catalog.md) y MLOPS_FLOW § Roadmap).
