@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv || goto fail
call .venv\Scripts\activate.bat || goto fail
python -m pip install --upgrade pip pyinstaller || goto fail
python -m pip install -r requirements.txt || goto fail
pyinstaller --noconfirm --clean --onefile --windowed --name ToriDownload --icon tori.ico --add-data "tori-logo.png;." --collect-all pystray --collect-all yt_dlp --collect-all imageio_ffmpeg app.py || goto fail
python package_portable.py "dist\ToriDownload.exe" "extension" "release-dist\ToriDownload-Portable-v0.22.zip" || goto fail
set "ISCC_PATH="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH (
  where ISCC.exe >nul 2>nul
  if not errorlevel 1 set "ISCC_PATH=ISCC.exe"
)
if not defined ISCC_PATH (
  echo Portable ZIP is ready in release-dist.
  echo Install Inno Setup 6, then double-click this BAT again to also make the installer.
  pause
  exit /b 2
)
"%ISCC_PATH%" installer.iss || goto fail
echo Both release files are ready in release-dist:
echo   ToriDownload-Setup-v0.22.exe
echo   ToriDownload-Portable-v0.22.zip
pause
exit /b 0
:fail
echo Build failed. Send a screenshot of this window to diagnose it.
pause
exit /b 1
