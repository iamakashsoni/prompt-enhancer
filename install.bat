@echo off
setlocal EnableDelayedExpansion

echo.
echo   Prompt Enhancer - Installer
echo   ----------------------------
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo   X Python not found. Install from https://python.org
    pause
    exit /b 1
)

:: Check git
where git >nul 2>&1
if errorlevel 1 (
    echo   X Git not found. Install from https://git-scm.com
    pause
    exit /b 1
)

set "INSTALL_DIR=%USERPROFILE%\.local\share\prompt-enhancer"

:: Stop any running instance
echo   + Stopping running instances...
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq Prompt*" >nul 2>&1
taskkill /f /im prompt-enhancer.exe >nul 2>&1

:: Remove old venv if exists (force fresh deps)
if exist "%INSTALL_DIR%\.venv" (
    echo   + Removing old virtual environment...
    rmdir /s /q "%INSTALL_DIR%\.venv" 2>nul
)

:: Clone or update
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

:: Virtual environment
echo   + Creating virtual environment...
python -m venv .venv

echo   + Installing dependencies...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

:: Autostart
echo   + Enabling autostart...
".venv\Scripts\python.exe" src/autostart.py enable 2>nul

:: Launch
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
pause
