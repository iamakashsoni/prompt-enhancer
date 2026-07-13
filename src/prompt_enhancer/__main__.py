"""Entry point for `python -m prompt_enhancer`."""
import sys

from prompt_enhancer.main import main
from prompt_enhancer.ui.settings_launcher import run_settings_window

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        run_settings_window()
        sys.exit(0)
    main()
