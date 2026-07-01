"""
Global hotkey listener using pynput.

Design:
- start() runs a restart loop in a daemon thread; survives crashes automatically
- reload() stops the current listener; the loop re-creates it with fresh config
- Lock is NEVER held during join() — eliminates the deadlock in reload()
- On Windows, uses keyboard.Listener with suppress=True to prevent the
  hotkey combo from reaching the focused app (e.g. Ctrl+Alt+E producing ē)
"""
import sys
import threading
import time
from typing import Callable

from pynput import keyboard
from pynput.keyboard import Key, KeyCode

from config import load_config

if sys.platform.startswith("linux"):
    from linux_input import EvdevGlobalHotkeys, is_wayland
else:
    def is_wayland() -> bool:
        return False

    EvdevGlobalHotkeys = None  # type: ignore[misc,assignment]

OnTrigger = Callable[[str], None]


class HotkeyListener:
    def __init__(self, on_trigger: OnTrigger) -> None:
        self._on_trigger = on_trigger
        self._current: keyboard.GlobalHotKeys | None = None
        self._lock = threading.Lock()
        self._stopped = False

    # ── public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Blocking restart loop — run in a daemon thread.
        Automatically restarts the listener after any crash or reload.
        """
        while not self._stopped:
            try:
                self._launch()
            except Exception as exc:
                if self._stopped:
                    break
                print(f"[HotkeyListener] error: {exc!r} — restarting in 3 s…", flush=True)
                time.sleep(3)

    def reload(self) -> None:
        """
        Stop the current listener so the restart loop re-creates it with
        updated config. Returns immediately — does NOT block.
        """
        with self._lock:
            hk = self._current
        if hk:
            stop = getattr(hk, "stop", None)
            if callable(stop):
                stop()

    def stop(self) -> None:
        """Permanently stop — called on app quit."""
        self._stopped = True
        with self._lock:
            hk = self._current
        if hk:
            stop = getattr(hk, "stop", None)
            if callable(stop):
                stop()

    # ── internal ─────────────────────────────────────────────────────────────

    def _launch(self) -> None:
        """
        Create and run one GlobalHotKeys instance.
        Blocks until the listener is stopped (via reload() or stop()).
        Lock is released before join() to prevent deadlock with reload().
        """
        config = load_config()
        hotkeys_cfg: dict[str, str] = config.get("hotkeys", {})

        mapping: dict[str, Callable] = {}
        for mode, combo in hotkeys_cfg.items():
            combo = combo.strip()
            if not combo:
                continue
            def _make_cb(m: str) -> Callable:
                def cb() -> None:
                    threading.Thread(
                        target=self._on_trigger,
                        args=(m,),
                        daemon=True,
                    ).start()
                return cb
            mapping[combo] = _make_cb(mode)

        if not mapping:
            # No hotkeys configured — idle until reload
            while not self._stopped:
                time.sleep(1)
            return

        if sys.platform.startswith("linux") and is_wayland() and EvdevGlobalHotkeys:
            # Evdev already debounces and runs cb on its own thread — no double-wrap.
            def _make_evdev_cb(m: str) -> Callable:
                def cb() -> None:
                    self._on_trigger(m)
                return cb

            evdev_mapping: dict[str, Callable] = {}
            for mode, combo in hotkeys_cfg.items():
                combo = combo.strip()
                if combo:
                    evdev_mapping[combo] = _make_evdev_cb(mode)
            hk = EvdevGlobalHotkeys(evdev_mapping)
            with self._lock:
                self._current = hk  # type: ignore[assignment]
            try:
                hk.start()
                hk.join()
            finally:
                with self._lock:
                    if self._current is hk:
                        self._current = None
            return

        if sys.platform == "win32":
            # Windows: use suppressed listener to prevent Ctrl+Alt+E → ē
            self._launch_win_suppressed()
            return

        hk = keyboard.GlobalHotKeys(mapping)

        # Store reference BEFORE starting, under the lock
        with self._lock:
            self._current = hk

        try:
            hk.start()
            hk.join()   # ← blocks here; lock is NOT held → reload() can run safely
        finally:
            with self._lock:
                if self._current is hk:
                    self._current = None

    def _launch_win_suppressed(self) -> None:
        """Windows: use Listener with suppress=True to prevent hotkey combo
        from reaching the focused app (Ctrl+Alt+E → ē, Ctrl+Shift+E → inspect).

        GlobalHotKeys doesn't support suppression, so we build a custom
        state machine that tracks modifier keys and fires callbacks when
        the full combo is pressed — while suppressing the event.
        """
        config = load_config()
        hotkeys_cfg: dict[str, str] = config.get("hotkeys", {})

        # Parse combos into {frozenset(mods): {key_char: callback}}
        parsed: dict[frozenset, dict[str, Callable]] = {}
        for mode, combo in hotkeys_cfg.items():
            combo = combo.strip()
            if not combo:
                continue
            mods: set = set()
            key_char: str | None = None
            for token in combo.split("+"):
                token = token.strip().strip("<>")
                if token in ("ctrl", "control"):
                    mods.add("ctrl")
                elif token in ("alt",):
                    mods.add("alt")
                elif token in ("shift",):
                    mods.add("shift")
                elif token in ("cmd", "super", "win"):
                    mods.add("cmd")
                elif len(token) == 1:
                    key_char = token.lower()
            if key_char and mods:
                def _make_cb(m: str) -> Callable:
                    def cb() -> None:
                        threading.Thread(
                            target=self._on_trigger, args=(m,), daemon=True
                        ).start()
                    return cb
                mod_fs = frozenset(mods)
                if mod_fs not in parsed:
                    parsed[mod_fs] = {}
                parsed[mod_fs][key_char] = _make_cb(mode)

        if not parsed:
            while not self._stopped:
                time.sleep(1)
            return

        pressed_mods: set = set()

        def on_press(key):
            # Track modifiers
            if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
                pressed_mods.add("ctrl")
                return False  # suppress
            elif key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
                pressed_mods.add("alt")
                return False
            elif key in (Key.shift, Key.shift_l, Key.shift_r):
                pressed_mods.add("shift")
                return False
            elif key in (Key.cmd, Key.cmd_l, Key.cmd_r):
                pressed_mods.add("cmd")
                return False

            # Check if this key + current mods matches a hotkey
            if isinstance(key, KeyCode) and key.char:
                char = key.char.lower()
                mod_fs = frozenset(pressed_mods)
                if mod_fs in parsed and char in parsed[mod_fs]:
                    parsed[mod_fs][char]()
                    return False  # suppress the key
            # Suppress any key while modifiers are held (prevents ē, inspect, etc.)
            if pressed_mods:
                return False
            return None  # let other keys through

        def on_release(key):
            if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
                pressed_mods.discard("ctrl")
            elif key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
                pressed_mods.discard("alt")
            elif key in (Key.shift, Key.shift_l, Key.shift_r):
                pressed_mods.discard("shift")
            elif key in (Key.cmd, Key.cmd_l, Key.cmd_r):
                pressed_mods.discard("cmd")
            return None  # don't suppress releases

        listener = keyboard.Listener(
            on_press=on_press, on_release=on_release, suppress=True
        )

        with self._lock:
            self._current = listener

        try:
            listener.start()
            listener.join()
        finally:
            with self._lock:
                if self._current is listener:
                    self._current = None
