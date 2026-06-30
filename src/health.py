"""Ops heartbeat file — process status without opening the tray."""
from __future__ import annotations

import json
import os
import tempfile
import time

from config import CONFIG_DIR, ensure_config_dir
from version import __version__

HEALTH_FILE = CONFIG_DIR / "health.json"
_started_at: float | None = None


def _atomic_write(data: dict) -> None:
    ensure_config_dir()
    fd, tmp_path = tempfile.mkstemp(
        prefix=".health-", suffix=".tmp", dir=str(CONFIG_DIR), text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, HEALTH_FILE)
        try:
            os.chmod(HEALTH_FILE, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_health() -> dict | None:
    if not HEALTH_FILE.exists():
        return None
    try:
        with open(HEALTH_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_health_startup() -> None:
    global _started_at
    _started_at = time.time()
    _atomic_write({
        "status": "running",
        "version": __version__,
        "pid": os.getpid(),
        "started_at": _started_at,
        "last_success_at": None,
        "last_error_at": None,
        "last_error": None,
        "last_request_id": None,
        "last_duration_ms": None,
    })


def record_success(request_id: str, duration_ms: int) -> None:
    now = time.time()
    payload = read_health() or {}
    payload.update({
        "status": "ok",
        "version": __version__,
        "pid": os.getpid(),
        "started_at": payload.get("started_at") or _started_at or now,
        "last_success_at": now,
        "last_request_id": request_id,
        "last_duration_ms": duration_ms,
        "last_error": None,
    })
    _atomic_write(payload)


def record_error(message: str, request_id: str | None = None) -> None:
    now = time.time()
    payload = read_health() or {}
    payload.update({
        "status": "error",
        "version": __version__,
        "pid": os.getpid(),
        "started_at": payload.get("started_at") or _started_at or now,
        "last_error_at": now,
        "last_error": message[:200],
        "last_request_id": request_id,
    })
    _atomic_write(payload)


def write_health_stopped() -> None:
    payload = read_health() or {}
    payload.update({
        "status": "stopped",
        "version": __version__,
        "pid": os.getpid(),
        "stopped_at": time.time(),
    })
    _atomic_write(payload)
