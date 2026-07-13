"""
Thin entry point — preserves the historical `src/main.py` path so existing
install.sh, run.sh, and systemd unit ExecStart lines keep working without
modification.

Real code lives in the `prompt_enhancer` package. Run with:
    python src/main.py                # app
    python src/main.py --settings     # settings window
    python src/main.py enable         # enable autostart (backward compat)
    python src/main.py disable        # disable autostart
    python src/main.py status         # check autostart status
    python -m prompt_enhancer         # equivalent to above
"""
import sys
import os

# Ensure the package is importable when running directly from source.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prompt_enhancer.main import main
from prompt_enhancer.ui.settings_launcher import run_settings_window

if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--settings":
            run_settings_window()
            sys.exit(0)
        # Backward compat: src/autostart.py used to exist as a standalone CLI.
        # Now it lives at prompt_enhancer.platform.autostart, but install.sh
        # and user muscle memory may still pass enable/disable/status.
        if arg in ("enable", "disable", "status", "toggle"):
            from prompt_enhancer.platform import autostart
            if arg == "enable":
                autostart.enable()
                print("Autostart enabled.")
            elif arg == "disable":
                autostart.disable()
                print("Autostart disabled.")
            elif arg == "status":
                print(f"Autostart is {'ENABLED' if autostart.is_enabled() else 'DISABLED'}.")
            elif arg == "toggle":
                state = autostart.toggle()
                print(f"Autostart {'enabled' if state else 'disabled'}.")
            sys.exit(0)
    main()
