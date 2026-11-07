from __future__ import annotations

import pytest

from tests.supercut.helpers import isolate_env, make_master, needs_ffmpeg, schema_conn


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """data/, outputs/ y tokens/ en tmp: nunca se escribe en el repo."""
    return isolate_env(tmp_path, monkeypatch)


@pytest.fixture
def sconn():
    c = schema_conn()
    yield c
    c.close()


@pytest.fixture(scope="session")
def masters(tmp_path_factory):
    """Dos masters sintéticos (uno sin audio, como una película muda) compartidos por la sesión."""
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg no disponible")
    root = tmp_path_factory.mktemp("masters")
    return {"Night of the Living Dead": make_master(root / "notld.mkv", seconds=14),
            "Carnival of Souls": make_master(root / "carnival.mp4", seconds=12, size="480x360", audio=False),
            "Horror Express": make_master(root / "horror.mkv", seconds=30, size="320x240")}


__all__ = ["needs_ffmpeg"]
