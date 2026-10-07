@echo off
REM ============================================================
REM  Start the ISOLATED test backend (APP_ENV=test, port 8001).
REM
REM  e2e refuses to run against a dev/prod backend so that test runs can never
REM  wipe real learning data, so this is the backend e2e expects.
REM
REM  Runs in the current window (visible logs). Stop with Ctrl+C, or use
REM  scripts\stop-test-backend.cmd from another window.
REM
REM  Usage: scripts\start-test-backend.cmd
REM ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-test-backend.ps1"
