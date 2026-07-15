"""
Linux input helpers — Wayland vs X11.

On Wayland, pynput's X11 backend cannot capture global hotkeys or inject keys
into native apps. We use evdev for hotkeys (input group) and ydotool for
copy/paste when available.
"""
from __future__ import annotations

import os
import select
import subprocess
import sys
import threading
import time
from typing import Callable


def ensure_session_env() -> None:
    """Fill DISPLAY / WAYLAND_DISPLAY / XDG_SESSION_TYPE from the live session.

    systemd user units often bake DISPLAY=:0 at install time. That breaks when
    the session is Wayland-only, X is not on :0 yet, or the unit was installed
    over SSH. Discover sockets under XDG_RUNTIME_DIR /tmp instead of trusting
    a stale hardcoded DISPLAY.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    os.environ.setdefault("XDG_RUNTIME_DIR", runtime)

    wayland = os.environ.get("WAYLAND_DISPLAY", "").strip()
    if not wayland:
        for name in ("wayland-0", "wayland-1"):
            if os.path.exists(os.path.join(runtime, name)):
                os.environ["WAYLAND_DISPLAY"] = name
                wayland = name
                break

    display = os.environ.get("DISPLAY", "").strip()
    if not display:
        for n in range(0, 5):
            sock = f"/tmp/.X11-unix/X{n}"
            if os.path.exists(sock):
                os.environ["DISPLAY"] = f":{n}"
                display = f":{n}"
                break
    elif display in (":0", ":0.0") and not os.path.exists("/tmp/.X11-unix/X0"):
        # Stale DISPLAY=:0 from systemd — drop it so pynput is not forced onto
        # a dead socket when Wayland (or another X display) is the real session.
        if wayland:
            os.environ.pop("DISPLAY", None)
            display = ""
        else:
            for n in range(1, 5):
                sock = f"/tmp/.X11-unix/X{n}"
                if os.path.exists(sock):
                    os.environ["DISPLAY"] = f":{n}"
                    display = f":{n}"
                    break

    session = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if not session:
        if wayland:
            os.environ["XDG_SESSION_TYPE"] = "wayland"
        elif display:
            os.environ["XDG_SESSION_TYPE"] = "x11"


def is_wayland() -> bool:
    ensure_session_env()
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "x11":
        return False
    if session == "wayland":
        return True
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    for name in ("wayland-0", "wayland-1"):
        if os.path.exists(os.path.join(runtime, name)):
            return True
    return False


def prefer_evdev_hotkeys() -> bool:
    """Use evdev when Wayland, or when no usable X display exists for pynput."""
    if is_wayland():
        return True
    ensure_session_env()
    display = os.environ.get("DISPLAY", "").strip()
    if not display:
        return True
    # ":0" / ":0.0" → X0; ":1.0" → X1
    num = display.lstrip(":").split(".", 1)[0]
    if not num.isdigit():
        return True
    return not os.path.exists(f"/tmp/.X11-unix/X{num}")


def simulate_key_combo(mod_char: tuple[str, str]) -> bool:
    """Press mod+char (e.g. ctrl+c). Uses ydotool on Wayland, pynput on X11."""
    mod, char = mod_char
    mod_name = "ctrl" if mod in ("ctrl", "control") else mod
    if is_wayland():
        combo = f"{mod_name}+{char.lower()}"
        # Try ydotool directly first
        for cmd_prefix in [
            ["ydotool"],
            ["sudo", "-n", "ydotool"],  # non-interactive sudo fallback
        ]:
            try:
                proc = subprocess.run(
                    cmd_prefix + ["key", "--delay", "50", combo],
                    check=False,
                    timeout=2,
                    capture_output=True,
                )
                if proc.returncode == 0:
                    return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                break
        from prompt_enhancer.core.logging import log
        log("[evdev] ydotool key failed — checking /dev/uinput access...")
        if not os.access("/dev/uinput", os.W_OK):
            log("[evdev] /dev/uinput not writable. User needs input group + re-login.")
        return False

    # X11 path — pynput Controller
    from pynput.keyboard import Controller, Key
    key = Key.ctrl if mod_name == "ctrl" else Key.cmd
    kb = Controller()
    with kb.pressed(key):
        kb.press(char)
        kb.release(char)
    return True


def simulate_key_repeat(key_spec: str, repeat: int, key_delay_ms: int = 1) -> None:
    """Send a ydotool key sequence *repeat* times (Wayland only)."""
    if repeat <= 0:
        return
    if not (is_wayland()):
        return
    repeat = min(repeat, 4000)
    try:
        subprocess.run(
            [
                "ydotool",
                "key",
                "--delay",
                "50",
                "--key-delay",
                str(key_delay_ms),
                "--repeat",
                str(repeat),
                key_spec,
            ],
            check=False,
            timeout=max(5, repeat // 20),
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _parse_pynput_combo(combo: str) -> tuple[frozenset[str], str] | None:
    """Parse '<ctrl>+<alt>+e' -> ({'ctrl', 'alt'}, 'e')."""
    combo = combo.strip().lower()
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods: set[str] = set()
    key: str | None = None
    for part in parts:
        if part.startswith("<") and part.endswith(">"):
            name = part[1:-1]
            if name in ("ctrl", "control"):
                mods.add("ctrl")
            elif name in ("cmd", "super", "win"):
                mods.add("super")
            elif name in ("alt", "shift"):
                mods.add(name)
            else:
                return None
        elif len(part) == 1 and part.isalnum():
            key = part
        else:
            return None
    if not key:
        return None
    return frozenset(mods), key


def _evdev_key(name: str) -> int | None:
    from evdev import ecodes

    if len(name) == 1 and name.isalpha():
        code = getattr(ecodes, f"KEY_{name.upper()}", None)
        return code
    return None


def _evdev_mod_codes(mod: str) -> tuple[int, ...]:
    from evdev import ecodes

    table = {
        "ctrl": (ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL),
        "alt": (ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT),
        "shift": (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT),
        "super": (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA),
    }
    return table.get(mod, ())


def _keyboard_devices():
    import evdev

    skip = (
        "consumer control",
        "power button",
        "sleep button",
        "video bus",
        "acpi",
        "hotkeys",
        "wireless radio",
        "gpio keys",
        "ydotool",
        "virtual device",
        "virtual keyboard",
    )
    out = []
    denied = 0
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except (OSError, PermissionError):
            denied += 1
            continue
        name = (dev.name or "").lower()
        if any(token in name for token in skip):
            dev.close()
            continue
        caps = dev.capabilities().get(evdev.ecodes.EV_KEY, [])
        if evdev.ecodes.KEY_A in caps and evdev.ecodes.KEY_ENTER in caps:
            out.append(dev)
        else:
            dev.close()
    if not out and denied > 0:
        from prompt_enhancer.core.logging import log_error
        log_error(
            f"EvdevGlobalHotkeys: {denied} input devices found but ALL were "
            f"permission-denied. User is not in the 'input' group. "
            f"Fix: sudo usermod -aG input $USER, then log out and back in."
        )
    elif not out:
        from prompt_enhancer.core.logging import log_error
        log_error(
            "EvdevGlobalHotkeys: no keyboard devices found at all. "
            "No /dev/input/event* devices available."
        )
    return out


class EvdevGlobalHotkeys:
    """Block until stopped; invoke callbacks on global hotkey press."""

    # Same physical keypress often appears on 2+ /dev/input nodes; coalesce here.
    _FIRE_DEBOUNCE_S = 5.0

    def __init__(self, mapping: dict[str, Callable[[], None]]) -> None:
        self._mapping = mapping
        self._combos: list[tuple[frozenset[str], str, Callable[[], None]]] = []
        for combo, cb in mapping.items():
            parsed = _parse_pynput_combo(combo)
            if parsed:
                self._combos.append((*parsed, cb))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fire_lock = threading.Lock()
        self._last_fire_mono = 0.0
        self._devices: list = []  # track open evdev devices so we can close on stop

    def stop(self) -> None:
        self._stop.set()
        # Close evdev file descriptors immediately so reload does not leak FDs.
        for dev in self._devices:
            try:
                dev.close()
            except OSError:
                pass
        self._devices.clear()

    def join(self) -> None:
        if self._thread:
            self._thread.join()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="evdev-hotkeys"
        )
        self._thread.start()

    def _pressed_mods(self, pressed: set[int]) -> set[str]:

        mods: set[str] = set()
        for name in ("ctrl", "alt", "shift", "super"):
            if any(code in pressed for code in _evdev_mod_codes(name)):
                mods.add(name)
        return mods

    def _run(self) -> None:
        from evdev import ecodes

        devices = _keyboard_devices()
        if not devices:
            from prompt_enhancer.core.logging import log
            log("[EvdevGlobalHotkeys] no keyboard devices — hotkeys disabled")
            return

        # Track opened devices so stop() can release their FDs.
        self._devices = list(devices)

        pressed: set[int] = set()
        names = ", ".join(repr(d.name) for d in devices)
        from prompt_enhancer.core.logging import log
        log(f"[EvdevGlobalHotkeys] listening on Wayland: {names}")

        while not self._stop.is_set():
            try:
                r, _, _ = select.select(devices, [], [], 0.2)
            except (OSError, ValueError):
                break
            for dev in r:
                try:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        if event.value == 1:
                            pressed.add(event.code)
                        elif event.value == 0:
                            pressed.discard(event.code)
                        elif event.value != 2:
                            continue

                        if event.value != 1:
                            continue

                        active_mods = self._pressed_mods(pressed)
                        for req_mods, key_char, cb in self._combos:
                            key_code = _evdev_key(key_char)
                            if key_code is None or event.code != key_code:
                                continue
                            if active_mods != set(req_mods):
                                continue
                            now = time.monotonic()
                            with self._fire_lock:
                                if now - self._last_fire_mono < self._FIRE_DEBOUNCE_S:
                                    break
                                self._last_fire_mono = now
                            threading.Thread(target=cb, daemon=True).start()
                            break  # one callback per physical keypress
                except (OSError, BlockingIOError):
                    continue
