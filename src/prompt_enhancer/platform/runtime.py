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
    """Directory containing the app (project root with .venv, src/, etc.)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # runtime.py is at src/prompt_enhancer/platform/runtime.py
    # Project root is 4 levels up: platform → prompt_enhancer → src → root
    return Path(__file__).resolve().parents[3]


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
    # Only invent DISPLAY when an X socket exists — avoids pynput probing a
    # dead :0 under Wayland-only or headless sessions.
    if "DISPLAY" not in env or env.get("DISPLAY") in (":0", ":0.0"):
        if Path("/tmp/.X11-unix/X0").exists():
            env["DISPLAY"] = env.get("DISPLAY") or ":0"
        else:
            env.pop("DISPLAY", None)
            for n in range(1, 5):
                if Path(f"/tmp/.X11-unix/X{n}").exists():
                    env["DISPLAY"] = f":{n}"
                    break
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
    """Asset key for GitHub release downloads. Linux-only after refactor."""
    return "linux_appimage"
