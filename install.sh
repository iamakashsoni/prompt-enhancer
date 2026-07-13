#!/usr/bin/env bash
set -euo pipefail

REPO="iamakashsoni/prompt-enhancer"
CLONE_URL="https://github.com/${REPO}.git"
INSTALL_DIR="${1:-$HOME/.local/share/prompt-enhancer}"

# ── Output helpers ──────────────────────────────────────────────────────────
info()  { printf '\033[0;34m→\033[0m %s\n' "$*"; }
ok()    { printf '\033[0;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m⚠\033[0m %s\n' "$*"; }
die()   { printf '\033[0;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ── Prerequisite checks ─────────────────────────────────────────────────────
command -v git >/dev/null 2>&1 || die "git is not installed.
  Ubuntu/Debian: sudo apt install git
  Fedora:        sudo dnf install git
  macOS:         xcode-select --install"

command -v python3 >/dev/null 2>&1 || die "Python 3 is not installed.
  Ubuntu/Debian: sudo apt install python3
  macOS:         brew install python or install from https://python.org"

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PY_VER="python${PY_MAJOR}.${PY_MINOR}"

if [[ "$PY_MAJOR" -lt 3 ]] || ([[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]); then
    die "Python 3.10+ required (found ${PY_MAJOR}.${PY_MINOR}).
  Ubuntu/Debian: sudo apt install python3.10
  Or use deadsnakes PPA for newer versions."
fi

# ── OS detection ────────────────────────────────────────────────────────────
detect_os() {
    local uname_s
    uname_s="$(uname -s 2>/dev/null || echo unknown)"
    case "$uname_s" in
        Linux) echo "linux" ;;
        Darwin) echo "macos" ;;
        *)     echo "unknown" ;;
    esac
}

os=$(detect_os)
case "$os" in
    linux)   : ;;
    macos)   die "macOS is no longer supported. Use the last cross-platform release." ;;
    unknown) die "Could not detect OS. Visit: https://github.com/${REPO}" ;;
esac

# ── Detect package manager ──────────────────────────────────────────────────
PM=""
if command -v apt-get >/dev/null 2>&1; then PM="apt"
elif command -v dnf >/dev/null 2>&1; then PM="dnf"
elif command -v pacman >/dev/null 2>&1; then PM="pacman"
fi

# ── Helper: install a system package (idempotent, quiet) ────────────────────
sys_install() {
    local pkgs_apt="$1" pkgs_dnf="$2" pkgs_pacman="$3"
    case "$PM" in
        apt)    sudo apt-get install -y -qq $pkgs_apt ;;
        dnf)    sudo dnf install -y -q $pkgs_dnf ;;
        pacman) sudo pacman -S --noconfirm --needed $pkgs_pacman ;;
    esac
}

# ── Helper: verify a Python module is importable ────────────────────────────
verify_module() {
    local mod="$1" label="$2"
    if ! python3 -c "import $mod" 2>/dev/null; then
        die "$label is missing after installation attempt.
Install manually:
  apt:    sudo apt install ${PY_VER}-${mod//-/_} ${mod//-/_}
  dnf:    sudo dnf install python3-${mod//-/_}
  pacman: sudo pacman -S ${mod//-/_}
Then re-run this installer."
    fi
}

# ── Fresh install or update? ────────────────────────────────────────────────
IS_UPDATE=false
[[ -d "$INSTALL_DIR/.git" ]] && IS_UPDATE=true

echo ""
if $IS_UPDATE; then echo "  ⚡ Prompt Enhancer — Update"
else                 echo "  ⚡ Prompt Enhancer — Install"; fi
echo "  ─────────────────────────"
echo ""

# ── Stop running instances ──────────────────────────────────────────────────
pkill -f "prompt.enhancer" 2>/dev/null || true
pkill -f "PromptEnhancer" 2>/dev/null || true
pkill -f "com.promptenhancer" 2>/dev/null || true
pkill -f "main.py" 2>/dev/null || true
sleep 1

# ── Clean up old installs (fresh only) ──────────────────────────────────────
if ! $IS_UPDATE; then
    if [[ "$os" == "linux" ]] && command -v flatpak >/dev/null 2>&1; then
        flatpak uninstall -y --user com.promptenhancer.App 2>/dev/null || \
        flatpak uninstall -y com.promptenhancer.App 2>/dev/null || true
    fi
    rm -f "$HOME/.local/bin/prompt-enhancer" 2>/dev/null || true
    for d in "$HOME/Downloads/prompt-enhancer" "$HOME/Desktop/prompt-enhancer"; do
        [[ -d "$d" ]] && [[ "$d" != "$INSTALL_DIR" ]] && rm -rf "$d"
    done
fi

# ── Clone or update ─────────────────────────────────────────────────────────
if $IS_UPDATE; then
    info "Updating..."
    cd "$INSTALL_DIR"
    git fetch --all --quiet || die "git fetch failed. Check your internet connection."
    git reset --hard origin/main --quiet
else
    info "Downloading..."
    rm -rf "$INSTALL_DIR"
    git clone --depth 1 --quiet "$CLONE_URL" "$INSTALL_DIR" || die "git clone failed. Check your internet connection."
    cd "$INSTALL_DIR"
fi

# ── System dependencies (fresh install only) ────────────────────────────────
if ! $IS_UPDATE && [[ "$os" == "linux" ]] && [[ -n "$PM" ]]; then
    info "Installing system dependencies..."
    case "$PM" in
        apt)
            sudo apt-get update -qq 2>/dev/null
            sys_install "python3 python3-pip python3-gi gir1.2-gtk-3.0 \
                gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 \
                xclip wl-clipboard ydotool" \
                "python3 pygobject3 gtk3 libappindicator-gtk3 xclip wl-clipboard ydotool" \
                "python python-pip gobject-introspection gtk3 libappindicator-gtk3 xclip wl-clipboard ydotool"
            ;;
        dnf|pacman)
            sys_install "" \
                "python3 pygobject3 gtk3 libappindicator-gtk3 xclip wl-clipboard ydotool" \
                "python python-pip gobject-introspection gtk3 libappindicator-gtk3 xclip wl-clipboard ydotool"
            ;;
    esac
fi

# ── Wayland setup (every run) ───────────────────────────────────────────────
if [[ "$os" == "linux" ]] && { [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] || [[ -n "${WAYLAND_DISPLAY:-}" ]]; }; then
    # Ensure ydotool is installed (provides keyboard simulation on Wayland)
    if ! command -v ydotool >/dev/null 2>&1; then
        info "Installing ydotool..."
        if [[ "$PM" == "apt" ]]; then
            sudo apt-get install -y ydotool || true
        elif [[ "$PM" == "dnf" ]]; then
            sudo dnf install -y ydotool || true
        elif [[ "$PM" == "pacman" ]]; then
            sudo pacman -S --noconfirm --needed ydotool || true
        fi
        command -v ydotool >/dev/null 2>&1 || warn "ydotool not installed. Clipboard paste won't work on Wayland."
    else
        ok "ydotool already installed"
    fi

    # ydotoold (separate daemon, only in ydotool 1.0+)
    # On Ubuntu 22.04 (ydotool 0.1.8), ydotoold doesn't exist — ydotool
    # works standalone. On newer systems, ydotoold is needed.
    YDOTOOLD_BIN=""
    for yd_path in ydotoold /usr/bin/ydotoold /usr/sbin/ydotoold /usr/local/bin/ydotoold; do
        if command -v "$yd_path" >/dev/null 2>&1 || [[ -x "$yd_path" ]]; then
            YDOTOOLD_BIN="$yd_path"
            break
        fi
    done

    if [[ -n "$YDOTOOLD_BIN" ]]; then
        # ydotoold exists — start it if not running
        if ! pgrep -x ydotoold >/dev/null 2>&1; then
            info "Starting ydotoold..."
            sudo "$YDOTOOLD_BIN" &
            sleep 3
            pgrep -x ydotoold >/dev/null 2>&1 && ok "ydotoold started" || warn "ydotoold failed — start manually: sudo $YDOTOOLD_BIN &"
        else
            ok "ydotoold already running"
        fi
    fi
    # If ydotoold doesn't exist (ydotool 0.1.8), ydotool works standalone — no action needed.

    # Add to input group (for evdev keyboard access + /dev/uinput for ydotool)
    if ! groups | grep -qw input; then
        info "Adding user to 'input' group (required for Wayland hotkeys + clipboard)..."
        sudo usermod -aG input "$USER" && ok "Added to input group" || warn "usermod failed — run: sudo usermod -aG input \$USER"
        warn "LOG OUT and LOG BACK IN for the group to take effect.
Hotkeys AND clipboard paste will not work until you re-login."
    fi

    # Ensure /dev/uinput is accessible (ydotool needs it for key injection)
    if [[ -e /dev/uinput ]] && ! [[ -w /dev/uinput ]]; then
        info "Setting up /dev/uinput access for ydotool..."
        # Add udev rule so input group can write to /dev/uinput
        echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/80-uinput.rules >/dev/null
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger /dev/uinput 2>/dev/null || true
        ok "/dev/uinput udev rule added"
    fi
fi

# ── Ensure Python build/runtime deps (every run — can be removed by system updates) ─
if [[ "$os" == "linux" ]] && [[ -n "$PM" ]]; then
    # python3-venv (ensurepip)
    if ! python3 -c "import ensurepip" 2>/dev/null; then
        info "Installing ${PY_VER}-venv..."
        sys_install "${PY_VER}-venv python3-venv" "python3-virtualenv" "python-virtualenv"
        verify_module "ensurepip" "python3-venv"
    fi

    # python3-dev (Python.h for compiling C extensions)
    if [[ "$PM" == "apt" ]]; then
        if ! ls /usr/include/${PY_VER}/Python.h >/dev/null 2>&1; then
            info "Installing ${PY_VER}-dev..."
            sys_install "${PY_VER}-dev" "python3-devel" "python"
            ls /usr/include/${PY_VER}/Python.h >/dev/null 2>&1 || die "${PY_VER}-dev install failed.
Install manually: sudo apt install ${PY_VER}-dev"
        fi
    elif [[ "$PM" == "dnf" ]]; then
        if ! python3 -c "import sysconfig,os; p=sysconfig.get_path('include'); os.path.isfile(os.path.join(p,'Python.h'))" 2>/dev/null; then
            info "Installing python3-devel..."
            sys_install "" "python3-devel" "python"
        fi
    fi

    # python3-tk (tkinter)
    if ! python3 -c "import tkinter" 2>/dev/null; then
        info "Installing ${PY_VER}-tk..."
        sys_install "${PY_VER}-tk python3-tk" "python3-tkinter" "tk"
        verify_module "tkinter" "python3-tk"
    fi
fi

# ── Create venv ─────────────────────────────────────────────────────────────
info "Setting up Python environment..."
rm -rf .venv
if ! python3 -m venv .venv 2>/dev/null; then
    die "Failed to create virtual environment.
This usually means python3-venv is not installed.
  apt:    sudo apt install ${PY_VER}-venv
  dnf:    sudo dnf install python3-virtualenv
  pacman: sudo pacman -S python-virtualenv
Then re-run this installer."
fi

# ── Install pip deps ────────────────────────────────────────────────────────
VENV_PY=".venv/bin/python"

$VENV_PY -m pip install --quiet --upgrade pip || warn "pip upgrade failed (non-critical)"
if ! $VENV_PY -m pip install --quiet -r requirements.txt 2>/dev/null; then
    # Show full output on failure so user can diagnose
    warn "pip install failed. Retrying with full output..."
    $VENV_PY -m pip install -r requirements.txt || die "pip install failed.
This could be a network issue or a missing system library.
Check the error above and install any missing dependencies."
fi
ok "Python dependencies installed"

# ── Autostart + restart service ─────────────────────────────────────────────
info "Enabling autostart..."
# src/main.py handles enable/disable/status/toggle args via backward-compat
# shim — it inserts src/ onto sys.path and calls autostart.enable().
if $VENV_PY src/main.py enable 2>&1; then
    ok "Autostart enabled"
else
    warn "Autostart setup failed — the app will run but won't start on login.
Enable manually: $VENV_PY src/main.py enable
Or check Settings → Hotkeys → Start at login toggle."
fi

# Restart the systemd service so it picks up the new code + SupplementaryGroups
if [[ "$os" == "linux" ]] && systemctl --user is-enabled prompt-enhancer.service >/dev/null 2>&1; then
    info "Restarting service..."
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user restart prompt-enhancer.service 2>/dev/null && ok "Service restarted" || true
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
$IS_UPDATE && ok "Updated successfully!" || ok "Installed successfully!"
echo ""

# ── Launch (only if systemd service isn't handling it) ─────────────────────
if ! systemctl --user is-active prompt-enhancer.service >/dev/null 2>&1; then
    info "Launching..."
    $VENV_PY src/main.py &>/dev/null &
fi

echo ""
echo "  The PE icon should appear in your system tray."
echo ""
if ! $IS_UPDATE; then
    echo "  Next: click the PE icon → Settings → paste your NVIDIA API key."
    echo "  Get a free key at: https://build.nvidia.com"
    echo ""
    echo "  Hotkeys: Ctrl+Alt+E=Enhance  P=Pro  S=Shorten  X=Expand  C=Casual"
fi
echo ""
echo "  Troubleshooting:"
echo "    Check logs:   journalctl --user -u prompt-enhancer.service --since '1 min ago' --no-pager"
echo "    Restart:      systemctl --user restart prompt-enhancer.service"
echo "    Open Settings: $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/src/main.py --settings"
echo ""
