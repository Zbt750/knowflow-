@echo off
chcp 65001 >nul
REM Graduation demo: prepare state so you can graduate today
REM Usage:
REM   scripts\graduate-demo.cmd first    prepare day 1 (finish questions, then shift 2 days back)
REM   scripts\graduate-demo.cmd retest   prepare the retest day (put a review question in today's paper)
REM   scripts\graduate-demo.cmd show     show current graduation gaps
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if "%~1"=="" (
    python scripts\graduate_demo.py show
) else (
    python scripts\graduate_demo.py %*
)
exit /b %errorlevel%