# Propuesta de actualización del MANIFIESTO (para el owner)

> El `MANIFIESTO.md` es del owner: el Docs Agent no lo edita. Esta es solo una **propuesta** para
> alinearlo con el producto actual (2026-11-04). Aceptar, cambiar o descartar.

## Qué ya no coincide con el código

| Sección del MANIFIESTO | Hoy en el repo |
|---|---|
| "Narración reflexiva (ex18)" / "Fish Audio S1-Mini" | Narración con edge-tts; TTS local previsto: Qwen3-TTS (Fish Speech tiene licencia no comercial) |
| "Descubrimiento … TMDB + Wikiquote + OpenSubtitles" | Internet Archive + biblioteca propia; transcripción por ASR; Wikiquote/Wikipedia como anclas |
| "Clasificación … LLM + ChromaDB" | Vocabulario controlado (61 tropos, 13 emociones…) + LLM validado; sin ChromaDB |
| "Edición de video (FFmpeg / Shotcut / DaVinci)" | Render automático con FFmpeg (1080x1920, −14 LUFS) + revisión humana en el estudio local |
| "Estrategia de publicación (hashtags, canciones, horarios)" | La música no se mezcla: se elige en TikTok/YouTube; TikTok como borrador |
| "Todo local" | Todo local salvo el sitio público mínimo en Railway (requisito de TikTok) |
| "Pulp Fiction al lado de Parasite" | Solo material de dominio público, licencia abierta o copias propias |

## Texto propuesto (borrador)

**La idea.** Aprender empatía con el cine. Cada lección junta, en menos de un minuto, escenas de
películas distintas donde aparece la misma emoción o la misma situación, y ayuda a nombrar lo que se
siente y a notarlo en el cuerpo, sin juicios.

**Principios nuevos (se suman a los existentes):**
1. **Solo material legítimo.** Dominio público, licencia abierta o copias propias; cada escena se puede
   justificar.
2. **El humano decide.** La máquina propone momentos y arma el borrador; una persona revisa, aprueba y
   publica.
3. **La IA no inventa hechos.** Títulos y años salen de la base de datos; el LLM solo clasifica y redacta.
4. **La música la elige quien publica**, dentro de la plataforma.
5. **Costo cero** sigue siendo la regla: APIs gratis o modelos locales, intercambiables.

**Stack técnico (reemplazo de la sección):** ETL media → moments → supercut → publish; estudio local en
127.0.0.1; sitio público mínimo en Railway para TikTok. Detalle en
[docs/architecture/SUPERCUT_ETL.md](../architecture/SUPERCUT_ETL.md).
