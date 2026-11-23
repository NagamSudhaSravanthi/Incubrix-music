# IncuBrix AI Background Music Engine

Procedural, sample-accurate instrumental music generator and FastAPI microservice built for video production workflows. Generates a mastered stereo/mono mix (`mix.wav` / `mix.mp3`), four separated stems (`drums`, `bass`, `pads`, `melody`), optional voiceover ducking (`mix_ducked.wav`), and a machine-readable `music_manifest.json`.

## Architecture Overview

- **`app/engine/`**: Pure-Python procedural DSP engine (`prompt.py`, `plan.py`, `synth.py`, `render.py`, `mix.py`, `duck.py`, `pipeline.py`, `errors.py`). Renders exact sample lengths (`duration_s * sample_rate`), normalizes loudness to target LUFS with true-peak limiting, and applies energy-based VAD voiceover ducking.
- **`app/api/`**: FastAPI REST service (`main.py`, `schemas.py`) supporting asynchronous job submission, `Idempotency-Key` deduplication, per-stem regeneration, file uploads, correlation-ID JSON logging, bearer auth, and rate limiting.
- **`app/worker.py`**: Background queue worker polling SQLite/Postgres jobs, executing providers (`procedural`, `mock`, `flaky`), uploading artifacts to local disk or S3/MinIO (`app/storage.py`), and firing HMAC-signed webhooks.
- **`cli/batch.py` & `measure.py`**: Batch job runner and automated quality/loudness/ducking benchmark runner.

## Quickstart (Local)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt