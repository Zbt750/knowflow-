@echo off
chcp 65001 >nul
REM Start local dev environment: PostgreSQL + backend + frontend
REM Usage (from project root): scripts\start-dev.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1"
exit /b %errorlevel%