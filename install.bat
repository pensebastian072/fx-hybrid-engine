@echo off
REM One-step install for the FX Hybrid Engine dashboard (Windows). Double-click me.
REM Installs the Next.js dashboard in ui\, builds it, then starts it and opens your browser.
REM The Python research engine is separate: see README (pip install -e ".[dev]").
setlocal EnableExtensions
cd /d "%~dp0ui"
title FX Hybrid Engine - install
echo.
echo  Installing the FX Hybrid Engine dashboard (first build takes a few minutes) ...
echo.
where node >nul 2>nul
if errorlevel 1 goto :nonode
call npm ci --no-audit --no-fund
if errorlevel 1 goto :fail
call npm run build
if errorlevel 1 goto :fail
echo.
echo  Installed. Next time just double-click start.bat
echo.
call "%~dp0start.bat"
exit /b 0

:nonode
echo  Node.js 20 or newer was not found.
echo  Install the LTS version from https://nodejs.org/ then double-click install.bat again.
if not defined NO_BROWSER pause
exit /b 1

:fail
echo.
echo  Install failed - see the messages above.
if not defined NO_BROWSER pause
exit /b 1
