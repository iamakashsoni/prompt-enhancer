"""
Prompt Enhancer — application entry point.

Run: python src/main.py  (or ./run.sh)
     python -m prompt_enhancer
"""
import signal
import sys
import threading
import time
import uuid

import prompt_enhancer.platform.autostart as autostart
from prompt_enhancer.core.logging import log, log_error
from prompt_enhancer.core.config import get_api_key, is_api_enabled, is_welcome_done, load_config
from prompt_enhancer.ui.settings_window import show_welcome_if_needed
from prompt_enhancer.core.enhancer import EnhancementError, capture_looks_corrupted, enhance_text, mode_display_name
from prompt_enhancer.core.health import record_error, record_success, write_health_startup, write_health_stopped
from prompt_enhancer.input.hotkey_listener import HotkeyListener
from prompt_enhancer.ui.settings_launcher import launch_settings_subprocess, run_settings_window
from prompt_enhancer.platform.single_instance import acquire as acquire_single_instance
from prompt_enhancer.platform.single_instance import release as release_single_instance
from prompt_enhancer.input.text_bridge import capture_selected_text, paste_text
from prompt_enhancer.platform.tray import TrayApp
from prompt_enhancer.core.updater import check_async, is_update_required, show_update_dialog
from prompt_enhancer.core.version import __version__
from prompt_enhancer.platform.evdev_hotkeys import is_wayland


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

    # Network diagnostics — log proxy + connectivity state at startup so the
    # user can diagnose "hotkey fires but enhancement times out" issues from
    # the journal without needing to run a separate diagnostic script.
    _log_network_state()

    log(f"Prompt Enhancer v{__version__} running — PE icon is in your system tray.")
    log("Hotkeys: Ctrl+Alt+E=Enhance  Ctrl+Alt+P=Professional")
    if is_wayland():
        log("Wayland: highlight text, keep that window focused, then hotkey.")
    log(
        "Tray (GNOME/Ubuntu): click the PE icon, then choose Settings in the menu. "
        "Or run: ~/.local/share/prompt-enhancer/.venv/bin/python ~/.local/share/prompt-enhancer/src/main.py --settings"
    )

    tray.run()


def _log_network_state() -> None:
    """Log proxy env + NVIDIA API reachability at startup.

    Surfaces the root cause of "hotkey fires but enhancement times out" in the
    journal immediately, instead of making the user wait 60s for a timeout
    and then run a separate diagnostic.
    """
    import os
    import socket
    import urllib.request
    import urllib.error

    proxy_vars = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                  "http_proxy", "https_proxy", "all_proxy", "no_proxy")
    proxies = {v: os.environ.get(v) for v in proxy_vars if os.environ.get(v)}
    if proxies:
        log(f"[net] proxy env detected: {list(proxies.keys())}")
        for k, v in proxies.items():
            log(f"[net]   {k}={v}")
    else:
        log("[net] no proxy env vars set — direct connection")

    # Quick reachability check via urllib (3s timeout — tests DNS+TCP+TLS+HTTP)
    try:
        socket.gethostbyname("integrate.api.nvidia.com")
    except socket.gaierror as exc:
        log(f"[net] DNS resolve integrate.api.nvidia.com FAILED: {exc}")
        return

    try:
        req = urllib.request.Request("https://integrate.api.nvidia.com/v1/models")
        urllib.request.urlopen(req, timeout=3)
        log("[net] NVIDIA /v1/models reachable (200 — public endpoint)")
    except urllib.error.HTTPError as exc:
        log(f"[net] NVIDIA /v1/models reachable (HTTP {exc.code})")
    except urllib.error.URLError as exc:
        reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
        if "timed out" in reason.lower():
            log("[net] NVIDIA /v1/models UNREACHABLE — TCP connect timed out after 3s")
            log("[net]   → if you use a VPN/proxy, ensure HTTPS_PROXY is set")
            log("[net]     in the shell that ran install.sh, then re-run install")
            log("[net]   → or switch to a custom API provider in Settings")
        else:
            log(f"[net] NVIDIA /v1/models unreachable: {reason}")
    except Exception as exc:
        log(f"[net] NVIDIA /v1/models check error: {exc!r}")

    # Also test the actual chat completions endpoint with the openai SDK —
    # this is the same code path the enhancer uses, so it catches issues that
    # urllib can't (httpx proxy handling, SDK auth headers, etc.).
    # Uses a 10s timeout and a 1-token request so it's fast even on slow models.
    try:
        from prompt_enhancer.core.config import resolve_api_endpoint, is_api_enabled, load_config
        from prompt_enhancer.core.enhancer import _get_client
        config = load_config()
        if is_api_enabled(config):
            base_url, api_key = resolve_api_endpoint(config)
            model = config.get("model", "meta/llama-3.3-70b-instruct")
            client = _get_client(api_key, base_url, 10)
            import time as _time
            t0 = _time.monotonic()
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=5,
                temperature=0,
            )
            dt = _time.monotonic() - t0
            reply = (completion.choices[0].message.content or "").strip()
            log(f"[net] NVIDIA chat completions OK ({dt:.1f}s) — model={model}, reply={reply!r}")
        else:
            log("[net] API disabled in config — skipping chat completions test")
    except Exception as exc:
        msg = str(exc)
        log(f"[net] NVIDIA chat completions FAILED: {msg[:200]}")
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            log("[net]   → the model endpoint is reachable but slow/unresponsive")
            log("[net]   → try a smaller model (e.g. meta/llama-3.1-8b-instruct)")
            log("[net]   → or increase timeout in Settings")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        run_settings_window()
        sys.exit(0)
    main()
