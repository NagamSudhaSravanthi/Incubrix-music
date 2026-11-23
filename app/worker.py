"""Background worker: python -m app.worker. Takes queued jobs, runs the provider, uploads files, calls the callback."""
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import threading
import time
import urllib.request

from . import db
from .config import get_settings
from .engine.errors import EngineError
from .logging_setup import correlation_id_var, job_id_var, log, setup_logging
from .providers import run_with_fallback
from .storage import get_storage

logger = logging.getLogger("worker")


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send_callback(url, payload: dict, attempts=3):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-IncuBrix-Signature": sign(get_settings().callback_secret, body)}
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                log(logger, logging.INFO, "callback delivered", status=r.status)
                return True
        except Exception as e:
            log(logger, logging.WARNING, "callback failed", attempt=i + 1, error=str(e))
            time.sleep(1 + i)
    return False


def _collect(dirpath):
    """Relative path -> absolute path for every output file."""
    out = {}
    for root, _, files in os.walk(dirpath):
        for f in files:
            full = os.path.join(root, f)
            out[os.path.relpath(full, dirpath).replace(os.sep, "/")] = full
    return out


def process(job):
    s, storage = get_settings(), get_storage()
    job_id = job["id"]
    job_id_var.set(job_id)
    correlation_id_var.set(job["correlation_id"])
    work = tempfile.mkdtemp(prefix=f"job_{job_id}_")
    t0 = time.time()
    log(logger, logging.INFO, "job started")
    try:
        req = dict(job["request"])
        nar = req.get("narration_url")
        if nar and nar.startswith("upload://"):                       # file uploaded through POST /api/v1/uploads
            dest = os.path.join(work, "narration_input")
            storage.get_file(nar[len("upload://"):], dest)
            req["narration_url"] = dest
        progress = lambda pct: db.set_progress(job_id, pct)
        manifest, final_dir = run_with_fallback(req, os.path.join(work, "out"), progress)
        progress(90)
        files = {}
        for rel, full in _collect(final_dir).items():
            key = f"jobs/{job_id}/{rel}"
            storage.put_file(key, full, mimetypes.guess_type(full)[0] or "application/octet-stream")
            files[rel] = key
        result = {"files": files, "warnings": manifest.get("warnings", []),
                  "summary": {"tempo_bpm": manifest["tempo_bpm"], "key": manifest["key"], "style": manifest["style"],
                              "loudness": manifest["loudness"], "provider": manifest["providers"][0]["name"]}}
        db.finish(job_id, result)
        log(logger, logging.INFO, "job succeeded", seconds=round(time.time() - t0, 2))
        status = "succeeded"
    except EngineError as e:
        db.fail(job_id, e.to_dict()["error"])
        log(logger, logging.WARNING, "job failed", code=e.code, message=e.message)
        status = "failed"
    except Exception as e:
        logger.exception("job crashed")
        db.fail(job_id, {"code": "INTERNAL_ERROR", "message": "Unexpected error while generating music.", "retryable": True,
                         "details": {"type": type(e).__name__}})
        status = "failed"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if job["callback_url"]:
        send_callback(job["callback_url"], {"job_id": job_id, "status": status})
    return status


def run_once():
    """Process one queued job. Returns True if a job was handled. Used by the loop and by tests."""
    job = db.claim_next()
    if not job:
        return False
    process(job)
    return True


def loop(stop: threading.Event):
    s = get_settings()
    while not stop.is_set():
        try:
            if not run_once():
                stop.wait(s.worker_poll_s)
        except Exception:
            logger.exception("worker loop error")
            stop.wait(2)


def main():
    s = get_settings()
    setup_logging(s.log_level)
    db.init_db()
    n = db.requeue_stale(s.job_timeout_s * 2)
    log(logger, logging.INFO, "worker started", concurrency=s.worker_concurrency, provider=s.provider, requeued=n)
    stop = threading.Event()
    threads = [threading.Thread(target=loop, args=(stop,), daemon=True) for _ in range(s.worker_concurrency)]
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
