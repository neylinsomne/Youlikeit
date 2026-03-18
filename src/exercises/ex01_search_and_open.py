from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from common.config import Settings
from common.logger import build_logger


def run(query: str, settings: Settings) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = settings.output_dir / "logs" / f"ex01_{ts}.log"
    screenshot_path = settings.output_dir / "screenshots" / f"ex01_{ts}.png"

    logger = build_logger("ex01", log_path)
    logger.info("Iniciando ejercicio 1")
    logger.info("Query: %s", query)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.headless)
        page = browser.new_page()
        page.set_default_timeout(settings.timeout_ms)

        page.goto("https://www.youtube.com/")
        page.get_by_placeholder("Search").fill(query)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)

        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.info("Captura guardada en %s", screenshot_path)

        browser.close()

    return screenshot_path
