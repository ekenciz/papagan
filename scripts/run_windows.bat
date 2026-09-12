@echo off
setlocal
set ROOT=%~dp0..
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo Sanal ortam bulunamadi. Once install_windows.bat calistirin.
  pause
  exit /b 1
)
set HF_HUB_DISABLE_SYMLINKS=1
"%ROOT%\.venv\Scripts\python.exe" -m epub2m4b.app
