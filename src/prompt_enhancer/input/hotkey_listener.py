"""
Global hotkey listener — Linux (Wayland via evdev, X11 via pynput).

Design:
- start() runs a restart loop in a daemon thread; survives crashes automatically
- reload() stops the current listener; the loop re-creates it with fresh config
- Lock is NEVER held during join() — eliminates the deadlock in reload()
- Wayland: EvdevGlobalHotkeys reads /dev/input/event* directly (rootless via
  the 'input' group), so hotkeys work even when the focused app is a native
  Wayland client that pynput's X11 backend cannot see.
- X11: falls back to pynput.keyboard.GlobalHotKeys.
- pynput is imported lazily — its import connects to DISPLAY and would crash
  the whole process under systemd when X is unavailable (Wayland-only / early boot).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from prompt_enhancer.core.config import load_config
from prompt_enhancer.platform.evdev_hotkeys import (
    EvdevGlobalHotkeys,
    ensure_session_env,
    prefer_evdev_hotkeys,
)

OnTrigger = Callable[[str], None]


class HotkeyListener:
    def __init__(self, on_trigger: OnTrigger) -> None:
        self._on_trigger = on_trigger
        self._current: Any = None
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

    def _run_evdev(self, hotkeys_cfg: dict[str, str]) -> None:
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
            self._current = hk
        try:
            hk.start()
            hk.join()
        finally:
            with self._lock:
                if self._current is hk:
                    self._current = None

    def _run_pynput(self, mapping: dict[str, Callable]) -> None:
        from pynput import keyboard

        hk = keyboard.GlobalHotKeys(mapping)
        with self._lock:
            self._current = hk
        try:
            hk.start()
            hk.join()
        finally:
            with self._lock:
                if self._current is hk:
                    self._current = None

    def _launch(self) -> None:
        """
        Create and run one GlobalHotKeys instance.
        Blocks until the listener is stopped (via reload() or stop()).
        Lock is released before join() to prevent deadlock with reload().
        """
        ensure_session_env()
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

        if prefer_evdev_hotkeys():
            self._run_evdev(hotkeys_cfg)
            return

        try:
            self._run_pynput(mapping)
        except ImportError as exc:
            # pynput backend probes X at import time — fall back to evdev
            print(
                f"[HotkeyListener] pynput unavailable ({exc!r}) — "
                "falling back to evdev",
                flush=True,
            )
            self._run_evdev(hotkeys_cfg)
