"""
Prompt Enhancer — AI-powered text enhancement hotkey tool for Linux.

Package layout:
    prompt_enhancer/
        core/        pure logic (config, enhancer, prompts, version, logging, updater, health)
        platform/    Linux platform layer (autostart, evdev, tray, runtime, single_instance)
        input/       keyboard hotkeys + clipboard text bridge
        ui/          settings window, async ui, settings launcher
        main.py      application orchestration
        __main__.py  enables `python -m prompt_enhancer`
"""
from prompt_enhancer.core.version import __version__  # noqa: F401

__all__ = ["__version__"]
