"""Publicación de lecciones aprobadas.

    tiktok_bridge  borrador al inbox de TikTok vía el puente de web/ (Railway):
                   el token de TikTok nunca sale de Railway y el video nunca se
                   guarda allá (el estudio hace el PUT directo a TikTok).
    youtube        OAuth de app instalada desde el estudio, tokens cifrados con
                   Fernet, subida resumible privada con publishAt.
    service        publish_lesson: requiere `approved`, registra `publications`.
"""
