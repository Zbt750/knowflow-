@echo off
REM ============================================================
REM  Prepare the data that e2e needs, in the ISOLATED test database.
REM
REM  Why this step exists:
REM  e2e runs against the isolated test backend (APP_ENV=test, port 8001)
REM  so it can never wipe real learning data. But the test database has no
REM  materials of its own -- pytest fixtures TRUNCATE it, and seed.py only
REM  seeds knowledge points and questions, not materials. Without this step
REM  every materials/chat e2e case fails with "no materials to test against".
REM
REM  It is idempotent: it first clears ALL materials in the test database
REM  (plus chat rows that reference them) and then re-ingests from scratch,
REM  so a failed run never leaves a half-state behind.
REM
REM  Storage is isolated too (storage/chroma-test, storage/uploads-test) so
REM  the development vector index is untouched.
REM
REM  Usage: scripts\prepare-e2e-data.cmd
REM ============================================================

set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

set APP_ENV=test
set TEST_DATABASE_URL=postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan_test
set DATABASE_URL=postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan
set CHROMA_DIR=%~dp0..\storage\chroma-test
set UPLOAD_DIR=%~dp0..\storage\uploads-test
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1

python scripts\prepare_e2e_data.py --apply
if errorlevel 1 exit /b 1
exit /b 0
