@echo off
chcp 65001 >nul
REM Reset today's plan so the "generate today's paper" button can be used again
REM Usage: scripts\reset-today.cmd
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
python scripts\reset_today.py
exit /b %errorlevel%