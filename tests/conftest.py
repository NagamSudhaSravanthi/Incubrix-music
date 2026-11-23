import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated SQLite + local-folder storage + mock provider. No keys, no network, no docker."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "files"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("MUSIC_PROVIDER", "mock")
    monkeypatch.setenv("FALLBACK_PROVIDER", "")
    monkeypatch.setenv("API_TOKEN", "")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1000")
    monkeypatch.setenv("JOB_TIMEOUT_S", "30")
    from app.config import reset_caches
    reset_caches()
    yield monkeypatch
    reset_caches()


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient
    from app.api.main import app
    with TestClient(app) as c:
        yield c


def run_worker():
    from app import worker
    n = 0
    while worker.run_once():
        n += 1
    return n


def wait_done(client, job_id):
    run_worker()
    return client.get(f"/api/v1/jobs/{job_id}").json()
