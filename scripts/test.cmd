@echo off
REM ============================================================
REM  Run all tests: backend pytest, migration check,
REM  frontend typecheck+build, frontend e2e.
REM
REM  Usage: scripts\test.cmd
REM
REM  NOTE: this file is intentionally pure ASCII. A .cmd containing
REM  Chinese text combined with "chcp 65001" fails to parse on this
REM  machine (the console code page is switched while cmd.exe is
REM  still reading the file). Chinese messages live in the .ps1/
REM  .py helpers instead.
REM
REM  pytest and e2e have OPPOSITE prerequisites:
REM    - pytest uses the separate kaoyan_test database and must run
REM      with the backend STOPPED (memory pressure; a running backend
REM      once got PostgreSQL killed by the OS).
REM    - e2e drives a real browser against /api/* and needs the
REM      backend RUNNING.
REM  Each step keeps its OWN skip flag. A single shared counter looks
REM  natural but is wrong: "backend is running" would then skip e2e
REM  as well, while printing the opposite reason.
REM ============================================================

set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

set SKIPPED_PYTEST=0
set SKIPPED_E2E=0

echo ============================================
echo  0/4 environment check before pytest
echo ============================================
python scripts\check_test_env.py --strict
if errorlevel 1 set SKIPPED_PYTEST=1

echo.
echo ============================================
echo  1/4 backend pytest
echo ============================================
if %SKIPPED_PYTEST% NEQ 0 goto :skip_pytest
python -m pytest -q
if errorlevel 1 goto :failed
goto :step2

:skip_pytest
echo SKIPPED: backend appears to be running.
echo Stop it (scripts\stop-dev.cmd) and re-run this script so that
echo the backend test suite is actually executed.

:step2
echo.
echo ============================================
echo  2/4 alembic check
echo ============================================
python -m alembic check
if errorlevel 1 goto :failed

echo.
echo ============================================
echo  3/4 frontend typecheck and build
echo ============================================
cd frontend
call npm run typecheck
if errorlevel 1 goto :failed
call npm run build
if errorlevel 1 goto :failed

echo.
echo ============================================
echo  4/4 frontend e2e (isolated test backend)
echo ============================================
REM e2e runs against an ISOLATED test backend on 8001 (APP_ENV=test), so a test
REM run can never touch real learning data.
REM
REM The sequencing and process lifetime are easy to get wrong, so they live in
REM scripts\run-e2e.ps1 rather than here:
REM   - the backend must be a child of THE SAME invocation (a `start /min` window
REM     is reaped when the invoking shell exits, which made this step never reach
REM     npm run test:e2e at all);
REM   - the data must be prepared BEFORE the backend starts (preparation clears
REM     the test vector collection; a backend started earlier keeps a stale
REM     handle and answers every search with 500);
REM   - `timeout /t` fails under redirected stdin ("Input redirection is not
REM     supported"), which silently turned the wait loop into a no-op.
echo Delegating to scripts\run-e2e.ps1 (prepare data, start backend, run e2e, stop backend)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-e2e.ps1"
if errorlevel 1 goto :failed
goto :done

REM The test backend used to be started/stopped here, which is why this file once
REM needed a :failed_after_backend path. That responsibility now lives entirely in
REM scripts\run-e2e.ps1 (it owns the backend for the duration of one invocation).

:done
cd ..
echo.
set /a SKIPPED_TOTAL=SKIPPED_PYTEST+SKIPPED_E2E
if %SKIPPED_TOTAL% NEQ 0 goto :partial
echo All tests passed.
exit /b 0

:partial
echo PARTIAL: %SKIPPED_TOTAL% step^(s^) were skipped, so this run does NOT
echo prove the suite passes. See the SKIPPED notes above.
exit /b 1

:failed
echo.
echo Tests FAILED, see output above.
exit /b 1
