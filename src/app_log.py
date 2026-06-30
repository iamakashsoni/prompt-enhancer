"""Logging for systemd/journalctl and optional JSON lines."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

_CONFIGURED = False
_LOGGER = logging.getLogger("prompt_enhancer")


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True
    level = logging.DEBUG if os.environ.get("PE_LOG_DEBUG") else logging.INFO
    _LOGGER.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    if os.environ.get("PE_LOG_JSON") == "1":
        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "msg": record.getMessage(),
                    "logger": record.name,
                }
                if hasattr(record, "request_id"):
                    payload["request_id"] = record.request_id
                return json.dumps(payload, ensure_ascii=False)

        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.handlers.clear()
    _LOGGER.addHandler(handler)
    _LOGGER.propagate = False


def log(msg: str, *, level: int = logging.INFO, request_id: str | None = None) -> None:
    _configure()
    extra = {"request_id": request_id} if request_id else {}
    _LOGGER.log(level, msg, extra=extra)


def log_warning(msg: str, *, request_id: str | None = None) -> None:
    log(msg, level=logging.WARNING, request_id=request_id)


def log_error(msg: str, *, request_id: str | None = None) -> None:
    log(msg, level=logging.ERROR, request_id=request_id)
