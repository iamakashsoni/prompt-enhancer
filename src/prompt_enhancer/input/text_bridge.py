"""
Captures currently selected text via clipboard simulation and pastes back
the enhanced result.

Linux only:
  - X11: pyperclip + pynput Controller for Ctrl+C / Ctrl+V injection
  - Wayland: wl-clipboard + ydotool (pynput can't inject into native Wayland clients)
"""
import os
import subprocess
import time

import pyperclip

from prompt_enhancer.core.logging import log
from prompt_enhancer.platform.evdev_hotkeys import is_wayland, simulate_key_combo

# On Wayland, key injection is via ydotool — no pynput Controller needed.
# On X11, pynput.Controller handles Ctrl+C / Ctrl+V.
if not is_wayland():
    from pynput.keyboard import Controller
    _keyboard = Controller()
else:
    _keyboard = None

_SENTINEL = "__PROMPT_ENHANCER_CAPTURE_SENTINEL_7f3a__"


def _copy_combo() -> tuple:
    return ("ctrl", "c")


def _paste_combo() -> tuple:
    return ("ctrl", "v")


def _tap(mod_name: str, char: str) -> bool:
    return simulate_key_combo((mod_name, char))


def _wl_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env.setdefault("XDG_RUNTIME_DIR", runtime)
    if not env.get("WAYLAND_DISPLAY"):
        env["WAYLAND_DISPLAY"] = "wayland-0"
    bus = env.get("DBUS_SESSION_BUS_ADDRESS")
    if not bus or bus == "autolaunch:":
        bus_path = os.path.join(runtime, "bus")
        if os.path.exists(bus_path):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"
    return env


def _wl_copy_stdin(text: str) -> None:
    env = _wl_env()
    proc = subprocess.Popen(
        ["wl-copy", "-t", "text"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        close_fds=True,
    )
    try:
        proc.communicate(input=text.encode("utf-8"), timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()


def _clip_write(text: str) -> None:
    try:
        pyperclip.copy(text)
    except Exception:
        if is_wayland():
            _wl_copy_stdin(text)
        else:
            raise


def _clip_read() -> str:
    try:
        return pyperclip.paste() or ""
    except Exception:
        if is_wayland():
            try:
                proc = subprocess.run(
                    ["wl-paste", "-n", "-t", "text"],
                    check=False,
                    timeout=3,
                    capture_output=True,
                    text=True,
                    env=_wl_env(),
                )
                return proc.stdout or ""
            except (FileNotFoundError, subprocess.TimeoutExpired):
                return ""
        return ""


def _sync_primary(text: str) -> None:
    """Update Wayland PRIMARY so a second hotkey cannot re-capture stale text."""
    if not (is_wayland()):
        return
    try:
        proc = subprocess.Popen(
            ["wl-copy", "-p", "-t", "text"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_wl_env(),
            close_fds=True,
        )
        proc.communicate(input=text.encode("utf-8"), timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _primary_read() -> str:
    """Read Wayland PRIMARY selection (highlighted text without Ctrl+C)."""
    if not (is_wayland()):
        return ""
    try:
        proc = subprocess.run(
            ["wl-paste", "-p", "-n", "-t", "text"],
            check=False,
            timeout=3,
            capture_output=True,
            text=True,
            env=_wl_env(),
        )
        return proc.stdout or ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def capture_selected_text() -> tuple[str, str] | None:
    """
    Returns (selected_text, original_clipboard) or None if nothing selected.
    Prefers Ctrl+C (current focus selection); PRIMARY is a Wayland fallback only.
    """
    original = _clip_read()
    wayland = is_wayland()
    delay = 0.35 if wayland else 0.22

    _clip_write(_SENTINEL)
    mod, char = _copy_combo()
    if _tap(mod, char):
        captured = ""
        for _ in range(4):
            time.sleep(delay / 4)
            captured = _clip_read()
            if captured and captured != _SENTINEL:
                log(f"[text_bridge] captured {len(captured)} chars via Ctrl+C")
                return captured, original

    if wayland:
        primary = _primary_read().strip()
        if primary and primary != _SENTINEL:
            log(f"[text_bridge] captured {len(primary)} chars from PRIMARY (fallback)")
            return primary, original

    _clip_write(original)
    log("[text_bridge] no text captured — highlight text, keep focus, retry")
    return None


def _clipboard_safe_to_restore(original: str, captured: str, enhanced: str) -> bool:
    """Skip restoring huge/tutorial clipboards — they caused accidental second pastes."""
    if not original.strip():
        return False
    if len(original) > max(len(captured) * 2, len(enhanced) * 2, 2000):
        return False
    lower = original.lower()
    if any(m in lower for m in ("setup.py", "twine upload", "transformers", "```")):
        return False
    return True


def paste_text(
    enhanced: str,
    original_clipboard: str,
    captured: str = "",
) -> bool:
    """
    Paste *enhanced* once over the current selection (Ctrl+V).
    Returns True when paste key injection succeeded.
    """
    try:
        _clip_write(enhanced)
    except Exception as exc:
        log(f"[text_bridge] clipboard write failed: {exc}")
        return False

    time.sleep(0.12)
    mod, char = _paste_combo()
    if not _tap(mod, char):
        log("[text_bridge] Ctrl+V simulation failed — is ydotoold running?")
        return False
    time.sleep(0.25)

    # Keep PRIMARY in sync so a duplicate hotkey cannot re-read old selection.
    _sync_primary(enhanced)

    # Restore clipboard only when it is small and not old AI/tutorial junk.
    if _clipboard_safe_to_restore(original_clipboard, captured, enhanced):
        try:
            _clip_write(original_clipboard)
        except Exception:
            pass
    return True
