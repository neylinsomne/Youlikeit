"""Dominio supercut: lecciones (recetas de supercut entre obras) → guion → voz → render 9:16.

    planner   find_moments → EDL (lesson + lesson_items), ordenado por año
    script    narración y textos con llm_json (hechos SOLO desde la DB) o plantilla
    tts       edge-tts con tiempos por palabra (interfaz lista para un backend local)
    render    1080x1920 con fondo desenfocado, rótulos, ducking, -14 LUFS, tarjeta de pausa
    preview   clip corto de 480 px de alto por momento (caché)
    lessons   CRUD + máquina de estados + issues + publicaciones
"""
