# 0007 · IA intercambiable: local o por API

- **Status:** accepted (acota el alcance de [0001](0001-why-algorithmic-not-llm.md) para el producto actual)
- **Date:** 2026-11-03 (documentada retroactivamente el 2026-11-04)
- **Deciders:** owner del repo

## Context and Problem Statement

El ETL de lecciones necesita transcripción con tiempos por palabra, etiquetas sobre un vocabulario y un
guion corto. Se puede correr local (RTX 5060, 8 GB) o con APIs gratis (Groq, Gemini). La GPU local es
una sola, no entran varios modelos a la vez, y el dueño pide permiso antes de correr modelos locales o
bajar pesos grandes.

## Decision Drivers

- Costo cero.
- Poder avanzar sin la GPU (o mientras está ocupada).
- Resultados verificables: el LLM no puede ser una fuente de hechos.

## Considered Options

1. Solo local.
2. Solo APIs.
3. **Capa intercambiable** con la misma interfaz para local y API, elegida por variables de entorno.

## Decision Outcome

Elegida la **opción 3**, en `src/integrations/ai/`:
- ASR: `ASR_BACKEND=auto|local|groq` (local = faster-whisper con CUDA; groq = Whisper por API en tramos
  de 10 min).
- LLM con salida JSON: `LLM_PROVIDER=auto|ollama|groq|gemini` o una lista en cascada (`auto` = ollama →
  groq → gemini). Groq por defecto `openai/gpt-oss-120b`.
- TTS: `TTS_BACKEND=edge` (online, gratis); `local` (Qwen3-TTS) queda sin implementar hasta tener
  permiso para usar la GPU.
- Toda salida del LLM se valida contra un esquema y el vocabulario, y se sanea por ítem. Los hechos del
  guion (títulos y años) salen solo de la DB.
- `utils/gpu_lock.py` serializa las etapas de GPU entre procesos.

### Consequences

**Buenas:**
- La corrida real usó solo Groq: 96 min de audio transcritos en 75 s, sin tocar la GPU.
- Cambiar de proveedor es una variable de entorno.

**Malas / trade-offs:**
- Límites por minuto de los planes gratis: reintentos con `Retry-After` y lotes pequeños.
- Los modelos de las APIs cambian (`llama-3.3-70b-versatile` fue retirado de Groq): el modelo es
  configurable con `GROQ_LLM_MODEL`.

## More Information

- [SUPERCUT_ETL.md](../SUPERCUT_ETL.md), [RUNBOOK.md § Incident 9](../../operations/RUNBOOK.md)
