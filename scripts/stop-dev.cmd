@echo off
chcp 65001 >nul
REM Stop all services
REM Usage: scripts\stop-dev.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-dev.ps1"
exit /b %errorlevel%