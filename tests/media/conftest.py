from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def ia_notld_meta() -> dict:
    """Metadata real (recortada) de IA: Night.Of.The.Living.Dead_1080p."""
    return json.loads((FIXTURES / "ia_notld_metadata.json").read_text(encoding="utf-8"))


@pytest.fixture
def media_conn() -> sqlite3.Connection:
    from apps.media.schema import ensure_schema
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """media_cache (segmentos, análisis, .npy) nunca escribe en el data/ real del repo."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("KEEP_ANALYSIS_FILES", raising=False)
    monkeypatch.delenv("MEDIA_CACHE_MAX_GB", raising=False)
