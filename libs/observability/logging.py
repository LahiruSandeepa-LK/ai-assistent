"""Structured JSON logging + correlation context. See docs/07-observability.md."""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")


def new_correlation_id() -> str:
    cid = uuid.uuid4().hex[:16]
    _correlation_id.set(cid)
    return cid


def set_context(correlation_id: str = "", session_id: str = "", user_id: str = "") -> None:
    if correlation_id:
        _correlation_id.set(correlation_id)
    if session_id:
        _session_id.set(session_id)
    if user_id:
        _user_id.set(user_id)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "service": getattr(record, "service", "ai-assistant"),
            "event": record.getMessage(),
            "correlation_id": _correlation_id.get(),
            "session_id": _session_id.get(),
            "user_id": _user_id.get(),
        }
        for k, v in getattr(record, "fields", {}).items():
            payload[k] = v
        return json.dumps(payload, default=str)


class _ServiceAdapter(logging.LoggerAdapter):
    """Merge the adapter's context (service) with each call's extra, instead of the default
    LoggerAdapter behaviour of overwriting it — otherwise the per-call `fields` (documents,
    chunks, route, …) are lost and never reach the JSON formatter."""

    def process(self, msg, kwargs):
        kwargs["extra"] = {**self.extra, **kwargs.get("extra", {})}
        return msg, kwargs


def get_logger(service: str = "ai-assistant") -> logging.LoggerAdapter:
    logger = logging.getLogger(service)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(JsonFormatter())
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return _ServiceAdapter(logger, {"service": service})


def log(logger, event: str, **fields) -> None:
    logger.info(event, extra={"fields": fields})
