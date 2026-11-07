@echo off
setlocal
cd /d "%~dp0"

title NAIWA Study Project

if not exist "scripts\start-dev.ps1" goto launcher_missing
where powershell.exe >nul 2>&1
if errorlevel 1 goto powershell_missing

echo Starting the NAIWA local database, backend, and frontend...
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "scripts\start-dev.ps1"
set "STARTUP_EXIT_CODE=%ERRORLEVEL%"
if not "%STARTUP_EXIT_CODE%"=="0" goto startup_failed

echo.
echo Startup succeeded. Opening the study page...
start "" "http://127.0.0.1:5173/study"
echo To stop services, run: scripts\stop-dev.cmd
echo.
pause
exit /b 0

:launcher_missing
echo ERROR: scripts\start-dev.ps1 was not found.
echo Keep this file in the project root directory.
goto startup_failed

:powershell_missing
echo ERROR: powershell.exe was not found on PATH.
goto startup_failed

:startup_failed
echo.
echo Startup failed. Check the messages above and these logs:
echo storage\postgres-dev.log
echo storage\backend-dev.log
echo storage\frontend-dev.log
echo.
pause
exit /b 1
