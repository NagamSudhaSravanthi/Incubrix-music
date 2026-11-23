"""HTTP API. All business routes live under /api/v1/. /health and /ready are plain ops endpoints."""
import hashlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, File, Header, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import db
from ..config import get_settings
from ..engine.errors import EngineError
from ..engine.pipeline import validate
from ..logging_setup import correlation_id_var, log, setup_logging
from ..storage import LocalStorage, get_storage
from .schemas import (ErrorResponse, Health, JobAccepted, JobStatus, MusicJobRequest, RegenerateRequest, UploadResult)

logger = logging.getLogger("api")
ERR = {"model": ErrorResponse}
COMMON = {401: ERR, 429: ERR, 500: ERR}


@asynccontextmanager
async def lifespan(app):
    setup_logging(get_settings().log_level)
    db.init_db()
    get_storage()
    yield


app = FastAPI(title="IncuBrix AI Background Music Engine", version="1.0.0", lifespan=lifespan,
              description="Original instrumental music that fits a video exactly, delivered as a mix plus separate instrument stems.")


# ------------------------------------------------------------------ errors
def err_response(code, message, status, retryable=False, details=None, headers=None):
    return JSONResponse({"error": {"code": code, "message": message, "retryable": retryable, "details": details or {}}},
                        status_code=status, headers=headers)


@app.exception_handler(EngineError)
async def _engine_error(request, e: EngineError):
    return err_response(e.code, e.message, e.http_status, e.retryable, e.details)


@app.exception_handler(RequestValidationError)
async def _validation_error(request, e):
    details = [{"field": ".".join(str(x) for x in er["loc"]), "problem": er["msg"]} for er in e.errors()]
    return err_response("VALIDATION_ERROR", "The request body or parameters are invalid.", 422, False, {"errors": jsonable_encoder(details)})


HTTP_CODES = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 409: "CONFLICT",
              413: "PAYLOAD_TOO_LARGE", 429: "RATE_LIMITED"}


@app.exception_handler(StarletteHTTPException)
async def _http_error(request, e):
    return err_response(HTTP_CODES.get(e.status_code, "HTTP_ERROR"), str(e.detail), e.status_code, e.status_code in (429, 503),
                        headers=getattr(e, "headers", None))


@app.exception_handler(Exception)
async def _unhandled(request, e):
    logger.exception("unhandled error")
    return err_response("INTERNAL_ERROR", "Unexpected server error.", 500, True)


# ------------------------------------------------------------------ middleware: correlation id, request log, rate limit
_hits = defaultdict(deque)


@app.middleware("http")
async def observe(request: Request, call_next):
    cid = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    correlation_id_var.set(cid)
    t0 = time.time()
    s = get_settings()
    if request.method == "POST" and request.url.path.startswith("/api/v1") and s.rate_limit_per_min > 0:
        ip = request.client.host if request.client else "?"
        q = _hits[ip]
        now = time.time()
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= s.rate_limit_per_min:
            resp = err_response("RATE_LIMITED", "Too many requests; slow down.", 429, True, {"limit_per_minute": s.rate_limit_per_min},
                                headers={"Retry-After": "10"})
            resp.headers["X-Correlation-Id"] = cid
            return resp
        q.append(now)
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = cid
    if request.url.path not in ("/health", "/ready"):
        log(logger, logging.INFO, "request", method=request.method, path=request.url.path, status=response.status_code,
            duration_ms=round((time.time() - t0) * 1000, 1))
    return response


def require_token(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)):
    token = get_settings().api_token
    if not token:
        return
    supplied = x_api_key or (authorization or "").removeprefix("Bearer ").strip()
    if supplied != token:
        raise StarletteHTTPException(401, "Missing or invalid API token. Send 'Authorization: Bearer <token>' or 'X-API-Key'.")


api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])


# ------------------------------------------------------------------ helpers
def _hash(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def _accepted(row, replay=False):
    s = get_settings()
    body = {"job_id": row["id"], "status": row["status"], "status_url": f"{s.public_base_url}/api/v1/jobs/{row['id']}"}
    return JSONResponse(body, status_code=202, headers={"Idempotent-Replayed": "true"} if replay else None)


def _enqueue(req: dict, key: str | None, source_job_id=None):
    validate(req)
    rhash = _hash(req)
    if key:
        old = db.get_by_key(key)
        if old:
            return _replay(old, rhash)
    job_id = str(uuid.uuid4())
    t = db.now()
    row = dict(id=job_id, status="queued", progress=0, request=req, idempotency_key=key, request_hash=rhash,
               correlation_id=correlation_id_var.get(), callback_url=req.get("callback_url"), source_job_id=source_job_id,
               created_at=t, updated_at=t)
    try:
        db.insert_job(row)
    except db.Duplicate:                       # two identical requests raced: the unique key lets exactly one win
        return _replay(db.get_by_key(key), rhash)
    log(logger, logging.INFO, "job queued", job_id=job_id)
    return _accepted(row)


def _replay(old, rhash):
    if old["request_hash"] != rhash:
        raise EngineError("IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used with a different request body.",
                          http_status=409, details={"job_id": old["id"]})
    return _accepted(old, replay=True)


# ------------------------------------------------------------------ routes
@api.post("/music/jobs", status_code=202, response_model=JobAccepted, responses={**COMMON, 409: ERR, 422: ERR},
          summary="Create a music generation job")
def create_job(body: MusicJobRequest, idempotency_key: str | None = Header(default=None)):
    return _enqueue(body.model_dump(exclude_none=True), idempotency_key)


@api.post("/music/jobs/{job_id}/regenerate", status_code=202, response_model=JobAccepted, responses={**COMMON, 404: ERR, 409: ERR, 422: ERR},
          summary="Regenerate ONE stem (for example new drums); the other stems stay identical")
def regenerate(job_id: str, body: RegenerateRequest, idempotency_key: str | None = Header(default=None)):
    src = db.get_job(job_id)
    if not src:
        raise StarletteHTTPException(404, "Job not found.")
    req = dict(src["request"])
    variants = dict(req.get("variants") or {})
    variants[body.stem] = body.variant if body.variant is not None else variants.get(body.stem, 0) + 1
    req["variants"] = variants
    return _enqueue(req, idempotency_key, source_job_id=job_id)


@api.get("/jobs/{job_id}", response_model=JobStatus, responses={**COMMON, 404: ERR}, summary="Job status, progress and result links")
def get_job(job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise StarletteHTTPException(404, "Job not found.")
    storage = get_storage()
    result = None
    if row["status"] == "succeeded" and row["result"]:
        r = row["result"]
        result = {"files": {rel: storage.url(key) for rel, key in r["files"].items()}, "warnings": r.get("warnings", []), "summary": r.get("summary", {})}
    return {"job_id": row["id"], "status": row["status"], "progress": row["progress"], "created_at": row["created_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None, "source_job_id": row["source_job_id"],
            "result": result, "error": row["error"]}


@api.post("/uploads", status_code=201, response_model=UploadResult, responses={**COMMON, 413: ERR, 422: ERR}, summary="Upload a narration file")
async def upload(file: UploadFile = File(...)):
    s = get_settings()
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise StarletteHTTPException(413, f"File is larger than {s.max_upload_mb} MB.")
    name = os.path.basename(file.filename or "upload.bin")
    key = f"uploads/{uuid.uuid4()}/{name}"
    tmp = f"/tmp/{uuid.uuid4()}" if os.name != "nt" else os.path.join(os.environ.get("TEMP", "."), str(uuid.uuid4()))
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        get_storage().put_file(key, tmp, file.content_type)
    finally:
        os.remove(tmp)
    return {"url": f"upload://{key}", "filename": name, "bytes": len(data)}


@app.get("/health", response_model=Health, summary="Liveness")
def health():
    return {"status": "ok"}


@app.get("/ready", response_model=Health, responses={503: ERR}, summary="Readiness: database and storage reachable")
def ready():
    try:
        db.ping()
        get_storage().ready()
    except Exception as e:
        raise EngineError("NOT_READY", f"Dependency not ready: {type(e).__name__}", retryable=True, http_status=503)
    return {"status": "ready"}


@app.get("/files/{key:path}", include_in_schema=False)
def local_file(key: str):
    st = get_storage()
    if not isinstance(st, LocalStorage):
        raise StarletteHTTPException(404, "Not found.")
    try:
        path = st.local_path(key)
    except ValueError:
        raise StarletteHTTPException(404, "Not found.")
    if not os.path.isfile(path):
        raise StarletteHTTPException(404, "Not found.")
    return FileResponse(path)


app.include_router(api)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    for path in schema["paths"].values():                       # our validation errors use the standard error shape
        for op in path.values():
            r = op.get("responses", {})
            if "422" in r and "content" in r["422"]:
                r["422"]["content"]["application/json"]["schema"] = {"$ref": "#/components/schemas/ErrorResponse"}
                r["422"]["description"] = "Validation error"
    for n in ("HTTPValidationError", "ValidationError"):
        schema.get("components", {}).get("schemas", {}).pop(n, None)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
