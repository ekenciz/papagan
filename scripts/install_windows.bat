@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1"
if errorlevel 1 (
  echo.
  echo Kurulum basarisiz. Yukaridaki hata mesajini kontrol edin.
  pause
  exit /b 1
)
echo.
echo Kurulum tamamlandi. run_windows.bat ile uygulamayi baslatabilirsiniz.
pause
