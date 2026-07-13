<div align="center">

# ⚡ Prompt Enhancer

Improve any selected text in any app with one hotkey.

Runs in your system tray · AI-powered · Pastes back in seconds

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%28Wayland%20%2B%20X11%29-success.svg)](#platform-support)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/iamakashsoni/prompt-enhancer/pulls)

</div>

---

> **It rewrites your wording** — grammar, tone, clarity, structure.  
> **It does not answer your question** or add code, tutorials, or step-by-step guides.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Enhancement Modes](#enhancement-modes)
- [How It Works](#how-it-works)
- [Hotkeys](#hotkeys)
- [System Tray](#system-tray)
- [Architecture](#architecture)
- [Workflow](#workflow)
- [Module Reference](#module-reference)
- [Platform Support](#platform-support)
- [API Providers](#api-providers)
- [Per-Mode Model Overrides](#per-mode-model-overrides)
- [Requirements](#requirements)
- [Update](#update)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [Tech Stack](#tech-stack)
- [License](#license)
- [Author](#author)

---

## Quick Start

### Linux (Wayland or X11)

```bash
curl -fsSL https://raw.githubusercontent.com/iamakashsoni/prompt-enhancer/main/install.sh | bash
```

The installer:
- Clones to `~/.local/share/prompt-enhancer/`
- Creates a Python venv + installs dependencies
- Installs `ydotool` + `wl-clipboard` (Wayland copy/paste)
- Adds you to the `input` group (evdev hotkey capture — **log out and back in** for this to take effect)
- Sets up a systemd user service (`prompt-enhancer.service`) for autostart + crash recovery

### Get an API key

1. Open **Settings** (click the ⚡ PE tray icon → Settings)
2. **API Provider** → choose:
   - **NVIDIA Cloud** — get a free key at [build.nvidia.com](https://build.nvidia.com) (starts with `nvapi-`)
   - **Ollama** — point at any network-reachable Ollama server (`http://localhost:11434/v1` or `http://192.168.x.x:11434/v1`). Click **Fetch models** to auto-populate the dropdown with installed models.
   - **Custom endpoint** — any OpenAI-compatible API (vLLM, LM Studio, etc.)
3. Paste your key → **Save & Apply**

You're ready. Highlight text in any app → press `Ctrl+Alt+E` → enhanced text replaces your selection in seconds.

---

## Enhancement Modes

Two modes only — simple to remember, each does one job well.

### Enhance (`Ctrl+Alt+E`)

Quick grammar, phrasing, and clarity fix. Keeps your voice, just polishes it.

| Input | Output |
|-------|--------|
| `need api docs` | Help me create comprehensive API documentation that clearly explains endpoints, request formats, responses, and usage guidelines. |
| `improve dashboard performance` | Help me improve dashboard performance by identifying bottlenecks and optimizing data loading, processing, and rendering efficiency. |
| `create login page for my app` | Help me create a responsive login page for my application with a clean user experience and proper authentication flow. |

### Professional (`Ctrl+Alt+P`)

Advanced prompt engineering. Detects the intent of your draft (Creation, Debugging, Analysis, Optimization, Review, Comparison, etc.) and produces a structured AI-ready prompt with Role, Objective, Context, Requirements, Constraints, and Output Format.

| Input | Output |
|-------|--------|
| `react component not rendering` | `Act as a Senior React Engineer.`<br>`Objective:` Identify the root cause…<br>`Expected Behavior:` …<br>`Actual Behavior:` …<br>`Evidence:` Component code, error messages, console output<br>`Analysis Requirements:` Identify likely causes, rank by likelihood, recommend corrective actions<br>`Output Format:` Findings, Root Cause Analysis, Recommendations |
| `need api docs` | `Create comprehensive API documentation.`<br>`Requirements:` Endpoint descriptions, request formats, response formats, error handling, auth details<br>`Output Format:` Documentation Structure, Content Organization |
| `dashboard performance is slow` | `Act as a Performance Optimization Specialist.`<br>`Objective:` Identify performance bottlenecks…<br>`Analysis Requirements:` Evaluate rendering, data loading, state management, scalability<br>`Output Format:` Bottlenecks, Impact Assessment, Prioritized Recommendations |

### Why it doesn't answer your question

The system prompt has strict rules: never answer, never provide solutions, never add code or tutorials. It only rewrites your text. An answer-checker inspects the output and retries with a stricter prompt if the model slips into "helpful assistant" mode.

---

## How It Works

```
You select text in any app
        ↓
Press Ctrl+Alt+E (or Ctrl+Alt+P)
        ↓
Prompt Enhancer simulates Ctrl+C  →  captures your selected text
        ↓
Sends text to AI (NVIDIA / Ollama / Custom) with the mode's system prompt
        ↓
AI rewrites the text (grammar, clarity, structure — no answering)
        ↓
Prompt Enhancer simulates Ctrl+V  →  pastes enhanced text over your selection
        ↓
Original clipboard restored
```

The whole cycle takes 2–6 seconds for an 8B model. No UI, no context switch — your hands never leave the keyboard.

---

## Hotkeys

| Hotkey | Mode | What it does |
|--------|------|-------------|
| `Ctrl+Alt+E` | **Enhance** | Quick grammar/phrasing/clarity fix |
| `Ctrl+Alt+P` | **Professional** | Advanced prompt engineering (intent detection + structured output) |

Both hotkeys are customizable in **Settings → Hotkeys**. Format: `<ctrl>+<alt>+e` (pynput syntax).

---

## System Tray

The ⚡ PE icon lives in your system tray. Right-click for:

- **Settings** — API provider, model, hotkeys, timeout, autostart
- **Start at login** — toggle autostart
- **Quit** — clean shutdown

Left-click does nothing (the tray is for configuration only — enhancement is hotkey-driven).

---

## Architecture

### High-level Design

```
src/
  main.py                              # thin entry point (backward compat)
  prompt_enhancer/
    __init__.py
    __main__.py                        # enables `python -m prompt_enhancer`
    main.py                            # orchestration: hotkey → capture → AI → paste
    │
    core/                              # pure logic — no I/O, no GUI, testable
    ├── config.py                      # load/save config.json, API key (keyring), model catalog
    ├── enhancer.py                    # LLM call, answer-checker, retry, mode resolution
    ├── prompts.py                     # system prompts + few-shot examples (Enhance, Professional)
    ├── health.py                      # health.json for diagnostics
    ├── updater.py                     # GitHub release version check
    ├── version.py                     # __version__, URLs
    └── logging.py                     # stderr logger (JSON-lines optional)
    │
    platform/                          # Linux platform layer
    ├── runtime.py                     # install paths (dev vs frozen), venv python lookup
    ├── autostart.py                   # systemd user service + XDG autostart fallback
    ├── evdev_hotkeys.py               # Wayland: /dev/input event capture + ydotool key injection
    ├── single_instance.py             # fcntl file lock (one process only)
    └── tray.py                        # pystray system tray icon
    │
    input/                             # keyboard + clipboard
    ├── hotkey_listener.py             # evdev (Wayland) or pynput GlobalHotKeys (X11)
    └── text_bridge.py                 # Ctrl+C capture, Ctrl+V paste, clipboard restore
    │
    ui/                                # settings GUI
    ├── settings_window.py             # customtkinter Settings window
    ├── settings_launcher.py           # runs Settings in subprocess (Tk mainloop isolation)
    └── async_ui.py                    # Future polling for async test-connection
```

### Design Principles

1. **Clipboard simulation, not accessibility APIs** — works in every app, including browsers, Electron, terminals, and Wayland-native apps. The trade-off: the target window must stay focused during the ~0.3s capture-paste window.
2. **Single instance** — `fcntl` file lock at `~/.prompt-enhancer/instance.lock` prevents duplicate tray icons and hotkey conflicts.
3. **Settings in a subprocess** — the Settings window runs in its own process so the Tk mainloop doesn't block the hotkey listener.
4. **One enhancement at a time** — a semaphore serializes triggers; a 3-second debounce prevents accidental double-presses.
5. **Crash recovery** — the systemd service has `Restart=on-failure`. The hotkey listener runs a restart loop in a daemon thread.
6. **Proxy-aware** — the systemd service inherits `HTTP_PROXY`/`HTTPS_PROXY` from the install-time shell, so VPN/proxy users work out of the box.

---

## Workflow

```
┌─────────────────────────────────────────────────────────┐
│  systemd user service (prompt-enhancer.service)         │
│  ├─ TrayApp (pystray) — system tray icon                │
│  ├─ HotkeyListener (daemon thread)                      │
│  │   ├─ Wayland: EvdevGlobalHotkeys (/dev/input)        │
│  │   └─ X11: pynput.keyboard.GlobalHotKeys              │
│  └─ On hotkey press:                                    │
│      ├─ capture_selected_text() (Ctrl+C simulation)     │
│      ├─ enhance_text() (OpenAI SDK → NVIDIA/Ollama)     │
│      ├─ paste_text() (Ctrl+V simulation)                │
│      └─ restore original clipboard                      │
└─────────────────────────────────────────────────────────┘
```

### Threading Model

| Thread | Role |
|--------|------|
| Main | `tray.run()` (pystray mainloop) |
| Hotkey listener (daemon) | Restarts on crash, runs evdev or pynput |
| Enhancement worker (daemon) | Spawned per hotkey press — capture → AI → paste |
| Updater check (daemon) | One-shot at startup, checks GitHub releases |

---

## Module Reference

| Module | Responsibility |
|--------|---------------|
| `prompt_enhancer/main.py` | Entry point: wires tray + listener + signal handlers |
| `core/config.py` | Load/save `~/.prompt-enhancer/config.json`, keyring API key, model catalog (NVIDIA + Ollama) |
| `core/enhancer.py` | OpenAI client, answer-checker, retry on transient errors, mode/model resolution |
| `core/prompts.py` | System prompts + few-shot examples for Enhance and Professional modes |
| `core/health.py` | Writes `health.json` with startup/success/error/stopped events |
| `core/updater.py` | Fetches GitHub release manifest, semver compare, update dialog |
| `core/logging.py` | Stderr logger (JSON-lines if `PE_LOG_JSON=1`) |
| `core/version.py` | `__version__`, GitHub repo URLs |
| `platform/runtime.py` | Install paths (dev vs frozen), venv python lookup |
| `platform/autostart.py` | systemd user service + XDG `.desktop` fallback |
| `platform/evdev_hotkeys.py` | Wayland: `/dev/input` event capture + `ydotool` key injection |
| `platform/single_instance.py` | `fcntl` file lock — one process only |
| `platform/tray.py` | `pystray` tray icon with state colors (idle/processing/success/error) |
| `input/hotkey_listener.py` | Routes to evdev (Wayland) or pynput (X11); restart loop |
| `input/text_bridge.py` | Ctrl+C capture, Ctrl+V paste, clipboard restore, Wayland PRIMARY fallback |
| `ui/settings_window.py` | customtkinter Settings window (provider, model, hotkeys, timeout, autostart) |
| `ui/settings_launcher.py` | Runs Settings in a subprocess (Tk mainloop isolation) |
| `ui/async_ui.py` | `try_deliver_future()` — polls a `Future` and dispatches callbacks |
| `src/main.py` | Thin entry point — backward compat for install.sh / systemd ExecStart |

### Where Data Lives

| Path | Contents |
|------|----------|
| `~/.local/share/prompt-enhancer/` | App source + `.venv/` |
| `~/.prompt-enhancer/config.json` | API provider, model, hotkeys, timeout, ollama_url |
| `~/.prompt-enhancer/instance.lock` | Single-instance file lock |
| `~/.prompt-enhancer/health.json` | Startup/success/error/stopped events |
| OS keyring (gnome-keyring / secretstorage) | NVIDIA API key |
| `~/.config/systemd/user/prompt-enhancer.service` | systemd user service |

---

## Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| **Linux (Wayland)** | ✅ Full | evdev hotkey capture + ydotool copy/paste. Requires `input` group membership. |
| **Linux (X11)** | ✅ Full | pynput hotkey capture + pyperclip copy/paste. |

### Linux Wayland Specifics

- **Hotkey capture**: reads `/dev/input/event*` directly via evdev (rootless via the `input` group). Works even when the focused app is a native Wayland client that pynput's X11 backend cannot see.
- **Copy/paste**: uses `ydotool` to simulate Ctrl+C/Ctrl+V (requires `/dev/uinput` access — the installer adds a udev rule for the `input` group).
- **ydotoold**: the installer starts `ydotoold` if it exists (ydotool 1.0+). On Ubuntu 22.04 (ydotool 0.1.8), ydotool works standalone.
- **Focus**: highlight text, keep that window focused, then press the hotkey. The target window must stay focused during the ~0.3s capture-paste window.

---

## API Providers

Three providers, switchable in Settings → API Provider:

### NVIDIA Cloud (default)
- **URL**: `https://integrate.api.nvidia.com/v1`
- **Auth**: API key from [build.nvidia.com](https://build.nvidia.com) (free tier, starts with `nvapi-`)
- **Models**: top 3 lightweight (≤8B) — fast on the free tier:
  - `meta/llama-3.1-8b-instruct` (default)
  - `qwen/qwen2.5-7b-instruct`
  - `nvidia/llama-3.1-nemotron-nano-8b-v1`

### Ollama (local or remote)
- **URL**: any network-reachable Ollama server (`http://localhost:11434/v1` or `http://192.168.x.x:11434/v1`)
- **Auth**: none needed (uses sentinel `"not-needed"` string)
- **Models**: click **Fetch models** in Settings to auto-populate from `GET /api/tags`. Works for any network host, not just localhost.
- **Setup**: `ollama serve` on the server, `ollama pull llama3.1:8b` to install a model.

### Custom endpoint
- **URL**: any OpenAI-compatible API (`http://localhost:1234/v1` for LM Studio, `http://localhost:8000/v1` for vLLM, etc.)
- **Auth**: API key from keyring (optional — some local servers don't require it)

### Disabled (air-gap)
- No network calls. Hotkeys do nothing. Useful for testing the install without an API key.

---

## Per-Mode Model Overrides

Power-user feature: use a different model per mode. Configure in `~/.prompt-enhancer/config.json`:

```json
{
  "model": "meta/llama-3.1-8b-instruct",
  "mode_models": {
    "professional": "qwen/qwen2.5-7b-instruct"
  }
}
```

Resolution order:
1. `config["mode_models"][mode]` — per-mode override
2. `config["model"]` — global default
3. `DEFAULT_MODEL` — hardcoded fallback (`meta/llama-3.1-8b-instruct`)

No UI surface — edit `config.json` directly. Useful for trying a different model on Professional mode without changing the global default.

---

## Requirements

- **Linux** (Wayland or X11)
- **Python 3.10+**
- **System packages** (auto-installed by `install.sh`):
  - `python3-venv`, `python3-dev`, `python3-tk`
  - `xclip` (X11 clipboard), `wl-clipboard` (Wayland clipboard)
  - `ydotool` (Wayland key injection)
  - `gir1.2-ayatanaappindicator3-0.1` (system tray icon on GNOME)
- **Group membership**: `input` group (for evdev hotkey capture + `/dev/uinput` for ydotool). The installer adds you — **log out and back in** for it to take effect.

---

## Update

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/iamakashsoni/prompt-enhancer/main/install.sh | bash
```

The installer detects the existing install, runs `git fetch` + `git reset --hard origin/main`, rebuilds the venv, and restarts the systemd service. Your config and API key are preserved.

Or, from the install directory:

```bash
cd ~/.local/share/prompt-enhancer
git pull
.venv/bin/python -m pip install -r requirements.txt
systemctl --user restart prompt-enhancer.service
```

---

## Troubleshooting

### Check logs

```bash
# Recent logs (last 1 minute)
journalctl --user -u prompt-enhancer.service --since '1 min ago' --no-pager

# Follow logs live
journalctl --user -u prompt-enhancer.service -f
```

### Restart the app

```bash
systemctl --user restart prompt-enhancer.service
```

### Open Settings

```bash
~/.local/share/prompt-enhancer/.venv/bin/python ~/.local/share/prompt-enhancer/src/main.py --settings
```

Or: right-click the ⚡ PE tray icon → Settings.

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Hotkey fires but "Request timed out" | NVIDIA API unreachable, or model too slow | Check `[net]` log lines at startup. Try a smaller model, or switch to Ollama (local). |
| Hotkey fires but "no text captured" | Target window lost focus during capture | Keep the target window focused after pressing the hotkey (~0.3s). |
| "paste failed — is ydotoold running?" | ydotoold not running on Wayland | `sudo ydotoold &` or reboot (installer sets it up). |
| No tray icon | Service crashed | `systemctl --user status prompt-enhancer.service` — check exit code + logs. |
| Hotkeys not captured on Wayland | Not in `input` group | `sudo usermod -aG input $USER` → log out and back in. |
| "Authentication failed (401)" | Wrong API key | Settings → paste a valid `nvapi-` key → Save. |
| "Model not found (404)" | Model name wrong or unavailable | Settings → AI Model → pick a curated model → Save. |

### Startup network diagnostics

At startup, the service logs network state to the journal:

```
[net] proxy env detected: ['HTTPS_PROXY']
[net]   HTTPS_PROXY=http://127.0.0.1:7890
[net] NVIDIA /v1/models reachable (HTTP 401)
[net] NVIDIA chat completions OK (4.2s) — model=meta/llama-3.1-8b-instruct, reply='OK'
```

If the chat completions check fails, the log tells you exactly what's wrong (timeout → try smaller model; connection refused → check proxy/network).

---

## Uninstall

### Linux

```bash
# 1. Stop and disable the service
systemctl --user disable --now prompt-enhancer.service
systemctl --user daemon-reload

# 2. Remove the app
rm -rf ~/.local/share/prompt-enhancer

# 3. Remove config + logs + health
rm -rf ~/.prompt-enhancer

# 4. Remove the udev rule (if added by installer)
sudo rm -f /etc/udev/rules.d/80-uinput.rules
sudo udevadm control --reload-rules

# 5. Remove API key from keyring
python3 -c "import keyring; keyring.delete_password('prompt-enhancer', 'nvidia-api-key')"

# 6. (Optional) Remove system packages installed by the installer
# Only remove these if nothing else uses them:
# sudo apt remove python3-tk python3-gi libayatana-appindicator3-1 xclip wl-clipboard ydotool -y
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| AI SDK | openai (NVIDIA NIM / Ollama / OpenAI-compatible) |
| Hotkey capture | pynput (X11), evdev (Wayland) |
| Clipboard | pyperclip (X11), wl-clipboard + ydotool (Wayland) |
| System tray | pystray + Pillow |
| Settings GUI | customtkinter (Tkinter) |
| Credential storage | keyring (gnome-keyring / secretstorage) |
| Autostart | systemd user service + XDG `.desktop` fallback |
| Single instance | fcntl file lock |

---

## License

[Apache License 2.0](LICENSE) — © 2026 Akash Soni

---

## Author

**Akash Soni** — [hi@akashsoni.com](mailto:hi@akashsoni.com) — [akashsoni.com](https://akashsoni.com)

[![GitHub](https://img.shields.io/badge/GitHub-iamakashsoni-181717?logo=github)](https://github.com/iamakashsoni)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-iamakashsoni-0A66C2?logo=linkedin)](https://www.linkedin.com/in/iamakashsoni/)
