"""
Install/runtime paths — dev (python main.py) vs frozen (PyInstaller/Nuitka binary).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running as a packaged binary, not from source."""
    if getattr(sys, "frozen", False):
        return True
    # Nuitka standalone
    if "__compiled__" in globals():
        return True
    return bool(os.environ.get("PE_FROZEN"))


def app_dir() -> Path:
    """Directory containing the app (source tree or install folder)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # When running from src/, the project root (with .venv) is the parent
    return Path(__file__).resolve().parent.parent


def main_executable() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve()
    return app_dir() / "src" / "main.py"


def python_or_exe() -> str:
    """Interpreter for subprocesses (venv python in dev, binary when frozen)."""
    if is_frozen():
        return str(main_executable())
    candidates = [
        app_dir() / ".venv" / "bin" / "python",
        app_dir() / ".venv" / "bin" / "python3",
        app_dir() / ".venv" / "Scripts" / "pythonw.exe",
        app_dir() / ".venv" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def main_argv() -> list[str]:
    """Argv tail for autostart Exec= / plist ProgramArguments (after exe)."""
    if is_frozen():
        return []
    return [str(main_executable())]


def _appimage_path() -> Path | None:
    """Path to the .AppImage file when running inside one."""
    raw = os.environ.get("APPIMAGE", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def gui_subprocess_env() -> dict[str, str]:
    """Environment for GUI child processes (Settings window)."""
    env = os.environ.copy()
    if not sys.platform.startswith("linux"):
        return env

    if is_frozen():
        app = str(app_dir())
        ld = env.get("LD_LIBRARY_PATH", "")
        parts = [p for p in ld.split(":") if p]
        if app not in parts:
            env["LD_LIBRARY_PATH"] = f"{app}:{ld}" if ld else app

    runtime = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    dbus = env.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not dbus or dbus == "autolaunch:":
        bus = Path(runtime) / "bus"
        if bus.exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    env.setdefault("DISPLAY", ":0")
    return env


def settings_argv() -> list[str]:
    """Launch Settings UI in a dedicated process."""
    appimage = _appimage_path()
    if appimage is not None:
        # Re-enter via AppImage launcher so AppRun sets LD_LIBRARY_PATH.
        return [str(appimage), "--settings"]

    appdir = os.environ.get("APPDIR", "").strip()
    if appdir and is_frozen():
        apprun = Path(appdir) / "AppRun"
        if apprun.is_file():
            return [str(apprun), "--settings"]

    exe = python_or_exe()
    if is_frozen():
        return [exe, "--settings"]
    return [exe, str(app_dir() / "src" / "main.py"), "--settings"]


def platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux_appimage"
