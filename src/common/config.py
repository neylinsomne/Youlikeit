from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass
class Settings:
    headless: bool
    timeout_ms: int
    output_dir: Path
    data_dir: Path


def _to_bool(value: str, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    load_dotenv()

    headless = _to_bool(os.getenv("HEADLESS", "true"), default=True)
    timeout_ms = int(os.getenv("TIMEOUT_MS", "20000"))
    output_dir = Path(os.getenv("OUTPUT_DIR", "outputs"))
    data_dir = Path(os.getenv("DATA_DIR", "data"))

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)
    (data_dir / "raw").mkdir(parents=True, exist_ok=True)
    (data_dir / "processed").mkdir(parents=True, exist_ok=True)

    return Settings(
        headless=headless,
        timeout_ms=timeout_ms,
        output_dir=output_dir,
        data_dir=data_dir,
    )
