"""
Prompt Enhancer — entry point.

Run: python main.py  (or ./run.sh)
"""
import signal
import sys
import threading
import time
import uuid

import autostart
from app_log import log, log_error
from config import get_api_key, is_api_enabled, is_welcome_done, load_config
from config_ui import show_welcome_if_needed
from enhancer import EnhancementError, capture_looks_corrupted, enhance_text, mode_display_name
from health import record_error, record_success, write_health_startup, write_health_stopped
from hotkey_listener import HotkeyListener
from settings_launcher import launch_settings_subprocess, run_settings_window
from single_instance import acquire as acquire_single_instance
from single_instance import release as release_single_instance
from text_bridge import capture_selected_text, paste_text
from tray import TrayApp
from updater import check_async, is_update_required, show_update_dialog
from version import __version__

if sys.platform.startswith("linux"):
    from linux_input import is_wayland
else:
    def is_wayland() -> bool:
        return False


_enhancement_lock = threading.Semaphore(1)
_last_trigger_at = 0.0
# 3s is enough to prevent accidental double-press while staying well below
# NVIDIA's free-tier rate limit (~40 req/min → 1.5s floor). The lock itself
# already serializes triggers, so this is purely a UX guard.
_TRIGGER_DEBOUNCE_S = 3.0
_busy_until = 0.0


def _handle_trigger(mode: str, tray: TrayApp) -> None:
    global _last_trigger_at, _busy_until

    request_id = uuid.uuid4().hex[:8]

    if is_update_required():
        log(f"[{request_id}] {mode}: skipped (update required)")
        tray.set_state("error", "Update required — open Settings")
        time.sleep(3)
        tray.set_state("idle")
        return

    if not _enhancement_lock.acquire(blocking=False):
        log(f"[{request_id}] {mode}: skipped (already processing)")
        return

    now = time.monotonic()
    if now < _busy_until or now - _last_trigger_at < _TRIGGER_DEBOUNCE_S:
        _enhancement_lock.release()
        log(f"[{request_id}] {mode}: skipped (debounced)")
        return
    _last_trigger_at = now

    log(f"[{request_id}] {mode}: hotkey fired", request_id=request_id)
    started = time.monotonic()

    # Brief settle so the hotkey key-up event clears before we simulate Ctrl+C.
    # 40ms is enough on Windows/macOS/X11; Wayland's ydotool path has its own
    # queueing so this is a safety margin only.
    time.sleep(0.04)

    try:
        result = capture_selected_text()
        if result is None:
            log(f"[{request_id}] {mode}: no text captured", request_id=request_id)
            tray.set_state("error", "no text selected")
            time.sleep(2)
            tray.set_state("idle")
            return

        captured, original_clipboard = result

        if not captured.strip():
            log(f"[{request_id}] {mode}: empty selection", request_id=request_id)
            tray.set_state("error", "empty selection")
            time.sleep(2)
            tray.set_state("idle")
            return

        corrupt = capture_looks_corrupted(captured)
        if corrupt:
            log(f"[{request_id}] {mode}: rejected selection", request_id=request_id)
            tray.set_state("error", corrupt[:60])
            time.sleep(3)
            tray.set_state("idle")
            return

        config = load_config()
        if not is_api_enabled(config):
            log(f"[{request_id}] {mode}: api disabled", request_id=request_id)
            tray.set_state("error", "Cloud API disabled — open Settings")
            record_error("api disabled", request_id)
            time.sleep(3)
            tray.set_state("idle")
            return

        display = mode_display_name(mode, config)
        tray.set_state("processing", display)
        log(
            f"[{request_id}] {mode}: processing {len(captured)} chars",
            request_id=request_id,
        )

        try:
            enhanced = enhance_text(captured, mode, config)
            pasted = paste_text(enhanced, original_clipboard, captured)
            duration_ms = int((time.monotonic() - started) * 1000)
            if pasted:
                log(
                    f"[{request_id}] {mode}: ok in={len(captured)} "
                    f"out={len(enhanced)} duration_ms={duration_ms}",
                    request_id=request_id,
                )
                tray.set_state("success", display)
                record_success(request_id, duration_ms)
                time.sleep(1.0)  # brief green flash — lock held only for visual feedback
            else:
                log(f"[{request_id}] {mode}: paste failed", request_id=request_id)
                tray.set_state("error", "paste failed — is ydotoold running?")
                record_error("paste failed", request_id)
                time.sleep(2.5)  # time to read the error message
        except EnhancementError as exc:
            log(f"[{request_id}] {mode}: {exc}", request_id=request_id)
            tray.set_state("error", str(exc)[:60])
            record_error(str(exc)[:200], request_id)
            time.sleep(3)
        except Exception as exc:
            log_error(
                f"[{request_id}] {mode}: unexpected error: {exc!r}",
                request_id=request_id,
            )
            tray.set_state("error", "Enhancement failed — see logs")
            record_error("unexpected error", request_id)
            time.sleep(3)

        tray.set_state("idle")

    finally:
        _busy_until = time.monotonic() + _TRIGGER_DEBOUNCE_S
        _enhancement_lock.release()


def main() -> None:
    acquire_single_instance()

    if not get_api_key():
        log(
            "No NVIDIA API key found. "
            "Right-click tray → Settings, or get a key at https://build.nvidia.com"
        )

    tray = TrayApp()
    listener = HotkeyListener(on_trigger=lambda mode: _handle_trigger(mode, tray))

    def _open_settings() -> None:
        def _settings_error(detail: str) -> None:
            tray.set_state("error", detail[:60])

        launch_settings_subprocess(
            on_exit=listener.reload,
            on_error=_settings_error,
        )

    tray.set_settings_fn(_open_settings)

    def _quit() -> None:
        listener.stop()
        write_health_stopped()
        tray.stop()
        release_single_instance()
        sys.exit(0)

    def _shutdown(signum, _frame) -> None:
        log(f"Shutting down (signal {signum})")
        listener.stop()
        write_health_stopped()
        release_single_instance()
        tray.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    tray.set_quit_fn(_quit)

    threading.Thread(target=listener.start, daemon=True, name="hotkey-listener").start()

    def _on_update_checked(info) -> None:
        if info is None:
            return
        action = show_update_dialog(info)
        if is_update_required() and action in ("quit", "download"):
            tray.set_state("error", "Update required")
            if action == "quit":
                _quit()

    check_async(_on_update_checked)

    if not is_welcome_done():
        threading.Thread(target=show_welcome_if_needed, daemon=True, name="welcome").start()

    write_health_startup()
    log(f"Prompt Enhancer v{__version__} running — PE icon is in your system tray.")
    log("Hotkeys: Ctrl+Alt+E=Enhance  P=Professional  S=Shorten  X=Expand  C=Casual")
    if sys.platform.startswith("linux"):
        if is_wayland():
            log("Wayland: highlight text, keep that window focused, then hotkey.")
        log(
            "Tray (GNOME/Ubuntu): click the PE icon, then choose Settings in the menu. "
            "Or run: ~/.local/share/prompt-enhancer/.venv/bin/python ~/.local/share/prompt-enhancer/src/main.py --settings"
        )

    tray.run()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        run_settings_window()
        sys.exit(0)
    main()
