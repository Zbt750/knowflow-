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
del /q "storage\backend-dev.log" >nul 2>nul
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "& python -u -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 2>&1 | Tee-Object -FilePath 'storage\backend-dev.log'"
