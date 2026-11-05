@echo off
REM ============================================================
REM  Do not terminate an arbitrary process by port. The matching start script
REM  runs in the foreground; stop it with Ctrl+C in its own window.
REM
REM  Usage: scripts\stop-test-backend.cmd
REM ============================================================

echo No process was stopped. Stop only the test backend window you started by pressing Ctrl+C there.

exit /b 0
