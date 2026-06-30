"""Launch the settings window (subprocess or in-process)."""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

_SETTINGS_LOG = Path.home() / ".cache" / "prompt-enhancer" / "settings.log"


def _log_settings(msg: str) -> None:
    _SETTINGS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _SETTINGS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(msg.rstrip() + "\n")


def run_settings_window() -> None:
    """Entry point for --settings (own process, own Tk main loop)."""
    try:
        from config_ui import SettingsWindow

        SettingsWindow().open()
    except Exception:
        _log_settings(traceback.format_exc())
        raise


def launch_settings_subprocess(on_exit=None, on_error=None) -> None:
    """Open Settings on a worker thread so the tray backend is never blocked."""
    def _run() -> None:
        try:
            run_settings_window()
        except Exception:
            _log_settings(traceback.format_exc())
            if on_error:
                on_error(f"Settings failed — see {_SETTINGS_LOG}")
        finally:
            if on_exit:
                on_exit()

    threading.Thread(target=_run, daemon=True, name="settings-ui").start()
