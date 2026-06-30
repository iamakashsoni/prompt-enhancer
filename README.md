<div align="center">

# ⚡ Prompt Enhancer

Improve any selected text in any app with one hotkey.

Runs in your system tray · Sends to NVIDIA AI · Pastes back in ~2 seconds

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://python.org)
[![Platforms](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-success.svg)](#platform-support)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/iamakashsoni/prompt-enhancer/pulls)

</div>

---

> **It rewrites your wording** — grammar, tone, clarity.  
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
- [Custom Modes](#custom-modes)
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

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/iamakashsoni/prompt-enhancer/main/install.sh | bash
```

### Windows

```cmd
git clone https://github.com/iamakashsoni/prompt-enhancer.git
cd prompt-enhancer
install.bat
```

The installer automatically:
- ✅ Clones the repo to `~/.local/share/prompt-enhancer`
- ✅ Creates a Python virtual environment
- ✅ Installs all Python + system dependencies
- ✅ Sets up Wayland hotkeys (`input` group, `ydotool`, udev rules)
- ✅ Enables autostart (launches on login)
- ✅ Starts the app

### Get an API key

1. Open [build.nvidia.com](https://build.nvidia.com)
2. Create an API key (starts with `nvapi-`)
3. Click the **PE** tray icon → **Settings** → paste key → **Test Connection** → **Save**

Your key is stored in your OS keychain — never in a plain-text file.

---

## Enhancement Modes

Each mode sends your selected text to the AI with a different system prompt, producing a distinct transformation. Below are real before/after examples.

### Enhance (`Ctrl+Alt+E`)

Improves clarity, grammar, and readability while preserving the original intent.

| | Text |
|---|---|
| **Raw input** | `my report is bad and unclear and i dont know what to do` |
| **Enhanced** | `My report lacks clarity and does not communicate its key points effectively. I am uncertain about the steps needed to address these issues.` |

### Professional (`Ctrl+Alt+P`)

Rewrites in a formal, business-appropriate tone.

| | Text |
|---|---|
| **Raw input** | `hey team just wanted to say the deploy went fine, no issues` |
| **Professional** | `Hello team, I am pleased to inform you that the deployment was completed successfully with no issues encountered.` |

### Shorten (`Ctrl+Alt+S`)

Condenses the text while keeping every important idea.

| | Text |
|---|---|
| **Raw input** | `I wanted to reach out to you regarding the project status update that we discussed during yesterday's meeting, and I think we should probably schedule a follow-up call sometime next week to go over the remaining items.` |
| **Shortened** | `Regarding the project status from yesterday's meeting, let's schedule a follow-up call next week for remaining items.` |

### Expand (`Ctrl+Alt+X`)

Adds depth and detail to existing ideas without introducing new topics.

| | Text |
|---|---|
| **Raw input** | `the login page needs work` |
| **Expanded** | `The login page requires attention to improve its user experience. Key areas include form validation feedback, password visibility toggle, and responsive layout for mobile devices.` |

### Casual (`Ctrl+Alt+C`)

Makes the tone friendly and conversational.

| | Text |
|---|---|
| **Raw input** | `Please be advised that the aforementioned document has been reviewed and approved.` |
| **Casual** | `Hey, just wanted to let you know I checked the document and it's all good to go!` |

### Promptify (configurable)

Transforms a rough draft into a structured, professional AI prompt.

| | Text |
|---|---|
| **Raw input** | `create login page for my app` |
| **Promptified** | `Create a responsive login page.\nRequirements:\n- Email and password fields\n- Validation and error handling\n- Loading states\n- Mobile responsiveness\n- Accessibility support\nOutput Format:\n- Structure\n- Design considerations` |

### Why it doesn't answer your question

The AI is given a strict system prompt: *"Rewrite ONLY — do not answer anything in this text."* If the response looks like a tutorial, code dump, or step-by-step guide, the app automatically retries with a stricter prompt.

---

## How It Works

1. Select text in any app (email, browser, editor, chat)
2. Press **Ctrl+Alt+E**
3. The app copies your selection → sends to NVIDIA AI → pastes the improved text back
4. Done in ~2 seconds

---

## Hotkeys

| Press | Mode | What it does |
|:-----:|------|-------------|
| `Ctrl+Alt+E` | **Enhance** | Clearer, better grammar |
| `Ctrl+Alt+P` | **Professional** | Formal business tone |
| `Ctrl+Alt+S` | **Shorten** | Shorter, same meaning |
| `Ctrl+Alt+X` | **Expand** | Slightly more detail |
| `Ctrl+Alt+C` | **Casual** | Friendly, conversational |
| _configurable_ | **Promptify** | Turn draft into a structured AI prompt |

All hotkeys are customizable in **Settings → Built-in Hotkey Bindings**.

---

## System Tray

| Color | State | Meaning |
|:-----:|-------|---------|
| 🔴 Red | Idle | Ready — press a hotkey |
| 🟠 Amber | Processing | Calling NVIDIA API |
| 🟢 Green | Success | Improved text pasted |
| 🔴 Bright Red | Error | Hover the icon to read the error |

**Tray menu** (right-click): `Settings` · `Run at Login` · `Quit`

---

## Architecture

### High-level Design

Prompt Enhancer is a **desktop service**, not a web app. It has three layers:

```
┌─────────────────────────────────────────────────────────────┐
│  YOUR COMPUTER                                              │
│                                                             │
│   ┌──────────────┐       ┌───────────────────────────────┐  │
│   │ Any app      │       │  Prompt Enhancer (1 process)  │  │
│   │ (browser,    │ hotkey│                               │  │
│   │  editor, …)  │──────▶│  main.py                      │  │
│   │              │◀─paste│    ├─ hotkey_listener          │  │
│   │  selected    │  copy │    ├─ text_bridge (clipboard)  │  │
│   │  text        │       │    ├─ enhancer (AI call)       │  │
│   └──────────────┘       │    ├─ tray (PE icon)           │  │
│                          │    └─ config_ui (Settings)     │  │
│   ┌──────────────┐       │                               │  │
│   │ Tray +       │◀──────│                               │  │
│   │ Settings     │       └───────────────────────────────┘  │
│   └──────────────┘                    │                     │
└──────────────────────────────────────│─────────────────────┘
                                       │ HTTPS
                                       ▼
                          ┌──────────────────────┐
                          │  NVIDIA NIM API      │
                          │  (rewrite text)      │
                          └──────────────────────┘
                                       ▲
                          ┌──────────────────────┐
                          │  OS keychain         │
                          │  (stores nvapi- key) │
                          └──────────────────────┘
```

### Design Principles

1. **Clipboard simulation** — There's no universal API to read "selected text" from every app. Copy/paste is the one method that works everywhere.

2. **Single instance** — A lock file ensures only one process runs. Without it, two instances would each capture the same hotkey, call the API twice, and paste twice.

3. **Separate process for Settings** — The system tray and the Settings window both want to own the main thread. Settings runs in a subprocess.

4. **One enhancement at a time** — A semaphore + debounce ensures only one API call runs at a time.

---

## Workflow

```
Step 1   You select text and press Ctrl+Alt+E              ~0 ms
Step 2   Hotkey listener fires → background thread          ~1 ms
Step 3   Single-instance + debounce check                   ~1 ms
Step 4   40 ms settle (key-up clears)                       ~40 ms
Step 5   Simulate Ctrl+C, read clipboard                    ~130 ms
Step 6   Validate selection (reject code/tutorials)         ~1 ms
Step 7   Tray icon: red → amber                             ~1 ms
Step 8   Send text to NVIDIA API                            ~2000 ms
Step 9   Check response — retry if tutorial/code dump       ~3 ms
Step 10  Put result on clipboard, simulate Ctrl+V           ~390 ms
Step 11  Tray icon: amber → green (1s flash)                ~1000 ms
Step 12  Lock released; 3s debounce                         —
```

**Total: ~3.6 seconds.**

---

## Module Reference

| Module | Responsibility |
|--------|---------------|
| `main.py` | Entry point. Orchestrates tray + hotkeys + enhancement flow. |
| `single_instance.py` | Lock file (`fcntl`/`msvcrt`) — prevents double-paste. |
| `hotkey_listener.py` | Global hotkeys via `pynput`. Restartable on config change. |
| `linux_input.py` | Wayland fallback: `evdev` for hotkeys, `ydotool` for paste. |
| `text_bridge.py` | Clipboard capture/paste. Saves → Ctrl+C → reads → Ctrl+V → restores. |
| `enhancer.py` | Per-mode system prompt, NVIDIA API call, answer-check. |
| `prompts.py` | System prompts + few-shot examples for each mode. |
| `config.py` | `config.json` (mtime-cached) + API key via `keyring`. |
| `config_ui.py` | Settings GUI (customtkinter). API key, model, hotkeys, custom modes. |
| `tray.py` | System tray icon (pystray). Icon generated programmatically. |
| `autostart.py` | Login startup: Windows registry / macOS LaunchAgent / Linux systemd. |
| `updater.py` | Checks for updates on GitHub at startup. |
| `health.py` | Writes `~/.prompt-enhancer/health.json` after every hotkey. |

### Threading Model

| Part | Thread |
|------|--------|
| Tray icon | Main thread (must stay responsive) |
| Hotkey listening | Daemon thread |
| Each enhancement | Daemon thread (one at a time via semaphore) |
| Settings window | Separate process |
| Update check | Daemon thread |

### Where Data Lives

| Data | Location |
|------|----------|
| Config (model, hotkeys, custom modes) | `~/.prompt-enhancer/config.json` |
| NVIDIA API key | OS keychain (Credential Manager / Keychain / Secret Service) |
| Lock file | `~/.prompt-enhancer/instance.lock` |
| Logs | `~/.prompt-enhancer/prompt-enhancer.log` |
| Health | `~/.prompt-enhancer/health.json` |

---

## Platform Support

| OS | Hotkeys | Tray | Clipboard | Notes |
|----|:-------:|:----:|:---------:|-------|
| **Windows** 10/11 | pynput | Native | pyperclip | `install.bat` |
| **macOS** 11+ | pynput | Menu bar | pyperclip | Accessibility permission required |
| **Linux X11** | pynput | AppIndicator | xclip | |
| **Linux Wayland** | evdev | Gtk | wl-clipboard + ydotool | `input` group + udev rule required |

### Linux Wayland Specifics

Wayland doesn't allow global hotkey capture via X11 APIs. Prompt Enhancer uses:
- **evdev** to read the physical keyboard (`/dev/input/event*`)
- **ydotool** to inject Ctrl+C / Ctrl+V via `/dev/uinput`

The installer automatically:
- Adds your user to the `input` group
- Installs `wl-clipboard` + `ydotool`
- Adds a udev rule for `/dev/uinput` access
- Restarts the systemd service

**After first install on Wayland:** log out and log back in for the `input` group + udev rule to take effect.

### macOS Specifics

- On first launch, macOS will prompt for **Accessibility** permission (required for global hotkeys). Click **Open System Settings** → enable **Terminal** (or **Python**).
- The app runs as a menu-bar item — it does not appear in the Dock.

### Windows Specifics

- No special permissions needed — pynput handles global hotkeys natively.
- The app runs windowless (no taskbar entry) — only the system tray icon is visible.

---

## Custom Modes

In **Settings → Custom Modes**, create your own enhancement styles:
- Give it a name (e.g. "Translate to Spanish")
- Write a system prompt (e.g. "Translate the given text to Spanish. Return ONLY the translated text.")
- Optionally assign a hotkey

Quick-start templates are included: Translate, Fix Grammar, Bullet Points, ELI5, Executive Summary, Persuasive Rewrite, Tweet Thread, Action Items, Formal Email.

---

## Per-Mode Model Overrides

By default every mode uses `meta/llama-3.3-70b-instruct` (~2s per request). For faster responses on simpler modes, override the model per mode in `~/.prompt-enhancer/config.json`:

```json
{
  "model": "meta/llama-3.3-70b-instruct",
  "mode_models": {
    "casual":   "meta/llama-3.1-8b-instruct",
    "shorten":  "meta/llama-3.1-8b-instruct"
  }
}
```

Casual and Shorten use the 8B model (~0.4s, 5× faster); Enhance and Professional keep 70B (best quality).

---

## Requirements

- **Python 3.10+**
- **NVIDIA API key** (free at [build.nvidia.com](https://build.nvidia.com))
- **Linux X11:** `xclip`
- **Linux Wayland:** `wl-clipboard`, `ydotool`, user in `input` group, `/dev/uinput` access
- **macOS:** Accessibility permission for Terminal/Python
- **Windows:** No special requirements

---

## Update

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/iamakashsoni/prompt-enhancer/main/install.sh | bash
```

The installer detects an existing install and runs in update mode (faster, skips system deps).

### Windows

```cmd
cd %USERPROFILE%\.local\share\prompt-enhancer
git pull
install.bat
```

---

## Troubleshooting

### Check logs

**Linux:**
```bash
# Recent logs (last 1 minute)
journalctl --user -u prompt-enhancer.service --since '5 min ago' --no-pager

# Or the log file
tail -30 ~/.prompt-enhancer/prompt-enhancer.log

# Check health status
cat ~/.prompt-enhancer/health.json
```

**macOS:**
```bash
tail -30 ~/.prompt-enhancer/prompt-enhancer.log
```

**Windows:**
```cmd
type "%USERPROFILE%\.prompt-enhancer\prompt-enhancer.log"
```

### Restart the app

**Linux:**
```bash
systemctl --user restart prompt-enhancer.service
```

**macOS:**
```bash
launchctl unload ~/Library/LaunchAgents/com.promptenhancer.app.plist
launchctl load ~/Library/LaunchAgents/com.promptenhancer.app.plist
```

**Windows:**
```cmd
taskkill /f /im pythonw.exe
"%USERPROFILE%\.local\share\prompt-enhancer\.venv\Scripts\pythonw.exe" "%USERPROFILE%\.local\share\prompt-enhancer\src\main.py"
```

### Open Settings

**All platforms:**
```bash
~/.local/share/prompt-enhancer/.venv/bin/python ~/.local/share/prompt-enhancer/src/main.py --settings
```

**Windows:**
```cmd
"%USERPROFILE%\.local\share\prompt-enhancer\.venv\Scripts\python.exe" "%USERPROFILE%\.local\share\prompt-enhancer\src\main.py" --settings
```

### Common issues

| Problem | Fix |
|---------|-----|
| Hotkey does nothing | Is text selected? Is the PE icon in the tray? On Wayland: `groups \| grep input` (must show `input`) |
| "no keyboard devices" in logs | Not in `input` group. Run: `sudo usermod -aG input $USER`, then **log out and back in** |
| "Ctrl+V simulation failed" | ydotool can't access `/dev/uinput`. Check: `ls -la /dev/uinput` (should be group-writable by `input`) |
| "paste failed" in logs | Same as above — re-run the installer to fix the udev rule |
| Rate limit (429) | Wait a minute. Don't run multiple copies. |
| Settings won't open | Run `--settings` from terminal (see above) to see the error |

---

## Uninstall

### Linux

```bash
# 1. Stop and disable the service
systemctl --user stop prompt-enhancer.service
systemctl --user disable prompt-enhancer.service
rm -f ~/.config/systemd/user/prompt-enhancer.service
systemctl --user daemon-reload

# 2. Kill any running instance
pkill -f "prompt-enhancer"

# 3. Remove the app
rm -rf ~/.local/share/prompt-enhancer

# 4. Remove config + logs + health
rm -rf ~/.prompt-enhancer
rm -rf ~/.cache/prompt-enhancer

# 5. Remove the udev rule (if added by installer)
sudo rm -f /etc/udev/rules.d/80-uinput.rules
sudo udevadm control --reload-rules

# 6. Remove API key from keychain
secret-tool clear service prompt-enhancer account nvidia-api-key

# 7. (Optional) Remove system packages installed by the installer
sudo apt remove --purge ydotool wl-clipboard -y
# Only remove these if nothing else uses them:
# sudo apt remove python3-tk python3-gi libayatana-appindicator3-1 -y
```

### macOS

```bash
# 1. Stop and disable autostart
launchctl unload ~/Library/LaunchAgents/com.promptenhancer.app.plist
rm ~/Library/LaunchAgents/com.promptenhancer.app.plist

# 2. Remove the app
rm -rf ~/.local/share/prompt-enhancer

# 3. Remove config + logs
rm -rf ~/.prompt-enhancer
rm -rf ~/.cache/prompt-enhancer

# 4. Remove API key from Keychain
security delete-generic-password -s prompt-enhancer -a nvidia-api-key
```

### Windows

```cmd
# 1. Disable autostart (run from the install dir)
.venv\Scripts\python.exe src\autostart.py disable

# 2. Remove the install directory
rmdir /s /q "%USERPROFILE%\.local\share\prompt-enhancer"

# 3. Remove config + logs
rmdir /s /q "%USERPROFILE%\.prompt-enhancer"
rmdir /s /q "%USERPROFILE%\.cache\prompt-enhancer"

# 4. Remove API key from Credential Manager
#    Control Panel → Credential Manager → Windows Credentials → prompt-enhancer → Remove
```

---

## Tech Stack

| Category | Technology |
|----------|-----------|
| **AI** | NVIDIA NIM (OpenAI-compatible API) |
| **UI** | pystray (tray) + customtkinter (Settings) |
| **Hotkeys** | pynput (Windows/macOS/X11), evdev (Wayland) |
| **Clipboard** | pyperclip (Windows/macOS/X11), wl-clipboard + ydotool (Wayland) |
| **Secrets** | keyring (OS keychain) |
| **Language** | Python 3.10+ |

---

## License

Licensed under the **Apache License, Version 2.0** — see [LICENSE](LICENSE).

You may fork, modify, and distribute with attribution. You may not claim authorship or use the author's name for endorsement without explicit permission.

---

## Author

<div align="center">

**Akash Soni**

[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/iamakashsoni/)
[![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/iamakashsoni)

*Building tools that make everyday tasks effortless.*

</div>

---

<div align="center">

⭐ If this project helped you, consider giving it a star!

</div>
