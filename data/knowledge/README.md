# Knowledge Base

Base de conocimiento que crece con el tiempo. Cada archivo es un aprendizaje
validado por datos o por revisión manual.

## Estructura

```
knowledge/
  insights/         ← Patrones descubiertos por analytics/agents
  rules/            ← Reglas confirmadas por A/B testing
  mistakes/         ← Errores documentados para no repetir
  audience/         ← Lo que sabemos de la audiencia
  cinema/           ← Conocimiento de cine (épocas, directores, tendencias)
```

## Formato de cada archivo

```yaml
---
title: Los hashtags de emoción generan 2.3x más engagement
category: insight
topic: hashtags
confidence: 0.82
source: ab_test #14
validated: 3
contradicted: 0
---

Los hashtags que describen emociones (#anger, #sadness, #epic) generan
en promedio 2.3x más engagement que los hashtags de género (#action,
#drama, #thriller).

Esto se validó en 3 ciclos de A/B testing con un p-value de 0.02.

Aplicar en: ex08 (priorizar hashtags de emoción), ex17 (estrategia).
```

## Quién escribe

- **claude:analyst** - insights de ex19/ex20/ex21
- **claude:ab_tester** - reglas confirmadas por A/B tests
- **claude:reviewer** - patrones de los reviews en ex15
- **admin** - conocimiento manual y correcciones

## Cómo se usa

ex09, ex17, y ex21 leen la knowledge base para tomar decisiones.
Si un insight tiene confidence > 0.7 y validated > contradicted,
se aplica automáticamente. Si no, se sugiere pero no se impone.
