from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass
class Settings:
    headless: bool
    timeout_ms: int
    output_dir: Path
    data_dir: Path
    # Remote PC / Wireguard settings
    remote_host: str = ""
    remote_user: str = ""
    remote_ssh_port: int = 22
    remote_movies_dir: str = "/home/movies"
    remote_qbit_port: int = 8090
    local_movies_dir: str = "E:/movies"
    wireguard_enabled: bool = False
    # Proxy settings
    scrape_proxy_enabled: bool = False
    scrape_proxy_port: int = 1080
    scrape_proxy_type: str = "socks5"


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
        # Remote PC
        remote_host=os.getenv("REMOTE_HOST", ""),
        remote_user=os.getenv("REMOTE_USER", ""),
        remote_ssh_port=int(os.getenv("REMOTE_SSH_PORT", "22")),
        remote_movies_dir=os.getenv("REMOTE_MOVIES_DIR", "/home/movies"),
        remote_qbit_port=int(os.getenv("REMOTE_QBIT_PORT", "8090")),
        # MOVIES_DIR es el nombre que usan movie_source/ex11; LOCAL_MOVIES_DIR se
        # mantiene como alias por compatibilidad con .env viejos.
        local_movies_dir=os.getenv("MOVIES_DIR") or os.getenv("LOCAL_MOVIES_DIR", "E:/movies"),
        wireguard_enabled=_to_bool(os.getenv("WIREGUARD_ENABLED", "false"), default=False),
        # Proxy
        scrape_proxy_enabled=_to_bool(os.getenv("SCRAPE_PROXY_ENABLED", "false"), default=False),
        scrape_proxy_port=int(os.getenv("SCRAPE_PROXY_PORT", "1080")),
        scrape_proxy_type=os.getenv("SCRAPE_PROXY_TYPE", "socks5"),
    )
