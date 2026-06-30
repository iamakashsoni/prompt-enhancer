"""
Cross-platform autostart + service manager.

- Windows  : HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
             (pythonw.exe — windowless, no console)
- macOS    : ~/Library/LaunchAgents/com.promptenhancer.app.plist
             KeepAlive = restart on non-zero exit (crash recovery)
- Linux    : ~/.config/autostart/prompt-enhancer.desktop  (XDG — all DEs)
             ~/.config/systemd/user/prompt-enhancer.service (Restart=on-failure)
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from runtime import (
    app_dir,
    is_frozen,
    main_argv,
    main_executable,
    python_or_exe,
    settings_argv as runtime_settings_argv,
)

APP_NAME = "PromptEnhancer"
PLIST_ID = "com.promptenhancer.app"
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


def _win_run_value() -> str:
    exe = python_or_exe()
    if is_frozen():
        return f'"{exe}"'
    return f'"{exe}" "{main_executable()}"'


# ══════════════════════════════════════════════════════════════════════════════
#  Windows  (registry Run key)
# ══════════════════════════════════════════════════════════════════════════════

def _win_install() -> None:
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value = _win_run_value()
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, value)


def _win_uninstall() -> None:
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass


def _win_is_enabled() -> bool:
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  macOS  (LaunchAgent plist with crash recovery)
# ══════════════════════════════════════════════════════════════════════════════

def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_ID}.plist"


def _mac_install() -> None:
    exe = python_or_exe()
    log = Path.home() / ".prompt-enhancer" / "prompt-enhancer.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    # PATH includes Homebrew (Intel + Apple Silicon) and common system paths
    mac_path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    prog_args = f"<string>{exe}</string>"
    for arg in main_argv():
        prog_args += f"\n                <string>{arg}</string>"

    # KeepAlive with SuccessfulExit=false:
    #   - Restarts if the process crashes (non-zero exit)
    #   - Does NOT restart when user clicks Quit (sys.exit(0) = clean exit)
    plist = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
            "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{PLIST_ID}</string>

            <key>ProgramArguments</key>
            <array>
                {prog_args}
            </array>

            <key>RunAtLoad</key>
            <true/>

            <key>KeepAlive</key>
            <dict>
                <key>SuccessfulExit</key>
                <false/>
            </dict>

            <key>ThrottleInterval</key>
            <integer>10</integer>

            <key>StandardOutPath</key>
            <string>{log}</string>

            <key>StandardErrorPath</key>
            <string>{log}</string>

            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>{mac_path}</string>
            </dict>
        </dict>
        </plist>
    """)

    p = _plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(plist, encoding="utf-8")

    # Unload any existing version first, then load fresh
    subprocess.run(["launchctl", "unload", str(p)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load",   str(p)], check=False)


def _mac_uninstall() -> None:
    p = _plist_path()
    if p.exists():
        subprocess.run(["launchctl", "unload", str(p)], check=False, capture_output=True)
        p.unlink(missing_ok=True)


def _mac_is_enabled() -> bool:
    return _plist_path().exists()


# ══════════════════════════════════════════════════════════════════════════════
#  Linux  (XDG autostart + systemd user service with Restart=on-failure)
# ══════════════════════════════════════════════════════════════════════════════

def _desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / "prompt-enhancer.desktop"


def _systemd_service_path() -> Path:
    return (
        Path.home() / ".config" / "systemd" / "user" / "prompt-enhancer.service"
    )


def _linux_session_env() -> list[str]:
    """Environment lines for systemd user service (tray, keyring, Wayland)."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    dbus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if not dbus or dbus == "autolaunch:":
        bus_socket = Path(runtime) / "bus"
        if bus_socket.exists():
            dbus = f"unix:path={bus_socket}"

    lines = [
        "Environment=PYTHONUNBUFFERED=1",
        "Environment=DISPLAY=:0",
        f"Environment=XDG_RUNTIME_DIR={runtime}",
    ]
    if dbus:
        lines.append(f"Environment=DBUS_SESSION_BUS_ADDRESS={dbus}")
    wayland = os.environ.get("WAYLAND_DISPLAY")
    if wayland:
        lines.append(f"Environment=WAYLAND_DISPLAY={wayland}")
    session_type = os.environ.get("XDG_SESSION_TYPE")
    if session_type:
        lines.append(f"Environment=XDG_SESSION_TYPE={session_type}")
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
    if sys.platform == "win32":
        return _win_is_enabled()
    elif sys.platform == "darwin":
        return _mac_is_enabled()
    else:
        return _linux_is_enabled()


def enable() -> None:
    """Install autostart entry for the current OS. Idempotent."""
    if sys.platform == "win32":
        _win_install()
    elif sys.platform == "darwin":
        _mac_install()
    else:
        _linux_install()


def disable() -> None:
    """Remove autostart entry. Idempotent."""
    if sys.platform == "win32":
        _win_uninstall()
    elif sys.platform == "darwin":
        _mac_uninstall()
    else:
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

    if sys.platform == "win32":
        import subprocess as sp
        sp.Popen(
            cmd,
            creationflags=sp.DETACHED_PROCESS | sp.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
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
        from settings_launcher import run_settings_window
        run_settings_window()
