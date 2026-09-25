@echo off
chcp 65001 >nul
REM Load or refresh seed knowledge points and questions (idempotent)
REM Usage: scripts\seed.cmd
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
python scripts\seed.py
exit /b %errorlevel%