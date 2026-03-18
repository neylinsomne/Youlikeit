import os
from pathlib import Path

from common.config import Settings


def _mask(value: str) -> str:
    if not value:
        return "(vacio)"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "..." + value[-4:]


def run(settings: Settings) -> Path:
    report_path = settings.output_dir / "logs" / "ex00_connections_report.txt"

    keys = {
        "YOUTUBE_API_KEY": os.getenv("YOUTUBE_API_KEY", ""),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "FISH_API_KEY": os.getenv("FISH_API_KEY", ""),
        "PEXELS_API_KEY": os.getenv("PEXELS_API_KEY", ""),
        "TMDB_API_KEY": os.getenv("TMDB_API_KEY", ""),
        "OPENSUBTITLES_API_KEY": os.getenv("OPENSUBTITLES_API_KEY", ""),
        "SUBDL_API_KEY": os.getenv("SUBDL_API_KEY", ""),
    }

    lines = ["Connection check report", "======================", ""]
    for name, value in keys.items():
        status = "OK" if value else "MISSING"
        lines.append(f"{name}: {status} | {_mask(value)}")

    lines.append("")
    lines.append("Notas:")
    lines.append("- Este chequeo valida presencia de variables, no consumo de cuota/API.")
    lines.append("- Guarda tus claves en .env y nunca las subas al repositorio.")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
