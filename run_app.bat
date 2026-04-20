@echo off
setlocal ENABLEDELAYEDEXPANSION

cd /d "%~dp0"

if exist "%~dp0bin" (
  set "PATH=%~dp0bin;%PATH%"
  echo Using local ffmpeg tools from "%~dp0bin"
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python is not installed or not in PATH.
  pause
  exit /b 1
)

if not exist "requirements.txt" (
  echo [ERROR] requirements.txt not found in project root.
  pause
  exit /b 1
)

echo Checking and installing missing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency check/install failed.
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [WARNING] ffmpeg not found in PATH. Video export and frame extraction may fail.
)

where ffprobe >nul 2>nul
if errorlevel 1 (
  echo [WARNING] ffprobe not found in PATH. Opening videos will fail.
  echo          Install FFmpeg and add its bin folder to PATH.
)

echo Starting application...
python -m app.main
if errorlevel 1 (
  echo [ERROR] Application exited with error.
  pause
  exit /b 1
)

exit /b 0
