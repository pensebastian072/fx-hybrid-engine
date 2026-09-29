@echo off
REM Start the FX Hybrid Engine dashboard and open it in your browser.
REM Runs on this computer only (127.0.0.1). Sign-in is off unless you add Clerk keys to ui\.env.local.
setlocal EnableExtensions
cd /d "%~dp0ui"
title FX Hybrid Engine
if not exist ".next\BUILD_ID" (
  echo  Not installed yet - running install.bat first...
  call "%~dp0install.bat"
  exit /b
)
set "PORT=3055"
set "FXHE_UI_LOCAL_MODE=true"
set "URL=http://127.0.0.1:%PORT%/dashboard/overview"
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%)).Close();exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 (
  echo  The dashboard is already running - opening %URL%
  start "" "%URL%"
  exit /b 0
)
if not defined NO_BROWSER start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 240;$i++){try{(New-Object Net.Sockets.TcpClient('127.0.0.1',%PORT%)).Close();Start-Process '%URL%';exit}catch{Start-Sleep -Milliseconds 500}}"
echo.
echo  FX Hybrid Engine dashboard is starting at %URL%
echo  Your browser opens by itself when it is ready. Close this window to stop.
echo.
call npx next start -H 127.0.0.1 -p %PORT%
echo.
echo  Dashboard stopped.
if not defined NO_BROWSER pause
