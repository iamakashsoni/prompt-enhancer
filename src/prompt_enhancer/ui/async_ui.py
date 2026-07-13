"""Thread-safe Future delivery helpers (Tk-free, unit-testable)."""
from __future__ import annotations

from concurrent.futures import Future
from typing import Callable, TypeVar

T = TypeVar("T")


def try_deliver_future(
    future: Future[T],
    on_success: Callable[[T], None],
    on_error: Callable[[BaseException], None],
) -> bool:
    """
    If *future* is done, invoke *on_success* or *on_error* and return True.
    Otherwise return False (caller should poll again later).
    """
    if not future.done():
        return False
    try:
        on_success(future.result())
    except Exception as exc:
        on_error(exc)
    return True
