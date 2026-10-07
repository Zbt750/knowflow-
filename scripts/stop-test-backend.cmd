@echo off
REM ============================================================
REM  Stop the ISOLATED test backend (whatever listens on port 8001).
REM
REM  Only touches the process owning port 8001, so it can never stop the
REM  development backend on 8000 or any other service.
REM
REM  Usage: scripts\stop-test-backend.cmd
REM ============================================================

set PORT=8001

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('stopped test backend pid ' + $c.OwningProcess) } else { Write-Host 'no test backend on port %PORT%' }"

exit /b 0
