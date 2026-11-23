"""All settings come from environment variables (see .env.example). Nothing is hard-coded."""
import os
from functools import lru_cache


def _env(name, default=""):
    return os.environ.get(name, default)


class Settings:
    def __init__(self):
        self.database_url = _env("DATABASE_URL", "sqlite:///./data/app.db")
        self.storage_backend = _env("STORAGE_BACKEND", "local")            # local | s3
        self.local_storage_dir = _env("LOCAL_STORAGE_DIR", "./data/files")
        self.public_base_url = _env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
        self.s3_endpoint_url = _env("S3_ENDPOINT_URL", "http://minio:9000")
        self.s3_public_endpoint_url = _env("S3_PUBLIC_ENDPOINT_URL", "http://localhost:9000")
        self.s3_access_key = _env("S3_ACCESS_KEY", "minioadmin")
        self.s3_secret_key = _env("S3_SECRET_KEY", "minioadmin")
        self.s3_bucket = _env("S3_BUCKET", "incubrix-music")
        self.s3_region = _env("S3_REGION", "us-east-1")
        self.link_expiry_s = int(_env("LINK_EXPIRY_S", "86400"))
        self.provider = _env("MUSIC_PROVIDER", "procedural")                # procedural | mock | flaky
        self.fallback_provider = _env("FALLBACK_PROVIDER", "")
        self.provider_fail_mode = _env("PROVIDER_FAIL_MODE", "error")       # used by the 'flaky' demo provider: error | timeout
        self.job_timeout_s = float(_env("JOB_TIMEOUT_S", "600"))
        self.api_token = _env("API_TOKEN", "")                              # empty = no auth
        self.rate_limit_per_min = int(_env("RATE_LIMIT_PER_MIN", "120"))
        self.callback_secret = _env("CALLBACK_SECRET", "change-me")
        self.worker_poll_s = float(_env("WORKER_POLL_S", "0.5"))
        self.worker_concurrency = int(_env("WORKER_CONCURRENCY", "2"))
        self.max_upload_mb = int(_env("MAX_UPLOAD_MB", "60"))
        self.log_level = _env("LOG_LEVEL", "INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_caches():
    """Used by tests after changing environment variables."""
    get_settings.cache_clear()
    from . import db, storage
    db.get_engine.cache_clear()
    storage.get_storage.cache_clear()
