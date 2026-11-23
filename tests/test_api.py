"""API + worker tests: job lifecycle, idempotency, errors, health, openapi, retries, fallback, callbacks, auth."""
import hashlib
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import soundfile as sf
import yaml

from conftest import run_worker, wait_done

BODY = {"prompt": "warm acoustic pop", "duration_s": 8, "seed": 1}


def test_job_lifecycle(client):
    r = client.post("/api/v1/music/jobs", json=BODY)
    assert r.status_code == 202
    j = r.json()
    assert j["status"] == "queued" and j["status_url"].endswith(j["job_id"])
    assert client.get(f"/api/v1/jobs/{j['job_id']}").json()["progress"] == 0
    done = wait_done(client, j["job_id"])
    assert done["status"] == "succeeded" and done["progress"] == 100
    files = done["result"]["files"]
    for name in ("mix.wav", "mix.mp3", "stems/drums.wav", "stems/bass.wav", "stems/pads.wav", "stems/melody.wav", "music_manifest.json"):
        assert name in files, name
    wav = client.get(files["mix.wav"].replace("http://testserver", ""))
    assert wav.status_code == 200 and len(wav.content) > 10000
    manifest = client.get(files["music_manifest.json"].replace("http://testserver", "")).json()
    for k in ("providers", "seed", "timings_s", "cost_estimate_usd", "warnings", "licences", "stems", "grid", "tempo_bpm", "key", "loudness"):
        assert k in manifest, k


def test_idempotency_same_key_same_job_and_one_run(client):
    h = {"Idempotency-Key": "abc-123"}
    a = client.post("/api/v1/music/jobs", json=BODY, headers=h)
    b = client.post("/api/v1/music/jobs", json=BODY, headers=h)
    assert a.json()["job_id"] == b.json()["job_id"]
    assert b.headers["Idempotent-Replayed"] == "true"
    assert run_worker() == 1                                  # the work was done exactly once


def test_idempotency_key_with_different_body_is_409(client):
    h = {"Idempotency-Key": "k1"}
    client.post("/api/v1/music/jobs", json=BODY, headers=h)
    r = client.post("/api/v1/music/jobs", json={**BODY, "duration_s": 9}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_two_simultaneous_requests_same_key_make_one_job(client):
    ids, h = [], {"Idempotency-Key": "race"}
    def go():
        ids.append(client.post("/api/v1/music/jobs", json=BODY, headers=h).json()["job_id"])
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(set(ids)) == 1


def test_two_different_jobs_at_once_both_finish(client):
    a = client.post("/api/v1/music/jobs", json=BODY).json()["job_id"]
    b = client.post("/api/v1/music/jobs", json={**BODY, "seed": 2}).json()["job_id"]
    ts = [threading.Thread(target=run_worker) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert {client.get(f"/api/v1/jobs/{i}").json()["status"] for i in (a, b)} == {"succeeded"}


def test_error_shape(client):
    for r, code, status in [
        (client.post("/api/v1/music/jobs", json={**BODY, "duration_s": 2}), "INVALID_DURATION", 422),
        (client.post("/api/v1/music/jobs", json={"duration_s": 10}), "VALIDATION_ERROR", 422),
        (client.get("/api/v1/jobs/nope"), "NOT_FOUND", 404),
        (client.delete("/api/v1/music/jobs"), "METHOD_NOT_ALLOWED", 405),
    ]:
        e = r.json()["error"]
        assert r.status_code == status and e["code"] == code
        assert set(e) == {"code", "message", "retryable", "details"} and e["code"].isupper()


def test_health_ready_and_correlation_id(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    r = client.get("/health", headers={"X-Correlation-Id": "corr-42"})
    assert r.headers["X-Correlation-Id"] == "corr-42"
    assert client.get("/health").headers["X-Correlation-Id"]


def test_openapi_yaml_matches_running_service(client):
    from app.api.main import app
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    disk = yaml.safe_load(open(os.path.join(root, "openapi.yaml")))
    live = json.loads(json.dumps(app.openapi()))
    assert disk["openapi"].startswith("3.1")
    assert disk == live, "openapi.yaml is stale: run python scripts/export_openapi.py"
    assert all(p.startswith("/api/v1/") or p in ("/health", "/ready") for p in live["paths"])


def test_auth_token(client, env):
    env.setenv("API_TOKEN", "secret")
    from app.config import reset_caches
    reset_caches()
    assert client.post("/api/v1/music/jobs", json=BODY).status_code == 401
    assert client.post("/api/v1/music/jobs", json=BODY, headers={"Authorization": "Bearer secret"}).status_code == 202
    assert client.get("/health").status_code == 200          # ops endpoints stay open


def test_rate_limit(client, env):
    env.setenv("RATE_LIMIT_PER_MIN", "3")
    from app.config import reset_caches
    from app.api import main
    reset_caches(); main._hits.clear()
    codes = [client.post("/api/v1/music/jobs", json=BODY).status_code for _ in range(5)]
    assert codes[:3] == [202] * 3 and codes[3] == 429
    r = client.post("/api/v1/music/jobs", json=BODY)
    assert r.json()["error"]["retryable"] is True


def test_provider_failure_is_reported_retryable(client, env):
    env.setenv("MUSIC_PROVIDER", "flaky"); env.setenv("PROVIDER_FAIL_MODE", "error")
    from app.config import reset_caches
    reset_caches()
    j = client.post("/api/v1/music/jobs", json=BODY).json()["job_id"]
    done = wait_done(client, j)
    assert done["status"] == "failed" and done["error"]["code"] == "PROVIDER_ERROR" and done["error"]["retryable"] is True


def test_provider_timeout(client, env):
    env.setenv("MUSIC_PROVIDER", "flaky"); env.setenv("PROVIDER_FAIL_MODE", "timeout"); env.setenv("JOB_TIMEOUT_S", "1")
    from app.config import reset_caches
    reset_caches()
    j = client.post("/api/v1/music/jobs", json=BODY).json()["job_id"]
    done = wait_done(client, j)
    assert done["status"] == "failed" and done["error"]["code"] == "PROVIDER_TIMEOUT" and done["error"]["retryable"]


def test_provider_failure_falls_back_with_warning(client, env):
    env.setenv("MUSIC_PROVIDER", "flaky"); env.setenv("FALLBACK_PROVIDER", "mock")
    from app.config import reset_caches
    reset_caches()
    j = client.post("/api/v1/music/jobs", json=BODY).json()["job_id"]
    done = wait_done(client, j)
    assert done["status"] == "succeeded"
    assert "PROVIDER_FALLBACK_USED" in {w["code"] for w in done["result"]["warnings"]}


def test_upload_narration_and_ducked_mix(client, tmp_path):
    sr = 48000
    t = np.arange(sr * 6) / sr
    sf.write(str(tmp_path / "v.wav"), (0.3 * np.sin(2 * np.pi * 200 * t) * (t > 1)).astype(np.float32), sr)
    up = client.post("/api/v1/uploads", files={"file": ("voice.wav", open(tmp_path / "v.wav", "rb"), "audio/wav")})
    assert up.status_code == 201 and up.json()["url"].startswith("upload://")
    j = client.post("/api/v1/music/jobs", json={**BODY, "narration_url": up.json()["url"]}).json()["job_id"]
    done = wait_done(client, j)
    assert done["status"] == "succeeded" and "mix_ducked.wav" in done["result"]["files"]


def test_bad_narration_url_is_a_clean_failure(client):
    j = client.post("/api/v1/music/jobs", json={**BODY, "narration_url": "http://127.0.0.1:9/none.wav"}).json()["job_id"]
    done = wait_done(client, j)
    assert done["status"] == "failed" and done["error"]["code"] == "NARRATION_UNREADABLE"


def test_callback_is_signed_with_hmac(client, env):
    from app.worker import sign
    assert sign("k", b"abc") == "sha256=" + hmac.new(b"k", b"abc", hashlib.sha256).hexdigest()
    got = {}
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got["body"] = self.rfile.read(int(self.headers["Content-Length"])); got["sig"] = self.headers["X-IncuBrix-Signature"]
            self.send_response(200); self.end_headers()
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    j = client.post("/api/v1/music/jobs", json={**BODY, "callback_url": f"http://127.0.0.1:{srv.server_port}/cb"}).json()["job_id"]
    wait_done(client, j)
    srv.shutdown()
    assert got["sig"] == sign("change-me", got["body"]) and json.loads(got["body"])["job_id"] == j


def test_regenerate_endpoint_changes_only_that_stem(client, env):
    env.setenv("MUSIC_PROVIDER", "procedural")
    from app.config import reset_caches
    reset_caches()
    a = client.post("/api/v1/music/jobs", json={**BODY, "duration_s": 8, "prompt": "electronic house"}).json()["job_id"]
    wait_done(client, a)
    b = client.post(f"/api/v1/music/jobs/{a}/regenerate", json={"stem": "drums"}).json()["job_id"]
    wait_done(client, b)
    from app.storage import get_storage
    st = get_storage()
    h = lambda job, n: hashlib.sha256(open(st.local_path(f"jobs/{job}/stems/{n}.wav"), "rb").read()).hexdigest()
    for n in ("bass", "pads", "melody"):
        assert h(a, n) == h(b, n), n
    assert h(a, "drums") != h(b, "drums")
    assert client.get(f"/api/v1/jobs/{b}").json()["source_job_id"] == a
    assert client.post(f"/api/v1/music/jobs/{a}/regenerate", json={"stem": "kazoo"}).status_code == 422
