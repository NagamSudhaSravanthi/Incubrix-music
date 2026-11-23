# Sources & Provenance

## Original Audio & DSP Synthesis
All audio synthesis, sequencing, mixing, loudness normalization, and voiceover ducking code in app/engine/ is original code written for this project using NumPy and SciPy primitives. No third-party audio samples, MIDI packs, royalty-free loops, or pretrained neural audio weights are used.

## Third-Party Software Libraries
- FastAPI & Uvicorn: HTTP API framework and ASGI server
- Pydantic: Request/response schema validation and OpenAPI generation
- NumPy & SciPy: Array math, filtering, resampling, and DSP synthesis
- SoundFile (libsndfile): Reading and writing WAV/MP3 audio files
- SQLAlchemy / SQLite: Job state persistence and idempotency tracking
- Boto3: S3-compatible object storage client (MinIO / AWS S3)
- Pytest & HTTPX: Automated test suite