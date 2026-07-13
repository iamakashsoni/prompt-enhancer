"""
Settings GUI built with customtkinter.
Opens in its own window from the system tray.
"""
import sys
import uuid
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import messagebox

import customtkinter as ctk

import prompt_enhancer.platform.autostart as autostart
from prompt_enhancer.ui.async_ui import try_deliver_future
from prompt_enhancer.core.config import (
    API_PROVIDER_CUSTOM,
    API_PROVIDER_DISABLED,
    API_PROVIDER_NVIDIA,
    API_PROVIDER_OLLAMA,
    DEFAULT_MODEL,
    NVIDIA_BASE_URL,
    OLLAMA_DEFAULT_URL,
    OBSOLETE_MODELS,
    fetch_ollama_models,
    get_api_key,
    is_api_enabled,
    is_welcome_done,
    load_config,
    mark_welcome_done,
    models_for_settings,
    save_config,
    set_api_key,
    validate_api_key,
    validate_custom_base_url,
    validate_custom_prompt,
)
from prompt_enhancer.core.enhancer import MODE_LABELS, test_connection
from prompt_enhancer.core.version import PORTFOLIO_URL, __version__
from prompt_enhancer.platform.evdev_hotkeys import is_wayland

_PROVIDER_OPTIONS = (
    (API_PROVIDER_NVIDIA, "NVIDIA Cloud"),
    (API_PROVIDER_OLLAMA, "Ollama (local or remote)"),
    (API_PROVIDER_CUSTOM, "Custom endpoint (vLLM, LM Studio, …)"),
    (API_PROVIDER_DISABLED, "Disabled (air-gap)"),
)
_PROVIDER_LABEL_TO_ID = {label: pid for pid, label in _PROVIDER_OPTIONS}
_PROVIDER_ID_TO_LABEL = {pid: label for pid, label in _PROVIDER_OPTIONS}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_BUILTIN_MODES = list(MODE_LABELS.keys())


def _duplicate_hotkeys(hotkeys: dict[str, str]) -> str | None:
    """Return the first duplicated combo string, or None if all unique."""
    seen: dict[str, str] = {}
    for mode, combo in hotkeys.items():
        combo = combo.strip().lower()
        if not combo:
            continue
        if combo in seen:
            return combo
        seen[combo] = mode
    return None

# ══════════════════════════════════════════════════════════════════════════════
#  HotkeyEntry — built-in hotkey row widget
# ══════════════════════════════════════════════════════════════════════════════

class HotkeyEntry(ctk.CTkFrame):
    """A row: label + entry for one built-in hotkey combo."""

    def __init__(self, parent, mode: str, label: str, current: str):
        super().__init__(parent, fg_color="transparent")
        self.mode = mode
        ctk.CTkLabel(self, text=f"{label}:", width=130, anchor="w").pack(
            side="left", padx=(0, 8))
        self._var = ctk.StringVar(value=current)
        ctk.CTkEntry(self, textvariable=self._var, width=200).pack(side="left")
        ctk.CTkLabel(
            self,
            text="e.g. <ctrl>+<alt>+e",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(8, 0))

    @property
    def value(self) -> str:
        return self._var.get().strip()


# ══════════════════════════════════════════════════════════════════════════════
#  SettingsWindow
# ══════════════════════════════════════════════════════════════════════════════

class SettingsWindow:
    def __init__(self, on_save=None):
        self._on_save = on_save
        self._win: ctk.CTk | None = None
        self._scroll: ctk.CTkScrollableFrame | None = None
        self._test_mode_menu: ctk.CTkOptionMenu | None = None

    # ── open ─────────────────────────────────────────────────────────────────

    def open(self) -> None:
        try:
            if self._win and self._win.winfo_exists():
                self._win.lift()
                self._win.focus_force()
                return
        except Exception:
            self._win = None

        config = load_config()  # migrates obsolete model ids; model list uses TTL cache
        hotkeys_cfg: dict = config.get("hotkeys", {})

        win = ctk.CTk()
        win.title("Prompt Enhancer — Settings")
        win.geometry("600x720")
        win.minsize(520, 600)
        win.resizable(True, True)
        self._win = win

        pad = {"padx": 20, "pady": 4}

        # ── Header (compact) ───────────────────────────────────────────────
        hdr = ctk.CTkFrame(win, corner_radius=0, fg_color="#1a1a2e", height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)  # keep fixed height
        ctk.CTkLabel(
            hdr,
            text="⚡ Prompt Enhancer",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#e94560",
        ).pack(pady=10)

        scroll = ctk.CTkScrollableFrame(win)
        scroll.pack(fill="both", expand=True, padx=8, pady=8)
        self._scroll = scroll

        # Bind mouse wheel scrolling (CTkScrollableFrame doesn't do this by default on Linux)
        def _on_mousewheel(event):
            scroll._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_button4(event):
            scroll._parent_canvas.yview_scroll(-1, "units")
        def _on_button5(event):
            scroll._parent_canvas.yview_scroll(1, "units")
        win.bind("<MouseWheel>", _on_mousewheel)
        win.bind("<Button-4>", _on_button4)
        win.bind("<Button-5>", _on_button5)

        # ════════════════════════════════════════════════════════════════════
        #  Section 1: API Provider (conditional URL fields)
        # ════════════════════════════════════════════════════════════════════
        self._section(scroll, "API Provider")
        provider_id = config.get("api_provider", API_PROVIDER_NVIDIA)
        self._api_provider_var = ctk.StringVar(
            value=_PROVIDER_ID_TO_LABEL.get(provider_id, _PROVIDER_OPTIONS[0][1]),
        )
        self._provider_menu = ctk.CTkOptionMenu(
            scroll,
            variable=self._api_provider_var,
            values=[label for _, label in _PROVIDER_OPTIONS],
            width=400,
            command=self._on_provider_change,
        )
        self._provider_menu.pack(anchor="w", **pad)

        # Ollama URL + Fetch (conditional — only visible when Ollama selected)
        self._ollama_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._ollama_url_var = ctk.StringVar(
            value=config.get("ollama_url", OLLAMA_DEFAULT_URL),
        )
        ctk.CTkLabel(
            self._ollama_frame,
            text="Ollama server URL (any network host)",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w")
        ollama_row = ctk.CTkFrame(self._ollama_frame, fg_color="transparent")
        ollama_row.pack(fill="x")
        ctk.CTkEntry(
            ollama_row,
            textvariable=self._ollama_url_var,
            width=290,
            placeholder_text="http://localhost:11434/v1",
        ).pack(side="left")
        self._fetch_ollama_btn = ctk.CTkButton(
            ollama_row, text="Fetch models", width=100,
            command=self._on_fetch_ollama_models,
        )
        self._fetch_ollama_btn.pack(side="left", padx=(6, 0))
        self._ollama_status_label = ctk.CTkLabel(
            self._ollama_frame, text="", text_color="gray60",
            font=ctk.CTkFont(size=11),
        )
        self._ollama_status_label.pack(anchor="w", pady=(2, 0))

        # Custom endpoint URL (conditional — only visible when Custom selected)
        self._custom_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._custom_url_var = ctk.StringVar(
            value=config.get("custom_api_base_url", ""),
        )
        ctk.CTkLabel(
            self._custom_frame,
            text="Custom base URL (OpenAI-compatible)",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w")
        ctk.CTkEntry(
            self._custom_frame,
            textvariable=self._custom_url_var,
            width=400,
            placeholder_text="http://localhost:1234/v1",
        ).pack(anchor="w")

        # API Key (conditional — hidden for Ollama/Custom/Disabled)
        self._apikey_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._api_var = ctk.StringVar(value=get_api_key() or "")
        api_entry = ctk.CTkEntry(
            self._apikey_frame,
            textvariable=self._api_var,
            show="•",
            width=330,
            placeholder_text="nvapi-xxxxxxxxxxxxxxxxxxxx",
        )
        api_entry.pack(side="left")
        self._show_key = False
        toggle_btn = ctk.CTkButton(
            self._apikey_frame, text="Show", width=55,
            command=lambda: self._toggle_key(api_entry, toggle_btn),
        )
        toggle_btn.pack(side="left", padx=(6, 0))
        ctk.CTkButton(
            self._apikey_frame, text="Test", width=55,
            command=self._test_connection,
        ).pack(side="left", padx=(4, 0))

        self._test_label = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=11))
        self._test_label.pack(anchor="w", padx=20)

        # Show/hide conditional frames based on current provider
        self._apply_provider_visibility()

        # ════════════════════════════════════════════════════════════════════
        #  Section 2: AI Model + Timeout (merged)
        # ════════════════════════════════════════════════════════════════════
        self._section(scroll, "AI Model")
        models: list[str] = models_for_settings(config, force_refresh=True)
        current_model = config.get("model", DEFAULT_MODEL)
        if current_model in OBSOLETE_MODELS:
            current_model = DEFAULT_MODEL
        if current_model not in models:
            models = [current_model] + models
        self._model_var = ctk.StringVar(value=current_model)
        self._model_menu = ctk.CTkOptionMenu(
            scroll, variable=self._model_var, values=models, width=400,
        )
        self._model_menu.pack(anchor="w", **pad)

        # Timeout inline with model (saves vertical space)
        timeout_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        timeout_frame.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(
            timeout_frame, text="Timeout (s):",
            font=ctk.CTkFont(size=11), text_color="gray60",
        ).pack(side="left")
        self._timeout_var = ctk.StringVar(value=str(config.get("timeout", 90)))
        ctk.CTkEntry(timeout_frame, textvariable=self._timeout_var, width=60).pack(side="left", padx=(6, 0))

        # ════════════════════════════════════════════════════════════════════
        #  Section 3: Hotkeys
        # ════════════════════════════════════════════════════════════════════
        self._section(scroll, "Hotkeys")
        self._hotkey_rows: list[HotkeyEntry] = []
        for mode in _BUILTIN_MODES:
            row = HotkeyEntry(scroll, mode, MODE_LABELS[mode],
                              hotkeys_cfg.get(mode, ""))
            row.pack(anchor="w", padx=20, pady=2)
            self._hotkey_rows.append(row)

        # Autostart toggle (compact — inline with hotkeys section)
        startup_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        startup_frame.pack(fill="x", padx=20, pady=(6, 0))
        self._autostart_var = ctk.BooleanVar(value=autostart.is_enabled())
        ctk.CTkSwitch(
            startup_frame,
            text="Start at login",
            variable=self._autostart_var,
            onvalue=True, offvalue=False,
            command=self._on_autostart_toggle,
            progress_color="#e94560",
        ).pack(side="left")

        # ════════════════════════════════════════════════════════════════════
        #  Section 4: Quick Test
        # ════════════════════════════════════════════════════════════════════
        self._section(scroll, "Quick Test")
        self._test_input = ctk.CTkTextbox(scroll, height=60, width=500)
        self._test_input.insert("1.0", self._QUICK_TEST_PLACEHOLDER)
        self._test_input.pack(**pad)

        mode_sel_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        mode_sel_frame.pack(fill="x", padx=20, pady=2)
        self._test_mode_var = ctk.StringVar(value=MODE_LABELS["enhance"])
        ctk.CTkLabel(mode_sel_frame, text="Mode:", width=45).pack(side="left")
        self._test_mode_menu = ctk.CTkOptionMenu(
            mode_sel_frame,
            variable=self._test_mode_var,
            values=self._mode_display_labels(),
            width=180,
        )
        self._test_mode_menu.pack(side="left", padx=6)
        ctk.CTkButton(
            mode_sel_frame, text="▶  Enhance", width=110,
            command=self._run_test_enhance,
        ).pack(side="left")

        self._test_output = ctk.CTkTextbox(scroll, height=70, width=500,
                                           state="disabled")
        self._test_output.pack(**pad)

        # ════════════════════════════════════════════════════════════════════
        #  Section 5: About (compact — single line)
        # ════════════════════════════════════════════════════════════════════
        about_frame = ctk.CTkFrame(scroll, fg_color="#1a1a2e", corner_radius=8)
        about_frame.pack(fill="x", padx=10, pady=(8, 4))
        about_row = ctk.CTkFrame(about_frame, fg_color="transparent")
        about_row.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(
            about_row,
            text=f"v{__version__}  ·  © 2026 Akash Soni",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
        ).pack(side="left")
        ctk.CTkButton(
            about_row, text="🔗 Project", width=85, height=24,
            corner_radius=5,
            fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="#e94560", font=ctk.CTkFont(size=10),
            command=lambda: webbrowser.open(PORTFOLIO_URL),
        ).pack(side="right", padx=(4, 0))
        ctk.CTkButton(
            about_row, text="🔄 Updates", width=85, height=24,
            corner_radius=5,
            fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="gray70", font=ctk.CTkFont(size=10),
            command=self._check_updates,
        ).pack(side="right")

        # ── Footer: Save / Reset ──────────────────────────────────────────
        footer = ctk.CTkFrame(win, corner_radius=0, fg_color="#1a1a2e", height=52)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        ctk.CTkFrame(footer, height=1, fg_color="#3a3a4a").pack(fill="x")

        btn_frame = ctk.CTkFrame(footer, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=8)

        ctk.CTkButton(
            btn_frame,
            text="Save & Apply",
            width=120, height=30,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#e94560",
            hover_color="#c73652",
            command=self._save,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_frame, text="Reset", width=80, height=30,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="gray70",
            command=self._reset,
        ).pack(side="right")

        # ── CRITICAL: force scroll region recalculation ────────────────────
        # Without this, CTkScrollableFrame on Linux/Wayland doesn't compute
        # its scrollarea on first paint, so the bottom sections (Model, About)
        # are invisible below the fold with no scrollbar visible.
        win.update_idletasks()
        scroll.update_idletasks()
        scroll._parent_canvas.yview_moveto(0)

        win.mainloop()
        self._win = None

    # ── provider-conditional UI ────────────────────────────────────────────────

    def _apply_provider_visibility(self) -> None:
        """Show/hide URL + API key fields based on the selected provider.

        NVIDIA  → API Key only
        Ollama  → Ollama URL + Fetch button
        Custom  → Custom URL + API Key
        Disabled → nothing
        """
        provider = self._current_provider_id()

        # Ollama URL frame
        if provider == API_PROVIDER_OLLAMA:
            self._ollama_frame.pack(anchor="w", fill="x", padx=20, pady=(4, 2))
        else:
            self._ollama_frame.pack_forget()

        # Custom URL frame
        if provider == API_PROVIDER_CUSTOM:
            self._custom_frame.pack(anchor="w", fill="x", padx=20, pady=(4, 2))
        else:
            self._custom_frame.pack_forget()

        # API Key frame (needed for NVIDIA and Custom)
        if provider in (API_PROVIDER_NVIDIA, API_PROVIDER_CUSTOM):
            self._apikey_frame.pack(anchor="w", fill="x", padx=20, pady=(4, 2))
        else:
            self._apikey_frame.pack_forget()

        # Force scroll region recalculation after visibility change
        if self._win:
            self._win.update_idletasks()

    def _on_provider_change(self, _selection: str) -> None:
        """Called when the provider dropdown changes — update conditional UI."""
        self._apply_provider_visibility()

    # ── mode helpers ───────────────────────────────────────────────────────────

    def _mode_display_labels(self) -> list[str]:
        return [MODE_LABELS[m] for m in _BUILTIN_MODES]


    def _label_to_mode_id(self, label: str) -> str:
        for mid in _BUILTIN_MODES:
            if MODE_LABELS[mid] == label:
                return mid
        return "enhance"









    # ── section label helper ──────────────────────────────────────────────────

    def _section(self, parent, title: str) -> None:
        ctk.CTkFrame(parent, height=1, fg_color="#3a3a4a").pack(
            fill="x", padx=20, pady=(16, 0))
        ctk.CTkLabel(
            parent,
            text=title.upper(),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray60",
        ).pack(anchor="w", padx=20, pady=(8, 2))

    # ── autostart helpers ─────────────────────────────────────────────────────

    def _autostart_label(self) -> str:
        hint = "XDG autostart + systemd user service"
        state = "Enabled" if autostart.is_enabled() else "Disabled"
        return f"{state}  —  {hint}"

    def _on_autostart_toggle(self) -> None:
        try:
            if self._autostart_var.get():
                autostart.enable()
            else:
                autostart.disable()
            self._autostart_status.configure(text=self._autostart_label())
        except Exception as exc:
            messagebox.showerror("Autostart Error", str(exc))
            self._autostart_var.set(autostart.is_enabled())

    def _toggle_key(self, entry: ctk.CTkEntry, btn: ctk.CTkButton) -> None:
        self._show_key = not self._show_key
        entry.configure(show="" if self._show_key else "•")
        btn.configure(text="Hide" if self._show_key else "Show")

    def _current_provider_id(self) -> str:
        label = self._api_provider_var.get()
        return _PROVIDER_LABEL_TO_ID.get(label, API_PROVIDER_NVIDIA)

    def _draft_config(self) -> dict:
        """Unsaved Settings values for Quick Test (model, timeout, custom modes)."""
        config = load_config()
        config["api_provider"] = self._current_provider_id()
        config["custom_api_base_url"] = self._custom_url_var.get().strip()
        try:
            timeout = max(5, int(self._timeout_var.get().strip()))
        except (ValueError, AttributeError):
            timeout = 30
        model = self._model_var.get().strip() or DEFAULT_MODEL
        if model in OBSOLETE_MODELS:
            model = DEFAULT_MODEL
        config["model"] = model
        config["timeout"] = timeout
        return config

    def _run_async(self, work, on_success, on_error) -> None:
        """
        Run blocking *work* in a thread; deliver results on the Tk thread.

        Tkinter is not thread-safe — never call win.after() from worker threads.
        Poll the Future from the Tk event loop instead.
        """
        if not self._win or not self._win.winfo_exists():
            return

        pool = ThreadPoolExecutor(max_workers=1)
        future: Future = pool.submit(work)

        def poll(fut: Future = future) -> None:
            try:
                if not self._win.winfo_exists():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
                if try_deliver_future(fut, on_success, on_error):
                    pool.shutdown(wait=False)
                else:
                    self._win.after(50, lambda f=fut: poll(f))
            except Exception:
                pool.shutdown(wait=False)

        poll()

    # ── ollama model fetch ────────────────────────────────────────────────────

    def _on_fetch_ollama_models(self) -> None:
        """Fetch installed models from the Ollama server and populate the model dropdown."""
        url = self._ollama_url_var.get().strip()
        url_err = validate_custom_base_url(url)
        if url_err:
            self._ollama_status_label.configure(
                text=f"✗ {url_err}", text_color="#e74c3c",
            )
            return

        self._fetch_ollama_btn.configure(state="disabled", text="Fetching…")
        self._ollama_status_label.configure(
            text=f"Fetching models from {url}…", text_color="gray60",
        )

        def on_success(models: list[str]) -> None:
            self._fetch_ollama_btn.configure(state="normal", text="Fetch models")
            if not models:
                self._ollama_status_label.configure(
                    text="✗ No models found. Run: ollama pull llama3.1:8b",
                    text_color="#e74c3c",
                )
                return
            # Populate the model dropdown with the fetched Ollama models
            current = self._model_var.get().strip()
            self._model_menu.configure(values=models)
            if current in models:
                self._model_var.set(current)
            else:
                self._model_var.set(models[0])
            self._ollama_status_label.configure(
                text=f"✓ Found {len(models)} model(s): {', '.join(models[:5])}"
                     + (" …" if len(models) > 5 else ""),
                text_color="#27ae60",
            )

        def on_error(exc: BaseException) -> None:
            self._fetch_ollama_btn.configure(state="normal", text="Fetch models")
            msg = str(exc)
            if "timed out" in msg.lower():
                msg = "Connection timed out — is the Ollama server running and reachable?"
            elif "Connection refused" in msg or "Connection refused" in str(exc):
                msg = "Connection refused — is Ollama running at that URL?"
            self._ollama_status_label.configure(
                text=f"✗ {msg[:120]}", text_color="#e74c3c",
            )

        self._run_async(
            lambda: fetch_ollama_models(url),
            on_success,
            on_error,
        )

    # ── connection test ───────────────────────────────────────────────────────

    def _test_connection(self) -> None:
        self._test_label.configure(text="Testing…", text_color="gray60")
        provider = self._current_provider_id()
        if provider == API_PROVIDER_DISABLED:
            self._test_label.configure(
                text="API is disabled (air-gap mode).",
                text_color="gray60",
            )
            return

        api_key = self._api_var.get().strip() or (get_api_key() or "")
        model = self._model_var.get().strip() or DEFAULT_MODEL
        if model in OBSOLETE_MODELS:
            model = DEFAULT_MODEL
            self._model_var.set(model)

        if provider == API_PROVIDER_CUSTOM:
            base_url = self._custom_url_var.get().strip().rstrip("/")
            url_err = validate_custom_base_url(base_url)
            if url_err:
                self._test_label.configure(text=f"✗ {url_err}", text_color="#e74c3c")
                return
            if not api_key:
                api_key = "not-needed"
        elif provider == API_PROVIDER_OLLAMA:
            base_url = self._ollama_url_var.get().strip().rstrip("/")
            url_err = validate_custom_base_url(base_url)
            if url_err:
                self._test_label.configure(text=f"✗ {url_err}", text_color="#e74c3c")
                return
            api_key = "not-needed"  # Ollama doesn't require auth
        else:
            base_url = NVIDIA_BASE_URL
            err = validate_api_key(api_key)
            if err:
                self._test_label.configure(text=f"✗ {err}", text_color="#e74c3c")
                return

        if api_key and api_key != "not-needed":
            try:
                set_api_key(api_key)
            except RuntimeError as exc:
                self._test_label.configure(text=f"✗ {exc}", text_color="#e74c3c")
                return

        def on_success(result: str) -> None:
            self._test_label.configure(
                text=f"Connected — model replied: {result[:40]}",
                text_color="#27ae60",
            )

        def on_error(exc: BaseException) -> None:
            msg = str(exc)
            if "404" in msg or "Model not found" in msg:
                self._model_var.set(DEFAULT_MODEL)
                msg = (
                    f"{msg} Switched model dropdown to {DEFAULT_MODEL} — "
                    "click Test Connection again."
                )
            self._test_label.configure(text=f"✗ {msg}", text_color="#e74c3c")

        self._run_async(
            lambda: test_connection(api_key, model, base_url=base_url),
            on_success,
            on_error,
        )

    # ── quick test ────────────────────────────────────────────────────────────

    _QUICK_TEST_PLACEHOLDER = "Type some text here and click Enhance to test."

    def _run_test_enhance(self) -> None:
        from enhancer import enhance_text

        text = self._test_input.get("1.0", "end").strip()
        if not text or text == self._QUICK_TEST_PLACEHOLDER:
            self._set_output("Error: Enter your own text in the box above.")
            return

        label = self._test_mode_var.get()
        mode = self._label_to_mode_id(label)
        self._set_output("Processing…")

        config = self._draft_config()
        if not is_api_enabled(config):
            self._set_output("Error: Cloud API is disabled (air-gap mode).")
            return

        api_key = self._api_var.get().strip()
        if api_key:
            try:
                set_api_key(api_key)
            except RuntimeError as exc:
                self._set_output(f"Error: {exc}")
                return
        elif config.get("api_provider") == API_PROVIDER_NVIDIA and not get_api_key():
            self._set_output("Error: Add your NVIDIA API key above first.")
            return

        def on_success(result: str) -> None:
            self._set_output(result)

        def on_error(exc: BaseException) -> None:
            self._set_output(f"Error: {exc}")

        self._run_async(
            lambda: enhance_text(text, mode, config),
            on_success,
            on_error,
        )

    def _set_output(self, text: str) -> None:
        self._test_output.configure(state="normal")
        self._test_output.delete("1.0", "end")
        self._test_output.insert("1.0", text)
        self._test_output.configure(state="disabled")

    # ── save / reset ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        api_key = self._api_var.get().strip()
        if api_key:
            try:
                set_api_key(api_key)
            except RuntimeError as exc:
                messagebox.showerror("Keychain Error", str(exc), parent=self._win)
                return

        try:
            timeout = max(5, int(self._timeout_var.get().strip()))
        except ValueError:
            timeout = 30

        config = load_config()
        model = self._model_var.get().strip()
        if model in OBSOLETE_MODELS:
            model = DEFAULT_MODEL
            self._model_var.set(model)
        provider = self._current_provider_id()
        if provider == API_PROVIDER_CUSTOM:
            url_err = validate_custom_base_url(self._custom_url_var.get())
            if url_err:
                messagebox.showwarning("Invalid URL", url_err, parent=self._win)
                return
        elif provider == API_PROVIDER_OLLAMA:
            url_err = validate_custom_base_url(self._ollama_url_var.get())
            if url_err:
                messagebox.showwarning("Invalid Ollama URL", url_err, parent=self._win)
                return

        config["model"] = model
        config["timeout"] = timeout
        config["api_provider"] = provider
        config["custom_api_base_url"] = self._custom_url_var.get().strip()
        config["ollama_url"] = self._ollama_url_var.get().strip() or OLLAMA_DEFAULT_URL

        # Built-in hotkeys
        hotkeys = {row.mode: row.value for row in self._hotkey_rows}

        dup = _duplicate_hotkeys(hotkeys)
        if dup:
            messagebox.showwarning(
                "Duplicate Hotkey",
                f"The hotkey {dup!r} is assigned to more than one mode.\n"
                "Each mode needs a unique binding.",
                parent=self._win,
            )
            return

        config["hotkeys"] = hotkeys
        save_config(config)

        if self._on_save:
            self._on_save()

        messagebox.showinfo("Saved", "Settings saved. Hotkeys reloaded.")

    def _reset(self) -> None:
        if messagebox.askyesno(
            "Reset",
            "Reset all settings to defaults? Your API key and Ollama URL will be cleared.",
            parent=self._win,
        ):
            from prompt_enhancer.core.config import DEFAULT_CONFIG
            from prompt_enhancer.core.config import save_config as sc
            sc(DEFAULT_CONFIG)
            if self._win:
                self._win.destroy()
            self.open()

    def _check_updates(self) -> None:
        import threading
        from prompt_enhancer.core.updater import check_sync, show_update_dialog

        def _run() -> None:
            info = check_sync()
            if info:
                show_update_dialog(info, parent=self._win)
            else:
                messagebox.showinfo(
                    "Updates",
                    f"You're on v{__version__} (latest or update server unreachable).",
                    parent=self._win,
                )

        threading.Thread(target=_run, daemon=True, name="check-updates").start()


# ══════════════════════════════════════════════════════════════════════════════
#  First-run welcome
# ══════════════════════════════════════════════════════════════════════════════

def show_welcome_if_needed() -> None:
    if is_welcome_done():
        return
    WelcomeDialog().run()


class WelcomeDialog:
    """One-time setup wizard for new installs."""

    def run(self) -> None:
        win = ctk.CTk()
        win.title("Welcome — Prompt Enhancer")
        win.geometry("560x520")
        win.minsize(480, 440)
        win.resizable(True, True)

        hdr = ctk.CTkFrame(win, corner_radius=0, fg_color="transparent")
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr,
            text="⚡ Prompt Enhancer",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#e94560",
        ).pack(pady=14)

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=12)

        lines = [
            "Improve selected text in any app with a hotkey.",
            "",
            "1. Get a free API key at build.nvidia.com (starts with nvapi-)",
            "2. Paste it in Settings and click Test Connection",
            "3. Select text, press Ctrl+Alt+E (Enhance)",
            "",
            "The PE icon lives in your system tray.",
        ]
        if is_wayland():
            lines.append("")
            lines.append("Wayland: keep ydotoold running for copy/paste.")

        ctk.CTkLabel(
            body,
            text="\n".join(lines),
            justify="left",
            wraplength=460,
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", pady=(0, 16))

        autostart_var = ctk.BooleanVar(value=not autostart.is_enabled())
        ctk.CTkCheckBox(
            body,
            text="Start automatically at login",
            variable=autostart_var,
        ).pack(anchor="w", pady=8)

        def _finish(open_settings: bool) -> None:
            if autostart_var.get():
                autostart.enable()
            mark_welcome_done()
            win.destroy()
            if open_settings:
                SettingsWindow().open()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=16)
        ctk.CTkButton(
            btn_row,
            text="Open Settings",
            width=160,
            fg_color="#e94560",
            hover_color="#c73652",
            command=lambda: _finish(True),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            btn_row,
            text="Finish",
            width=120,
            fg_color="gray30",
            command=lambda: _finish(False),
        ).pack(side="left")

        win.mainloop()
