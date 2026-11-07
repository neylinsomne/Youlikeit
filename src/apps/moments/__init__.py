"""Dominio moments — Transform del ETL de supercuts.

Transcripción + planos (apps.media) → candidatos de momento ajustados a cortes
→ señales interpretables (audio, ritmo, posición, frases clave) + anclas
externas (Wikiquote, trama de Wikipedia) → importancia lineal → etiquetado
con vocabulario controlado (LLM local/API o heurística) → recuperación de
momentos equivalentes ENTRE obras para un tema/tropo.
"""
