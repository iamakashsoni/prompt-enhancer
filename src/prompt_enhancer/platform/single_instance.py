"""Ensure only one Prompt Enhancer process runs at a time (Linux, fcntl)."""
from __future__ import annotations

import atexit
import fcntl
import os
import sys
from pathlib import Path

_LOCK_PATH = Path.home() / ".prompt-enhancer" / "instance.lock"
_lock_fp = None


def _read_lock_pid() -> str:
    try:
        pid = _LOCK_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "?"
    return pid or "unknown"


def _stop_hint() -> str:
    return "Stop extra copies: systemctl --user restart prompt-enhancer.service"


def release() -> None:
    """Release the single-instance lock (SIGTERM shutdown)."""
    global _lock_fp
    fp = _lock_fp
    if fp is None:
        return
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        fp.close()
    except OSError:
        pass
    _lock_fp = None


def acquire() -> None:
    global _lock_fp
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fp = open(_LOCK_PATH, "a+", encoding="utf-8")

    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        fp.close()
        other_pid = _read_lock_pid()
        print(
            f"Prompt Enhancer is already running (pid {other_pid}).\n"
            f"{_stop_hint()}",
            file=sys.stderr,
        )
        sys.exit(1)

    fp.seek(0)
    fp.truncate()
    fp.write(str(os.getpid()))
    fp.flush()
    _lock_fp = fp
    atexit.register(release)
