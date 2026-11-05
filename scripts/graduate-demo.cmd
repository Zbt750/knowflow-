@echo off
chcp 65001 >nul
REM Read-only graduation gap inspection. Legacy write actions are disabled.
REM Usage:
REM   first/retest are rejected before database access; self-report is not confirmation.
REM   scripts\graduate-demo.cmd show     show current graduation gaps
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if "%~1"=="" (
    python scripts\graduate_demo.py show
) else (
    python scripts\graduate_demo.py %*
)
exit /b %errorlevel%
