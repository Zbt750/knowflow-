@echo off
REM 后端启动器：供 start-dev.ps1 在新窗口中调用（cmd 支持 &&，PowerShell 5.1 不支持）
REM
REM 2026-09-23 改动：输出同时写进 storage\backend-dev.log。
REM 起因：启动失败时后端输出只落在这个窗口里，窗口一关就再也查不到原因，
REM       start-dev.ps1 只能报一句"请查看窗口"。
REM 注意：这里仍然用 PATH 上的 python（自检在 start-dev.ps1 里做，会用 where python 报出来）。
title 后端 FastAPI 8000
cd /d "%~dp0.."
if not exist storage mkdir storage
REM 保留已有日志，避免恢复失效实例时删除排障证据。
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$stamp=[guid]::NewGuid().ToString('N'); & python -u scripts/run_phase4_backend.py --manifest ('tmp/dev-backend-manifests/runtime-'+$stamp+'.json') 2>&1 | Tee-Object -FilePath 'storage\backend-dev.log' -Append"
