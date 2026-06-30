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

import autostart
from async_ui import try_deliver_future
from config import (
    API_PROVIDER_CUSTOM,
    API_PROVIDER_DISABLED,
    API_PROVIDER_NVIDIA,
    DEFAULT_MODEL,
    NVIDIA_BASE_URL,
    OBSOLETE_MODELS,
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
from enhancer import MODE_LABELS, test_connection
from version import PORTFOLIO_URL, __version__

_PROVIDER_OPTIONS = (
    (API_PROVIDER_NVIDIA, "NVIDIA Cloud"),
    (API_PROVIDER_CUSTOM, "Custom endpoint (Ollama, vLLM, …)"),
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

# ── Example prompts shown in the custom mode dialog ──────────────────────────
_PROMPT_TEMPLATES = [
    ("Translate → Spanish",   "Translate the given text to Spanish. Return ONLY the translated text, no explanations."),
    ("Translate → French",    "Translate the given text to French. Return ONLY the translated text, no explanations."),
    ("Fix Grammar Only",      "Fix only the grammar and spelling errors in the given text. Do not change the wording, tone, or structure otherwise. Return ONLY the corrected text."),
    ("Bullet Points",         "Convert the given text into a clear, concise bullet-point list. Return ONLY the bullet points."),
    ("ELI5 (Simplify)",       "Explain the given text as if the reader is 10 years old. Use simple, everyday words. Return ONLY the simplified explanation."),
    ("Executive Summary",     "Write a one-paragraph executive summary of the given text. Be concise and focus on key decisions and outcomes. Return ONLY the summary."),
    ("Persuasive Rewrite",    "Rewrite the given text to be more persuasive and compelling. Keep the core message but strengthen the argument. Return ONLY the rewritten text."),
    ("Tweet Thread",          "Convert the given text into a Twitter/X thread of 3–5 punchy tweets. Number each tweet. Return ONLY the tweets."),
    ("Action Items",          "Extract all action items and tasks from the given text as a numbered list. Return ONLY the list."),
    ("Formal Email",          "Rewrite the given text as a polished formal email with a subject line, greeting, body, and sign-off. Return ONLY the email."),
]


# ══════════════════════════════════════════════════════════════════════════════
#  CustomModeDialog — modal dialog for creating / editing a custom mode
# ══════════════════════════════════════════════════════════════════════════════

class CustomModeDialog(ctk.CTkToplevel):
    """Modal window for adding or editing a custom enhancement mode."""

    def __init__(
        self,
        parent,
        mode_id: str | None = None,
        name: str = "",
        system_prompt: str = "",
        hotkey: str = "",
        on_save=None,
    ):
        super().__init__(parent)
        self._mode_id = mode_id
        self._on_save = on_save

        is_edit = mode_id is not None
        title = f"Edit Mode: {name}" if is_edit else "Add Custom Mode"
        self.title(title)
        self.geometry("640x620")
        self.minsize(560, 540)
        self.resizable(True, True)
        self.grab_set()   # modal — blocks parent
        self.focus_set()

        pad = {"padx": 20, "pady": 6}

        # ── Header ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color="#1a1a2e")
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr,
            text="✏  Custom Enhancement Mode" if is_edit else "＋  New Custom Mode",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#e94560",
        ).pack(pady=12)

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=6)

        # ── Mode Name ────────────────────────────────────────────────────────
        self._label(scroll, "Mode Name")
        self._name_var = ctk.StringVar(value=name)
        ctk.CTkEntry(
            scroll,
            textvariable=self._name_var,
            width=400,
            placeholder_text="e.g. Translate to Spanish",
        ).pack(anchor="w", **pad)

        # ── Hotkey ───────────────────────────────────────────────────────────
        self._label(scroll, "Hotkey  (optional)")
        self._hotkey_var = ctk.StringVar(value=hotkey)
        hk_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        hk_frame.pack(anchor="w", **pad)
        ctk.CTkEntry(hk_frame, textvariable=self._hotkey_var, width=220,
                     placeholder_text="<ctrl>+<alt>+t").pack(side="left")
        ctk.CTkLabel(
            hk_frame,
            text="  pynput format: <ctrl>, <alt>, <shift>, <cmd>",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(side="left")

        # ── System Prompt ─────────────────────────────────────────────────────
        self._label(scroll, "System Prompt  (AI instructions)")
        ctk.CTkLabel(
            scroll,
            text="Tell the AI exactly what to do with the selected text.\n"
                 "End your prompt with: Return ONLY the result — no explanations.",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 4))

        self._prompt_box = ctk.CTkTextbox(scroll, height=150, width=560,
                                          wrap="word", font=ctk.CTkFont(size=12))
        self._prompt_box.insert("1.0", system_prompt)
        self._prompt_box.pack(**pad)

        # ── Prompt Templates ─────────────────────────────────────────────────
        self._label(scroll, "Quick-Start Templates  (click to load)")
        tmpl_outer = ctk.CTkFrame(scroll, fg_color="transparent")
        tmpl_outer.pack(fill="x", padx=20, pady=4)

        for i, (tmpl_name, tmpl_prompt) in enumerate(_PROMPT_TEMPLATES):
            col = i % 2
            row = i // 2
            btn = ctk.CTkButton(
                tmpl_outer,
                text=tmpl_name,
                width=255,
                height=28,
                fg_color="#2a2a40",
                hover_color="#3a3a58",
                font=ctk.CTkFont(size=11),
                command=lambda p=tmpl_prompt, n=tmpl_name: self._load_template(n, p),
            )
            btn.grid(row=row, column=col, padx=4, pady=3, sticky="w")

        # ── Tip ──────────────────────────────────────────────────────────────
        tip_frame = ctk.CTkFrame(scroll, fg_color="#0d1117", corner_radius=8)
        tip_frame.pack(fill="x", padx=20, pady=(12, 4))
        ctk.CTkLabel(
            tip_frame,
            text="💡  Prompt writing tips",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e94560",
        ).pack(anchor="w", padx=12, pady=(8, 2))
        tips = (
            "• Always end with: Return ONLY the result — no explanations or labels.\n"
            "• Be specific: 'Translate to Spanish' beats 'Make it different'.\n"
            "• You can chain instructions: 'Fix grammar, then make it formal.'\n"
            "• Reference the input naturally: 'the given text', 'the selection'.\n"
            "• Use the Quick Test in Settings to verify your prompt before saving."
        )
        ctk.CTkLabel(
            tip_frame,
            text=tips,
            font=ctk.CTkFont(size=11),
            text_color="gray70",
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(
            btn_frame,
            text="💾  Save Mode",
            width=160,
            fg_color="#e94560",
            hover_color="#c73652",
            command=self._save,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=100,
            fg_color="gray30",
            command=self.destroy,
        ).pack(side="left")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _label(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent,
            text=text.upper(),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray60",
        ).pack(anchor="w", padx=20, pady=(12, 2))

    def _load_template(self, name: str, prompt: str) -> None:
        """Fill name (if empty) and system prompt from a template."""
        if not self._name_var.get().strip():
            self._name_var.set(name)
        self._prompt_box.delete("1.0", "end")
        self._prompt_box.insert("1.0", prompt)

    def _save(self) -> None:
        name = self._name_var.get().strip()
        system_prompt = self._prompt_box.get("1.0", "end").strip()
        hotkey = self._hotkey_var.get().strip()

        if not name:
            messagebox.showwarning("Required", "Please enter a name for this mode.",
                                   parent=self)
            return
        if not system_prompt:
            messagebox.showwarning("Required", "Please enter a system prompt.",
                                   parent=self)
            return

        prompt_err = validate_custom_prompt(system_prompt)
        if prompt_err:
            messagebox.showwarning("Invalid prompt", prompt_err, parent=self)
            return

        mode_id = self._mode_id or f"custom_{uuid.uuid4().hex[:8]}"

        if self._on_save:
            self._on_save(mode_id, name, system_prompt, hotkey)
        self.destroy()


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
        # In-memory state for custom modes (populated on open)
        self._custom_modes: dict[str, dict] = {}        # id → {name, system_prompt}
        self._custom_hotkeys: dict[str, str] = {}       # id → hotkey string
        self._custom_list_frame: ctk.CTkFrame | None = None
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
        self._custom_modes = {
            k: dict(v) for k, v in config.get("custom_modes", {}).items()
        }
        hotkeys_cfg: dict = config.get("hotkeys", {})
        self._custom_hotkeys = {
            k: hotkeys_cfg.get(k, "")
            for k in self._custom_modes
        }

        win = ctk.CTk()
        win.title("Prompt Enhancer — Settings")
        win.geometry("640x860")
        win.minsize(560, 720)
        win.resizable(True, True)
        self._win = win

        pad = {"padx": 20, "pady": 6}

        # ── Header ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(win, corner_radius=0, fg_color="#1a1a2e")
        hdr.pack(fill="x")
        ctk.CTkLabel(
            hdr,
            text="⚡ Prompt Enhancer",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#e94560",
        ).pack(pady=14)

        scroll = ctk.CTkScrollableFrame(win)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
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

        # ── API Provider ─────────────────────────────────────────────────────
        self._section(scroll, "API Provider")
        provider_id = config.get("api_provider", API_PROVIDER_NVIDIA)
        self._api_provider_var = ctk.StringVar(
            value=_PROVIDER_ID_TO_LABEL.get(provider_id, _PROVIDER_OPTIONS[0][1]),
        )
        ctk.CTkOptionMenu(
            scroll,
            variable=self._api_provider_var,
            values=[label for _, label in _PROVIDER_OPTIONS],
            width=420,
        ).pack(anchor="w", **pad)
        self._custom_url_var = ctk.StringVar(
            value=config.get("custom_api_base_url", ""),
        )
        ctk.CTkLabel(
            scroll,
            text="Custom base URL (OpenAI-compatible, e.g. http://localhost:11434/v1)",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=20, pady=(4, 0))
        ctk.CTkEntry(
            scroll,
            textvariable=self._custom_url_var,
            width=420,
            placeholder_text="http://localhost:11434/v1",
        ).pack(anchor="w", **pad)

        # ── API Key ──────────────────────────────────────────────────────────
        self._section(scroll, "API Key")
        api_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        api_frame.pack(fill="x", **pad)

        self._api_var = ctk.StringVar(value=get_api_key() or "")
        api_entry = ctk.CTkEntry(
            api_frame,
            textvariable=self._api_var,
            show="•",
            width=340,
            placeholder_text="nvapi-xxxxxxxxxxxxxxxxxxxx",
        )
        api_entry.pack(side="left")

        self._show_key = False
        toggle_btn = ctk.CTkButton(
            api_frame, text="Show", width=60,
            command=lambda: self._toggle_key(api_entry, toggle_btn),
        )
        toggle_btn.pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            scroll, text="Test Connection", width=160,
            command=self._test_connection,
        ).pack(anchor="w", **pad)

        self._test_label = ctk.CTkLabel(scroll, text="", font=ctk.CTkFont(size=12))
        self._test_label.pack(anchor="w", padx=20)

        # ── Model ────────────────────────────────────────────────────────────
        self._section(scroll, "AI Model")
        models: list[str] = models_for_settings(config, force_refresh=True)
        current_model = config.get("model", DEFAULT_MODEL)
        if current_model in OBSOLETE_MODELS:
            current_model = DEFAULT_MODEL
        if current_model not in models:
            models = [current_model] + models
        self._model_var = ctk.StringVar(value=current_model)
        self._model_menu = ctk.CTkOptionMenu(
            scroll, variable=self._model_var, values=models, width=420,
        )
        self._model_menu.pack(anchor="w", **pad)
        ctk.CTkLabel(
            scroll,
            text=f"Use {DEFAULT_MODEL} if Test Connection returns 404.",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=20, pady=(0, 4))

        # ── Timeout ──────────────────────────────────────────────────────────
        self._section(scroll, "Request Timeout (seconds)")
        self._timeout_var = ctk.StringVar(value=str(config.get("timeout", 30)))
        ctk.CTkEntry(scroll, textvariable=self._timeout_var, width=80).pack(anchor="w", **pad)

        # ── Autostart ────────────────────────────────────────────────────────
        self._section(scroll, "Run at Login (Autostart)")
        startup_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        startup_frame.pack(fill="x", padx=20, pady=6)
        self._autostart_var = ctk.BooleanVar(value=autostart.is_enabled())
        ctk.CTkSwitch(
            startup_frame,
            text="Start automatically when I log in",
            variable=self._autostart_var,
            onvalue=True, offvalue=False,
            command=self._on_autostart_toggle,
            progress_color="#e94560",
        ).pack(side="left")
        self._autostart_status = ctk.CTkLabel(
            scroll, text=self._autostart_label(),
            font=ctk.CTkFont(size=11), text_color="gray60",
        )
        self._autostart_status.pack(anchor="w", padx=20, pady=(0, 4))

        # ── Built-in Hotkeys ─────────────────────────────────────────────────
        self._section(scroll, "Built-in Hotkey Bindings")
        ctk.CTkLabel(
            scroll,
            text="pynput format: <ctrl>, <alt>, <shift>, <cmd> + any key",
            text_color="gray60", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=20, pady=(0, 6))

        self._hotkey_rows: list[HotkeyEntry] = []
        for mode in _BUILTIN_MODES:
            row = HotkeyEntry(scroll, mode, MODE_LABELS[mode],
                              hotkeys_cfg.get(mode, ""))
            row.pack(anchor="w", padx=20, pady=3)
            self._hotkey_rows.append(row)

        # ── Custom Modes ─────────────────────────────────────────────────────
        self._section(scroll, "Custom Modes")
        ctk.CTkLabel(
            scroll,
            text="Create your own enhancement modes with custom AI instructions.\n"
                 "Assign any hotkey — or leave blank and run from Quick Test.",
            text_color="gray60", font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 8))

        # List container (rebuilt whenever modes change)
        self._custom_list_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._custom_list_frame.pack(fill="x", padx=10)
        self._rebuild_custom_list()

        ctk.CTkButton(
            scroll,
            text="＋  Add Custom Mode",
            width=200,
            fg_color="#2a2a40",
            hover_color="#3a3a58",
            border_color="#e94560",
            border_width=1,
            command=self._add_custom_mode,
        ).pack(anchor="w", padx=20, pady=(10, 4))

        # ── Quick Test ───────────────────────────────────────────────────────
        self._section(scroll, "Quick Test")
        self._test_input = ctk.CTkTextbox(scroll, height=70, width=520)
        self._test_input.insert("1.0", self._QUICK_TEST_PLACEHOLDER)
        self._test_input.pack(**pad)

        mode_sel_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        mode_sel_frame.pack(fill="x", **pad)
        self._test_mode_var = ctk.StringVar(value=MODE_LABELS["enhance"])
        ctk.CTkLabel(mode_sel_frame, text="Mode:", width=50).pack(side="left")
        self._test_mode_menu = ctk.CTkOptionMenu(
            mode_sel_frame,
            variable=self._test_mode_var,
            values=self._mode_display_labels(),
            width=200,
        )
        self._test_mode_menu.pack(side="left", padx=8)
        ctk.CTkButton(
            mode_sel_frame, text="▶  Enhance", width=120,
            command=self._run_test_enhance,
        ).pack(side="left")

        self._test_output = ctk.CTkTextbox(scroll, height=80, width=520,
                                           state="disabled")
        self._test_output.pack(**pad)

        privacy_frame = ctk.CTkFrame(scroll, fg_color="#0d1117", corner_radius=8)
        privacy_frame.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(
            privacy_frame,
            text=(
                "Privacy: When the API is enabled, selected text is sent to the "
                "configured endpoint over HTTP(S) for rewriting. Air-gap mode "
                "sends nothing. Text is not stored locally."
            ),
            font=ctk.CTkFont(size=11),
            text_color="gray60",
            justify="left",
            wraplength=560,
        ).pack(anchor="w", padx=16, pady=10)

        # ── About ─────────────────────────────────────────────────────────
        self._section(scroll, "About")
        about_frame = ctk.CTkFrame(scroll, fg_color="#1a1a2e", corner_radius=10,
                                   border_width=1, border_color="#2a2a3e")
        about_frame.pack(fill="x", padx=10, pady=(4, 8))

        about_inner = ctk.CTkFrame(about_frame, fg_color="transparent")
        about_inner.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(
            about_inner,
            text=f"Prompt Enhancer  v{__version__}",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#e94560",
        ).pack(anchor="w")

        ctk.CTkLabel(
            about_inner,
            text="© 2026 Akash Soni  ·  Apache License 2.0",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
        ).pack(anchor="w", pady=(2, 8))

        links = ctk.CTkFrame(about_inner, fg_color="transparent")
        links.pack(anchor="w")
        ctk.CTkButton(
            links, text="🔗  Project Page", width=120, height=28,
            corner_radius=6,
            fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="#e94560", font=ctk.CTkFont(size=11),
            command=lambda: webbrowser.open(PORTFOLIO_URL),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            links, text="🔄  Check Updates", width=120, height=28,
            corner_radius=6,
            fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="gray70", font=ctk.CTkFont(size=11),
            command=self._check_updates,
        ).pack(side="left")

        # ── Footer: Save / Reset ──────────────────────────────────────────
        footer = ctk.CTkFrame(win, corner_radius=0, fg_color="#1a1a2e")
        footer.pack(fill="x", side="bottom")
        ctk.CTkFrame(footer, height=1, fg_color="#3a3a4a").pack(fill="x")

        btn_frame = ctk.CTkFrame(footer, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=10)

        ctk.CTkButton(
            btn_frame,
            text="Save & Apply",
            width=130, height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#e94560",
            hover_color="#c73652",
            command=self._save,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_frame, text="Reset Defaults", width=110, height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2a2a3e", hover_color="#3a3a4e",
            text_color="gray70",
            command=self._reset,
        ).pack(side="right")

        win.mainloop()
        self._win = None

    # ── custom modes helpers ──────────────────────────────────────────────────

    def _mode_display_labels(self) -> list[str]:
        """Human-readable labels for the Quick Test dropdown (built-in + custom)."""
        labels = [MODE_LABELS[m] for m in _BUILTIN_MODES]
        for mid, info in self._custom_modes.items():
            labels.append(info.get("name", mid))
        return labels

    def _label_to_mode_id(self, label: str) -> str:
        """Convert a dropdown display label back to its mode ID."""
        for mid in _BUILTIN_MODES:
            if MODE_LABELS[mid] == label:
                return mid
        for mid, info in self._custom_modes.items():
            if info.get("name", mid) == label:
                return mid
        return label   # fallback — shouldn't happen

    def _rebuild_custom_list(self) -> None:
        """Destroy and recreate the custom modes list rows."""
        if not self._custom_list_frame:
            return
        for w in self._custom_list_frame.winfo_children():
            w.destroy()

        if not self._custom_modes:
            ctk.CTkLabel(
                self._custom_list_frame,
                text="No custom modes yet — click  ＋ Add Custom Mode  below.",
                text_color="gray50",
                font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=10, pady=6)
            return

        for mode_id, info in list(self._custom_modes.items()):
            self._add_custom_row(mode_id, info)

    def _add_custom_row(self, mode_id: str, info: dict) -> None:
        """Render one custom mode row inside the list frame."""
        row = ctk.CTkFrame(self._custom_list_frame, fg_color="#1e1e30",
                           corner_radius=8)
        row.pack(fill="x", padx=0, pady=4)

        # Name + prompt preview
        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True, padx=10, pady=6)

        ctk.CTkLabel(
            text_col,
            text=info.get("name", mode_id),
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(anchor="w")

        preview = info.get("system_prompt", "")[:80].replace("\n", " ")
        if len(info.get("system_prompt", "")) > 80:
            preview += "…"
        ctk.CTkLabel(
            text_col,
            text=preview,
            text_color="gray60",
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(anchor="w")

        # Hotkey entry
        hk_col = ctk.CTkFrame(row, fg_color="transparent")
        hk_col.pack(side="left", padx=(0, 6), pady=6)
        hk_var = ctk.StringVar(value=self._custom_hotkeys.get(mode_id, ""))
        hk_entry = ctk.CTkEntry(hk_col, textvariable=hk_var, width=180,
                                placeholder_text="hotkey (optional)")
        hk_entry.pack()

        # Keep hotkey var in sync
        def _on_hk_change(*_, mid=mode_id, var=hk_var):
            self._custom_hotkeys[mid] = var.get().strip()
        hk_var.trace_add("write", _on_hk_change)

        # Edit / Delete buttons
        btn_col = ctk.CTkFrame(row, fg_color="transparent")
        btn_col.pack(side="right", padx=6, pady=6)

        ctk.CTkButton(
            btn_col,
            text="✏",
            width=34, height=28,
            fg_color="#2a2a40",
            hover_color="#3a3a58",
            font=ctk.CTkFont(size=14),
            command=lambda mid=mode_id: self._edit_custom_mode(mid),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_col,
            text="✕",
            width=34, height=28,
            fg_color="#3a1010",
            hover_color="#5a2020",
            font=ctk.CTkFont(size=14),
            command=lambda mid=mode_id: self._delete_custom_mode(mid),
        ).pack(side="left")

    def _add_custom_mode(self) -> None:
        if not self._win:
            return
        CustomModeDialog(
            self._win,
            on_save=self._on_custom_mode_saved,
        )

    def _edit_custom_mode(self, mode_id: str) -> None:
        if not self._win:
            return
        info = self._custom_modes.get(mode_id, {})
        CustomModeDialog(
            self._win,
            mode_id=mode_id,
            name=info.get("name", ""),
            system_prompt=info.get("system_prompt", ""),
            hotkey=self._custom_hotkeys.get(mode_id, ""),
            on_save=self._on_custom_mode_saved,
        )

    def _delete_custom_mode(self, mode_id: str) -> None:
        name = self._custom_modes.get(mode_id, {}).get("name", mode_id)
        if not messagebox.askyesno(
            "Delete Mode",
            f"Delete custom mode '{name}'?\nIts hotkey will also be removed.",
            parent=self._win,
        ):
            return
        self._custom_modes.pop(mode_id, None)
        self._custom_hotkeys.pop(mode_id, None)
        self._rebuild_custom_list()
        self._refresh_test_mode_menu()

    def _on_custom_mode_saved(
        self, mode_id: str, name: str, system_prompt: str, hotkey: str
    ) -> None:
        self._custom_modes[mode_id] = {"name": name, "system_prompt": system_prompt}
        self._custom_hotkeys[mode_id] = hotkey
        self._rebuild_custom_list()
        self._refresh_test_mode_menu()

    def _refresh_test_mode_menu(self) -> None:
        if self._test_mode_menu:
            self._test_mode_menu.configure(values=self._mode_display_labels())

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
        import sys as _sys
        hint = {
            "win32":  "Registry: HKCU\\...\\Run",
            "darwin": "LaunchAgent: ~/Library/LaunchAgents/",
        }.get(_sys.platform, "XDG autostart + systemd user service")
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
        config["custom_modes"] = {
            mid: dict(info) for mid, info in self._custom_modes.items()
        }
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

        config["model"] = model
        config["timeout"] = timeout
        config["api_provider"] = provider
        config["custom_api_base_url"] = self._custom_url_var.get().strip()

        # Built-in hotkeys
        hotkeys = {row.mode: row.value for row in self._hotkey_rows}
        # Custom mode hotkeys merged in
        for mid, hk in self._custom_hotkeys.items():
            if hk:
                hotkeys[mid] = hk
            else:
                hotkeys.pop(mid, None)   # no hotkey — remove entry

        dup = _duplicate_hotkeys(hotkeys)
        if dup:
            messagebox.showwarning(
                "Duplicate Hotkey",
                f"The hotkey {dup!r} is assigned to more than one mode.\n"
                "Each mode needs a unique binding.",
                parent=self._win,
            )
            return

        for mid, info in self._custom_modes.items():
            prompt_err = validate_custom_prompt(info.get("system_prompt", ""))
            if prompt_err:
                name = info.get("name", mid)
                messagebox.showwarning(
                    "Invalid custom mode",
                    f"Mode '{name}': {prompt_err}",
                    parent=self._win,
                )
                return

        config["hotkeys"] = hotkeys
        config["custom_modes"] = {
            mid: info for mid, info in self._custom_modes.items()
        }
        save_config(config)

        if self._on_save:
            self._on_save()

        messagebox.showinfo("Saved", "Settings saved. Hotkeys reloaded.")

    def _reset(self) -> None:
        if messagebox.askyesno(
            "Reset",
            "Reset all settings to defaults?\nThis will also delete all custom modes.",
            parent=self._win,
        ):
            from config import DEFAULT_CONFIG
            from config import save_config as sc
            sc(DEFAULT_CONFIG)
            if self._win:
                self._win.destroy()
            self.open()

    def _check_updates(self) -> None:
        import threading
        from updater import check_sync, show_update_dialog

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
        if sys.platform == "darwin":
            lines.append("")
            lines.append("macOS: allow Accessibility when prompted (required for hotkeys).")
        if sys.platform.startswith("linux"):
            lines.append("")
            lines.append("Linux Wayland: keep ydotoold running for copy/paste.")

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
