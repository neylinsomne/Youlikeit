# MOMENTS_AGENT · Dominio `apps.moments` (Transform del ETL de supercuts)

## Scope

Encontrar los momentos importantes de cada obra, clasificarlos con un vocabulario
controlado y recuperar momentos **equivalentes entre obras distintas** (la base de
un supercut temático). Entrada: lo que deja `apps.media` (transcripción por
palabra, planos, audio 16 kHz). Salida: tablas `moments` + `moment_labels`.

Principio: señales clásicas e interpretables primero (baratas, explicables); el
LLM solo etiqueta el top-K y su salida se valida contra el vocabulario.

## Piezas

| Módulo | Qué hace |
|---|---|
| `data/vocab/tropes.json` | 61 tropos con descripción propia es/en, frases clave y temas (TV Tropes solo como índice de nombres: es CC BY-NC-SA) |
| `data/vocab/taxonomy.json` | beats (con rango de posición), emociones unificadas, roles (arquetipos de Vogler) |
| `data/vocab/importance_weights.json` | pesos lineales de la importancia + mezcla con el LLM (los ajusta analytics) |
| `vocab.py` | carga, ids, frases clave → pistas de tropo, prior de beat por posición, `parse_spec("trope:x")` |
| `scenes.py` | candidatos: bloques de diálogo ajustados a cortes de plano (4–15 s) + picos de audio sin diálogo |
| `features.py` | `AudioProfile` (percentiles POR película), picos, 8 señales 0-1, importancia con contribuciones |
| `anchors.py` | Wikiquote (citas ↔ transcripción) y trama de Wikipedia (TF-IDF + DP monótona) |
| `labeling.py` | top-K → LLM en lotes con JSON schema del vocabulario → etiquetas `llm:<proveedor>` |
| `retrieval.py` | `find_moments(dim, valor)`: importancia × confianza, MMR entre obras, solo derechos usables |
| `pipeline.py` | `detect_moments` / `label_asset` (idempotente; respeta lo ya etiquetado) |

## Señales de importancia

| Señal | Qué mide |
|---|---|
| `quote_anchor` | la ventana contiene una cita de Wikiquote (respaldo externo fuerte) |
| `plot_anchor` | una frase de la trama de Wikipedia se alinea con esta zona |
| `loudness` | percentil de volumen dentro de la propia película (solo la mitad alta cuenta) |
| `sudden_onset` | subida brusca de volumen vs su p99.9 en la película (sustos, golpes, disparos) |
| `shot_tempo` | cortes por segundo (0.8/s = acción) |
| `speech_intensity` | palabras por segundo + exclamaciones |
| `climax_position` | cercanía al ~85 % de la obra |
| `trope_cues` | frases clave de tropos en el diálogo |

## Comandos

```bash
ylk moments vocab --dimension trope
ylk moments detect <asset>          # candidatos + señales + anclas
ylk moments label <asset> --provider groq
ylk moments show <asset> --top 15   # con "why" (contribuciones) y etiquetas
ylk moments find trope:the_dead_return --min-works 3
```

## Medido (2026-11-03)

- Anclas reales: *Night of the Living Dead* → 105 citas + 29 frases de trama;
  *Horror Express* → 19 citas + 24 frases (página correcta, no remakes ni sagas).
- Audio de cine real: MAD ≈ 9 dB por los silencios → un z-score global no detecta
  picos (máx z ≈ 1.8). Por eso los umbrales son percentiles por película + margen
  absoluto de 6 dB.
- Sin transcripción (solo audio + planos): 40 candidatos por película; los mejores
  caen en los clímax (NOTLD 1:09–1:26, asedio final; Horror Express 1:11–1:13).
  Se descartan picos en créditos (primeros 90 s y último 3 %).

## Definition of Done (Fase 2)

- [x] Vocabulario controlado + validación de salida del LLM
- [x] Candidatos ajustados a planos y palabras; anclas Wikiquote/trama
- [x] Importancia lineal explicable; recuperación MMR entre obras con capa de derechos
- [x] Etiquetado real con LLM (2026-11-04, Groq `openai/gpt-oss-120b`): 1206 momentos, 199 etiquetados
  en 3 películas; valores fuera del vocabulario se sanean por ítem
- [x] Transcripción real con anclas: NOTLD 100/105 citas alineadas, Horror Express 17/19; `find` devuelve
  las 3 obras para `emotion:fear|dread|shock` y `trope:the_dead_return|monster_reveal`
- [x] Arreglos de la corrida real: títulos exactos en Wikiquote/Wikipedia, ±2 años entre fuentes, caché
  de anclas vacías que vence a los 7 días (`tests/moments/test_real_run_regressions.py`)
- [ ] precisión@5 por tema sobre un set etiquetado a mano (~50 momentos, 5 obras)

## Verificación

```bash
python -m pytest tests/moments -q
```
