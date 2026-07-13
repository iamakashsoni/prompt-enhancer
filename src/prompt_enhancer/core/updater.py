"""
Version check against version.json on GitHub Releases (or PE_UPDATE_URL).
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Callable

from prompt_enhancer.platform.runtime import platform_key
from prompt_enhancer.core.version import UPDATE_MANIFEST_URL, __version__

_CHECK_TIMEOUT_S = 4.0
_lock = threading.Lock()
_blocked = False
_optional: "UpdateInfo | None" = None
_last_error: str | None = None


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    min_supported: str
    force: bool
    release_notes: str
    download_url: str | None


def _parse_version(ver: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in (ver or "0").strip().lstrip("v").split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _version_lt(a: str, b: str) -> bool:
    return _parse_version(a) < _parse_version(b)


def fetch_manifest(url: str | None = None) -> dict | None:
    target = (url or UPDATE_MANIFEST_URL).strip()
    if not target:
        return None
    req = urllib.request.Request(
        target,
        headers={"User-Agent": f"PromptEnhancer/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as exc:
        global _last_error
        _last_error = str(exc)
        return None


def _download_url(manifest: dict) -> str | None:
    downloads = manifest.get("downloads") or {}
    key = platform_key()
    url = downloads.get(key)
    if url:
        return str(url).strip() or None
    return None


def evaluate(manifest: dict | None = None) -> UpdateInfo | None:
    """Return UpdateInfo when user should see an update UI; None if up to date."""
    data = manifest if manifest is not None else fetch_manifest()
    if not data:
        return None

    latest = str(data.get("latest", "")).strip()
    min_supported = str(data.get("min_supported", "0.0.0")).strip()
    force = bool(data.get("force", False))
    notes = str(data.get("release_notes", "")).strip()
    dl = _download_url(data)

    if not latest:
        return None

    must_block = force or _version_lt(__version__, min_supported)
    has_optional = _version_lt(__version__, latest)

    if not must_block and not has_optional:
        return None

    return UpdateInfo(
        current=__version__,
        latest=latest,
        min_supported=min_supported,
        force=must_block,
        release_notes=notes,
        download_url=dl,
    )


def apply_evaluation(info: UpdateInfo | None) -> None:
    global _blocked, _optional
    with _lock:
        if info is None:
            _blocked = False
            _optional = None
            return
        if info.force or _version_lt(__version__, info.min_supported):
            _blocked = True
            _optional = info
        else:
            _blocked = False
            _optional = info


def is_update_required() -> bool:
    with _lock:
        return _blocked


def get_pending_update() -> UpdateInfo | None:
    with _lock:
        return _optional


def get_last_check_error() -> str | None:
    return _last_error


def open_download(url: str | None = None) -> None:
    info = get_pending_update()
    target = url or (info.download_url if info else None)
    if target:
        webbrowser.open(target)


def check_sync() -> UpdateInfo | None:
    info = evaluate()
    apply_evaluation(info)
    return info


def check_async(on_done: Callable[[UpdateInfo | None], None] | None = None) -> None:
    def _run() -> None:
        info = check_sync()
        if on_done:
            on_done(info)

    threading.Thread(target=_run, daemon=True, name="update-check").start()


def show_update_dialog(info: UpdateInfo, *, parent=None) -> str:
    """
    Show blocking or optional update dialog. Returns 'download', 'later', or 'quit'.

    Threading note:
    Tkinter is officially single-threaded; on macOS, creating a Tk root from a
    non-main thread is unsupported and can deadlock. main.py invokes this from
    the "update-check" daemon thread. We therefore:
      - Run the dialog inline when already on the main thread.
      - On worker threads, try the dialog and gracefully degrade to "later" if
        Tk cannot be created (e.g. macOS off-main-thread). The caller treats
        "later" as "do not block the user", so the app keeps working.
    """
    import threading
    import tkinter as tk
    from tkinter import messagebox

    def _show() -> str:
        root = tk.Tk()
        try:
            root.withdraw()
            if parent is not None:
                try:
                    root.transient(parent)
                except Exception:
                    pass

            title = "Update required" if info.force or _version_lt(__version__, info.min_supported) else "Update available"
            body = f"You have v{info.current}.\n"
            if info.latest:
                body += f"Latest version: v{info.latest}\n\n"
            if info.release_notes:
                body += f"{info.release_notes}\n\n"
            if info.download_url:
                body += "Open the download page in your browser?"
            else:
                body += "Visit the project page to download the latest version."

            forced = info.force or _version_lt(__version__, info.min_supported)
            if forced:
                if info.download_url:
                    if messagebox.askokcancel(title, body + "\n\nThis version can no longer be used.", icon="warning"):
                        open_download(info.download_url)
                        return "download"
                else:
                    messagebox.showwarning(title, body + "\n\nThis version can no longer be used.")
                return "quit"

            if messagebox.askyesno(title, body):
                open_download(info.download_url)
                return "download"
            return "later"
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    if threading.current_thread() is threading.main_thread():
        return _show()

    # Worker-thread path: Tkinter on macOS may refuse to create a root here.
    # Degrade gracefully so the app keeps running.
    try:
        return _show()
    except Exception as exc:  # pragma: no cover — defensive
        from prompt_enhancer.core.logging import log_error
        log_error(f"update dialog could not be shown: {exc!r}")
        # If the update is forced but we cannot show a dialog, surface the
        # failure via webbrowser so the user still has a path forward.
        if (info.force or _version_lt(__version__, info.min_supported)) and info.download_url:
            try:
                open_download(info.download_url)
            except Exception:
                pass
            return "download"
        return "later"
