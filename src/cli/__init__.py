"""YouLikeIt CLI (`ylk`). Front-door unificado del pipeline.

Cada dominio registra sus subcomandos en cli/commands/<dominio>.py.
Agregar funcionalidad = agregar un comando ahí (o un módulo nuevo + add_typer
en cli/main.py), no un script suelto.
"""
