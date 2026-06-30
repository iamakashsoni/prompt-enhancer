"""
System tray icon and menu using pystray + Pillow.
The icon is generated programmatically — no external asset needed.
"""
import threading

import pystray
from PIL import Image, ImageDraw, ImageFont
from pystray import Menu
from pystray import MenuItem as Item

import autostart

# ── icon factory ────────────────────────────────────────────────────────────

_COLORS = {
    "idle":       ("#1a1a2e", "#e94560"),
    "processing": ("#1a1a2e", "#f5a623"),
    "success":    ("#1a1a2e", "#27ae60"),
    "error":      ("#1a1a2e", "#e74c3c"),
}


def _make_icon(state: str = "idle", size: int = 64) -> Image.Image:
    bg, fg = _COLORS.get(state, _COLORS["idle"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill=bg, outline=fg, width=3)
    try:
        font = ImageFont.truetype("arial.ttf", size // 3)
    except Exception:
        font = ImageFont.load_default()
    text = "PE"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 2), text, fill=fg, font=font)
    return img


# X11 WM_NAME only accepts latin-1; pystray passes title there on Linux.
def _x11_safe_title(text: str) -> str:
    for old, new in (
        ("\u2014", "-"),   # em dash
        ("\u2013", "-"),   # en dash
        ("\u2026", "..."), # ellipsis
        ("\u2713", "OK"),  # check mark
    ):
        text = text.replace(old, new)
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── TrayApp ─────────────────────────────────────────────────────────────────

class TrayApp:
    def __init__(self) -> None:
        self._settings_fn = None
        self._quit_fn = None
        self._icon = pystray.Icon(
            name="prompt-enhancer",
            icon=_make_icon("idle"),
            title=_x11_safe_title("Prompt Enhancer - Idle"),
            menu=self._build_menu(),
        )

    # ── callbacks wired by main.py ──────────────────────────────────────

    def set_settings_fn(self, fn) -> None:
        self._settings_fn = fn

    def set_quit_fn(self, fn) -> None:
        self._quit_fn = fn

    # ── status updates (thread-safe) ───────────────────────────────────

    def set_state(self, state: str, detail: str = "") -> None:
        labels = {
            "idle":       "Idle",
            "processing": "Processing…",
            "success":    "Done ✓",
            "error":      "Error",
        }
        label = labels.get(state, state)
        title = f"Prompt Enhancer - {label}"
        if detail:
            title += f": {detail}"
        self._icon.icon  = _make_icon(state)
        self._icon.title = _x11_safe_title(title)

    # ── menu ───────────────────────────────────────────────────────────

    def _build_menu(self) -> Menu:
        return Menu(
            Item("Prompt Enhancer", None, enabled=False),
            Menu.SEPARATOR,
            Item("Settings", self._on_settings, default=True),
            Item("Run at Login", self._on_toggle_autostart,
                 checked=lambda item: autostart.is_enabled()),
            Menu.SEPARATOR,
            Item("Quit", self._on_quit),
        )

    def _on_toggle_autostart(self, icon, item) -> None:
        enabled = autostart.toggle()
        status = "enabled" if enabled else "disabled"
        self.set_state("idle", f"autostart {status}")

    def _on_settings(self, icon, item) -> None:
        if self._settings_fn:
            # Linux uses subprocess (own Tk thread); macOS/Windows run inline in worker.
            import sys
            if sys.platform.startswith("linux"):
                self._settings_fn()
            else:
                threading.Thread(target=self._settings_fn, daemon=True).start()

    def _on_quit(self, icon, item) -> None:
        if self._quit_fn:
            self._quit_fn()
        icon.stop()

    # ── run (blocking — must be called from main thread) ───────────────

    def run(self) -> None:
        self._icon.run()

    def stop(self) -> None:
        self._icon.stop()
