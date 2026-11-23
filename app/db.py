"""Job store. SQLite for local tests, Postgres in docker-compose; same code for both."""
import os
import time
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import (JSON, Column, DateTime, Integer, MetaData, String, Table, create_engine, select, text, update)
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

from .config import get_settings

metadata = MetaData()
jobs = Table(
    "jobs", metadata,
    Column("id", String(36), primary_key=True),
    Column("status", String(16), nullable=False, index=True),          # queued | running | succeeded | failed
    Column("progress", Integer, nullable=False, default=0),
    Column("request", JSON, nullable=False),
    Column("result", JSON),
    Column("error", JSON),
    Column("idempotency_key", String(200), unique=True),
    Column("request_hash", String(64)),
    Column("correlation_id", String(100)),
    Column("callback_url", String(2000)),
    Column("source_job_id", String(36)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)
Duplicate = IntegrityError


def now():
    return datetime.now(timezone.utc)


@lru_cache
def get_engine():
    url = get_settings().database_url
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def init_db(retries=10):
    for i in range(retries):                       # API and worker may start together; retry the create race
        try:
            metadata.create_all(get_engine())
            return
        except (OperationalError, ProgrammingError, IntegrityError):
            if i == retries - 1:
                raise
            time.sleep(1)


def ping():
    with get_engine().connect() as c:
        c.execute(text("SELECT 1"))


def insert_job(row: dict):
    with get_engine().begin() as c:
        c.execute(jobs.insert().values(**row))


def get_job(job_id):
    with get_engine().connect() as c:
        return c.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()


def get_by_key(key):
    with get_engine().connect() as c:
        return c.execute(select(jobs).where(jobs.c.idempotency_key == key)).mappings().first()


def claim_next():
    """Atomically take the oldest queued job. Safe with several workers: only one UPDATE can flip queued -> running."""
    with get_engine().begin() as c:
        row = c.execute(select(jobs.c.id).where(jobs.c.status == "queued").order_by(jobs.c.created_at).limit(1)).first()
        if not row:
            return None
        n = c.execute(update(jobs).where(jobs.c.id == row.id, jobs.c.status == "queued")
                      .values(status="running", started_at=now(), updated_at=now(), progress=1)).rowcount
        if n != 1:
            return None
        return c.execute(select(jobs).where(jobs.c.id == row.id)).mappings().first()


def set_progress(job_id, pct):
    with get_engine().begin() as c:
        c.execute(update(jobs).where(jobs.c.id == job_id).values(progress=int(min(99, max(0, pct))), updated_at=now()))


def finish(job_id, result):
    with get_engine().begin() as c:
        c.execute(update(jobs).where(jobs.c.id == job_id).values(status="succeeded", progress=100, result=result,
                                                                  finished_at=now(), updated_at=now()))


def fail(job_id, error):
    with get_engine().begin() as c:
        c.execute(update(jobs).where(jobs.c.id == job_id).values(status="failed", error=error, finished_at=now(), updated_at=now()))


def requeue_stale(older_than_s):
    """A worker that died leaves jobs 'running'; put them back in the queue."""
    from datetime import timedelta
    with get_engine().begin() as c:
        return c.execute(update(jobs).where(jobs.c.status == "running", jobs.c.updated_at < now() - timedelta(seconds=older_than_s))
                         .values(status="queued", progress=0)).rowcount
