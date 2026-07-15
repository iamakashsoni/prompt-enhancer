"""
Linux autostart + systemd user service manager.

- systemd user service: ~/.config/systemd/user/prompt-enhancer.service
  Restart=on-failure, restarts automatically after crashes.
- XDG autostart fallback: ~/.config/autostart/prompt-enhancer.desktop
  Used only when systemd --user is unavailable (minimal DEs, SSH).
"""
import os
import subprocess
from pathlib import Path

from prompt_enhancer.platform.runtime import (
    app_dir,
    is_frozen,
    main_argv,
    main_executable,
    python_or_exe,
    settings_argv as runtime_settings_argv,
)

SCRIPT_DIR = app_dir()


def python_exe() -> str:
    return python_or_exe()


def settings_argv() -> list[str]:
    return runtime_settings_argv()


def _exec_start() -> str:
    """Single string for systemd ExecStart / desktop Exec."""
    exe = python_or_exe()
    tail = main_argv()
    if tail:
        return f"{exe} {' '.join(tail)}"
    return exe


# ══════════════════════════════════════════════════════════════════════════════
#  Linux  (XDG autostart + systemd user service with Restart=on-failure)
# ══════════════════════════════════════════════════════════════════════════════

def _desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / "prompt-enhancer.desktop"


def _systemd_service_path() -> Path:
    return (
        Path.home() / ".config" / "systemd" / "user" / "prompt-enhancer.service"
    )


def _detect_wayland_display(runtime: str) -> str | None:
    env = os.environ.get("WAYLAND_DISPLAY", "").strip()
    if env:
        return env
    for name in ("wayland-0", "wayland-1"):
        if (Path(runtime) / name).exists():
            return name
    return None


def _detect_x_display() -> str | None:
    env = os.environ.get("DISPLAY", "").strip()
    if env and env not in (":0", ":0.0"):
        return env
    # Prefer a live X socket over a stale DISPLAY=:0 from a previous session.
    for n in range(0, 5):
        if Path(f"/tmp/.X11-unix/X{n}").exists():
            return f":{n}"
    if env and Path("/tmp/.X11-unix/X0").exists():
        return env
    return None


def _systemd_user_env_vars() -> dict[str, str]:
    """Pull display/session vars already imported into the user manager."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {}
    if result.returncode != 0:
        return {}
    wanted = {
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XDG_SESSION_TYPE",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "PATH",
    }
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key in wanted and val:
            out[key] = val
    return out


def _linux_session_env() -> list[str]:
    """Environment lines for systemd user service (tray, keyring, Wayland, network).

    Includes proxy env vars (HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY) because
    many users route AI traffic through a local proxy (Clash, v2ray, etc.).
    Without these, the service can reach the network but times out hitting
    NVIDIA — while the user's interactive shell (which has the proxy env)
    works fine. This was the root cause of "hotkey not firing" reports.
    """
    mgr = _systemd_user_env_vars()
    runtime = (
        os.environ.get("XDG_RUNTIME_DIR")
        or mgr.get("XDG_RUNTIME_DIR")
        or f"/run/user/{os.getuid()}"
    )
    dbus = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or mgr.get("DBUS_SESSION_BUS_ADDRESS")
    if not dbus or dbus == "autolaunch:":
        bus_socket = Path(runtime) / "bus"
        if bus_socket.exists():
            dbus = f"unix:path={bus_socket}"

    wayland = _detect_wayland_display(runtime) or mgr.get("WAYLAND_DISPLAY")
    display = _detect_x_display() or mgr.get("DISPLAY")
    # Never hardcode DISPLAY=:0 when the X socket is missing — that caused
    # pynput ImportError crash-loops under Wayland-only / early-boot systemd.
    if display in (":0", ":0.0") and not Path("/tmp/.X11-unix/X0").exists():
        display = None

    session_type = (
        os.environ.get("XDG_SESSION_TYPE")
        or mgr.get("XDG_SESSION_TYPE")
        or ("wayland" if wayland else ("x11" if display else None))
    )

    lines = [
        "Environment=PYTHONUNBUFFERED=1",
        f"Environment=XDG_RUNTIME_DIR={runtime}",
    ]
    if display:
        lines.append(f"Environment=DISPLAY={display}")
    if dbus:
        lines.append(f"Environment=DBUS_SESSION_BUS_ADDRESS={dbus}")
    if wayland:
        lines.append(f"Environment=WAYLAND_DISPLAY={wayland}")
    if session_type:
        lines.append(f"Environment=XDG_SESSION_TYPE={session_type}")

    # PATH — needed so the service can find ydotool, wl-copy, xclip, etc.
    # systemd user services get a minimal PATH by default.
    path = os.environ.get("PATH") or mgr.get("PATH")
    if path:
        lines.append(f"Environment=PATH={path}")

    # Proxy env vars — pass through whatever the install-time shell has.
    # Both lowercase and uppercase variants because some tools check only one.
    for var in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        val = os.environ.get(var)
        if val:
            lines.append(f"Environment={var}={val}")

    return lines

def _linux_has_systemd_user() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _linux_install() -> None:
    if _linux_has_systemd_user():
        # Prefer systemd only — XDG .desktop would start a duplicate at login.
        _desktop_path().unlink(missing_ok=True)

        env_lines = _linux_session_env()
        service = (
            "[Unit]\n"
            "Description=Prompt Enhancer - AI text enhancement hotkey tool\n"
            "After=graphical-session.target\n"
            "PartOf=graphical-session.target\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={_exec_start()}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
            + "\n".join(env_lines)
            + "\n\n"
            "[Install]\n"
            "WantedBy=graphical-session.target\n"
        )
        sp = _systemd_service_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(service, encoding="utf-8")

        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False, capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "prompt-enhancer.service"],
            check=False, capture_output=True,
        )
        return

    # Fallback when systemd user session is unavailable (minimal DEs, SSH, etc.)
    _systemd_service_path().unlink(missing_ok=True)

    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Prompt Enhancer\n"
        "Comment=AI-powered text enhancement hotkey tool\n"
        f"Exec={_exec_start()}\n"
        "Icon=utilities-terminal\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "StartupNotify=false\n"
        "Terminal=false\n"
    )
    dp = _desktop_path()
    dp.parent.mkdir(parents=True, exist_ok=True)
    dp.write_text(desktop, encoding="utf-8")
    dp.chmod(0o755)


def _linux_uninstall() -> None:
    try:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "prompt-enhancer.service"],
            check=False, capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass

    _desktop_path().unlink(missing_ok=True)
    _systemd_service_path().unlink(missing_ok=True)


def _linux_is_enabled() -> bool:
    if _systemd_service_path().exists():
        return True
    return _desktop_path().exists()


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def is_enabled() -> bool:
    """Return True if autostart is currently configured."""
    return _linux_is_enabled()


def enable() -> None:
    """Install autostart entry. Idempotent."""
    _linux_install()


def disable() -> None:
    """Remove autostart entry. Idempotent."""
    _linux_uninstall()


def toggle() -> bool:
    """Toggle autostart. Returns the new state (True = enabled)."""
    if is_enabled():
        disable()
        return False
    else:
        enable()
        return True


def launch_now() -> None:
    """Start the app in the background right now (used by installers)."""
    cmd = [python_or_exe(), *main_argv()]
    log = Path.home() / ".prompt-enhancer" / "prompt-enhancer.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as lf:
        subprocess.Popen(
            cmd,
            stdout=lf,
            stderr=lf,
            start_new_session=True,
        )


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Manage Prompt Enhancer autostart")
    parser.add_argument(
        "action",
        choices=["enable", "disable", "status", "toggle", "launch", "settings"],
        help="Action to perform",
    )
    args = parser.parse_args()

    if args.action == "enable":
        enable()
        print("Autostart enabled.")
    elif args.action == "disable":
        disable()
        print("Autostart disabled.")
    elif args.action == "toggle":
        state = toggle()
        print(f"Autostart {'enabled' if state else 'disabled'}.")
    elif args.action == "status":
        print(f"Autostart is {'ENABLED' if is_enabled() else 'DISABLED'}.")
    elif args.action == "launch":
        launch_now()
        print("Prompt Enhancer launched in background.")
    elif args.action == "settings":
        from prompt_enhancer.ui.settings_launcher import run_settings_window
        run_settings_window()
