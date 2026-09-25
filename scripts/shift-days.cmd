@echo off
chcp 65001 >nul
REM Cross-day graduation test: shift existing learning timestamps back by N days
REM Usage:
REM   scripts\shift-days.cmd        show current graduation gaps only
REM   scripts\shift-days.cmd 2      move history to 2 days ago
REM   scripts\shift-days.cmd -2     move it back to real time
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if "%~1"=="" (
    python scripts\shift_learning_days.py --show
) else (
    python scripts\shift_learning_days.py --days %~1
)
exit /b %errorlevel%