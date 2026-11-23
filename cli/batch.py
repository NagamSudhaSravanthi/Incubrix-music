"""Batch runner for IncuBrix AI Background Music Engine.

Usage:
  python -m cli.batch --input batch_requests.jsonl --outdir out_batch
  python -m cli.batch --input batch_requests.jsonl --outdir out_batch --api-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.engine.errors import EngineError
from app.engine.pipeline import generate


def load_requests(path: str) -> list[dict]:
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def run_local(requests: list[dict], outdir: str) -> list[dict]:
    results = []
    os.makedirs(outdir, exist_ok=True)
    for idx, req in enumerate(requests):
        job_name = req.get("id") or f"job_{idx:03d}"
        job_dir = os.path.join(outdir, job_name)
        t0 = time.perf_counter()
        try:
            manifest, _ = generate(req, job_dir)
            results.append({
                "id": job_name,
                "status": "succeeded",
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "outdir": job_dir,
                "manifest": manifest,
            })
        except EngineError as e:
            results.append({
                "id": job_name,
                "status": "failed",
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "error": e.to_dict()["error"],
            })
        except Exception as e:
            results.append({
                "id": job_name,
                "status": "failed",
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "error": {"code": "INTERNAL_ERROR", "message": str(e), "retryable": False, "details": {}},
            })
    return results


def _http_json(url: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def run_api(requests: list[dict], outdir: str, api_url: str, api_key: str | None) -> list[dict]:
    os.makedirs(outdir, exist_ok=True)
    base = api_url.rstrip("/")
    auth = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    results = []

    for idx, req in enumerate(requests):
        job_name = req.get("id") or f"job_{idx:03d}"
        t0 = time.perf_counter()
        try:
            created = _http_json(
                f"{base}/api/v1/music/jobs",
                payload=req,
                headers={**auth, "Idempotency-Key": f"batch-{job_name}"},
            )
            job_id = created["job_id"]
            while True:
                status_obj = _http_json(f"{base}/api/v1/jobs/{job_id}", headers=auth)
                if status_obj.get("status") in ("succeeded", "failed"):
                    break
                time.sleep(0.5)
            results.append({
                "id": job_name,
                "job_id": job_id,
                "status": status_obj.get("status"),
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "response": status_obj,
            })
        except Exception as e:
            results.append({
                "id": job_name,
                "status": "failed",
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "error": str(e),
            })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch music generation jobs.")
    parser.add_argument("--input", required=True, help="Path to .jsonl or .json request list")
    parser.add_argument("--outdir", default="out_batch", help="Output directory")
    parser.add_argument("--api-url", default=None, help="Optional running API URL (e.g. http://localhost:8000)")
    parser.add_argument("--api-key", default=os.getenv("API_KEY"), help="Optional Bearer token")
    args = parser.parse_args()

    reqs = load_requests(args.input)
    if args.api_url:
        results = run_api(reqs, args.outdir, args.api_url, args.api_key)
    else:
        results = run_local(reqs, args.outdir)

    summary_path = os.path.join(args.outdir, "batch_results.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    ok = sum(1 for r in results if r["status"] == "succeeded")
    print(f"Completed {ok}/{len(results)} jobs -> {summary_path}")


if __name__ == "__main__":
    main()