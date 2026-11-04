from __future__ import annotations

import pytest

from tests.supercut.helpers import isolate_env, seed_fear_world

TOKEN = "test-studio-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    isolate_env(tmp_path, monkeypatch)
    monkeypatch.setenv("STUDIO_TOKEN", TOKEN)
    import apps.publish.youtube as yt
    yt._pending.clear()
    return tmp_path


@pytest.fixture
def app():
    from apps.studio.app import create_app
    return create_app(start_worker=False)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app, headers=AUTH) as c:
        yield c


@pytest.fixture
def anon(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    from apps.studio.settings import connect
    conn = connect()
    yield conn
    conn.close()


@pytest.fixture
def world(db):
    return seed_fear_world(db)


def run_jobs(app) -> list[int]:
    """Corre en este hilo todo lo encolado (el worker no arranca en los tests)."""
    done = []
    while (jid := app.state.jobs.run_next()) is not None:
        done.append(jid)
    return done
