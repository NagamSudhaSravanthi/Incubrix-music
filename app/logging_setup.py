"""Structured JSON logs. Every line carries timestamp, level, job_id and the X-Correlation-Id of the request."""
import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

correlation_id_var = contextvars.ContextVar("correlation_id", default=None)
job_id_var = contextvars.ContextVar("job_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        d = {"timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
             "level": record.levelname, "logger": record.name, "message": record.getMessage(),
             "job_id": job_id_var.get(), "correlation_id": correlation_id_var.get()}
        d.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            d["exception"] = self.formatException(record.exc_info)
        return json.dumps(d, default=str)


def setup_logging(level="INFO"):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True      # we log requests ourselves, in JSON


def log(logger, level, msg, **fields):
    logger.log(level, msg, extra={"fields": fields})
