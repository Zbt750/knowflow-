@echo off
chcp 65001 >nul
REM Show service status, today's plan and graduation gaps
REM Usage: scripts\status.cmd
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
python scripts\status.py
exit /b %errorlevel%