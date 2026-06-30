@echo off
setlocal EnableDelayedExpansion

echo.
echo   Prompt Enhancer - Installer
echo   ----------------------------
echo.

:: ── Check Python (must be REAL python, not Microsoft Store stub) ───────────
:: Try python, python3, py launcher
set "PY_CMD="

:: Try 'py' launcher first (official Python installer includes it)
where py >nul 2>&1
if not errorlevel 1 (
    py --version >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=py"
        goto :py_found
    )
)

:: Try 'python3'
where python3 >nul 2>&1
if not errorlevel 1 (
    python3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=python3"
        goto :py_found
    )
)

:: Try 'python' — but reject Microsoft Store stub
where python >nul 2>&1
if not errorlevel 1 (
    python --version >nul 2>&1
    if not errorlevel 1 (
        :: Check it's not the MS Store stub
        python -c "import sys; sys.exit(0)" >nul 2>&1
        if not errorlevel 1 (
            set "PY_CMD=python"
            goto :py_found
        )
    )
)

echo   X Python 3.10+ not found.
echo.
echo   Windows has a "Python" stub that redirects to the Microsoft Store.
echo   Install real Python from:
echo     https://www.python.org/downloads/
echo.
echo   During installation, CHECK "Add Python to PATH".
echo   Then close this window and re-run install.bat
echo.
pause
exit /b 1

:py_found
:: Verify Python version is 3.10+
%PY_CMD% -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo   X Python 3.10+ required. Found:
    %PY_CMD% --version
    echo   Install from https://python.org
    pause
    exit /b 1
)

:: ── Check git ──────────────────────────────────────────────────────────────
where git >nul 2>&1
if errorlevel 1 (
    echo   X Git not found. Install from https://git-scm.com
    pause
    exit /b 1
)

set "INSTALL_DIR=%USERPROFILE%\.local\share\prompt-enhancer"

:: ── Stop running instances ─────────────────────────────────────────────────
echo   + Stopping running instances...
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq Prompt*" >nul 2>&1
taskkill /f /im prompt-enhancer.exe >nul 2>&1

:: ── Remove old venv ────────────────────────────────────────────────────────
if exist "%INSTALL_DIR%\.venv" (
    echo   + Removing old virtual environment...
    rmdir /s /q "%INSTALL_DIR%\.venv" 2>nul
)

:: ── Clone or update ────────────────────────────────────────────────────────
if exist "%INSTALL_DIR%\.git" (
    echo   + Updating existing install...
    cd /d "%INSTALL_DIR%"
    git fetch --all
    git reset --hard origin/main
    git pull --ff-only
) else (
    echo   + Cloning to %INSTALL_DIR%...
    git clone --depth 1 https://github.com/iamakashsoni/prompt-enhancer.git "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

:: ── Create venv ────────────────────────────────────────────────────────────
echo   + Creating virtual environment...
%PY_CMD% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo   X Failed to create virtual environment.
    echo     This usually means Python is not installed correctly.
    echo     Reinstall Python from https://python.org
    echo     Make sure to CHECK "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: ── Install dependencies ──────────────────────────────────────────────────
echo   + Installing dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo   X Failed to install dependencies.
    echo     Check your internet connection and try again.
    pause
    exit /b 1
)

:: ── Autostart ──────────────────────────────────────────────────────────────
echo   + Enabling autostart...
".venv\Scripts\python.exe" src/autostart.py enable 2>nul

:: ── Done ───────────────────────────────────────────────────────────────────
echo.
echo   + Setup complete!
echo.
echo   Launching...
start "" ".venv\Scripts\pythonw.exe" src/main.py

echo.
echo   The PE icon should appear in your system tray.
echo.
echo   Next: right-click the PE icon -^> Settings -^> paste your NVIDIA API key.
echo   Get a free key at: https://build.nvidia.com
echo.
echo   Hotkeys: Ctrl+Alt+E=Enhance  P=Pro  S=Shorten  X=Expand  C=Casual
echo.
echo   Troubleshooting:
echo     Logs:     type "%USERPROFILE%\.prompt-enhancer\prompt-enhancer.log"
echo     Restart:  taskkill /f /im pythonw.exe ^& start "" ".venv\Scripts\pythonw.exe" src/main.py
echo     Settings: ".venv\Scripts\python.exe" src/main.py --settings
echo.
pause
