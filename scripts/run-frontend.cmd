@echo off
REM 前端启动器：供 start-dev.ps1 在新窗口中调用
REM
REM 2026-09-23 改动：输出同时写进 ..\storage\frontend-dev.log（理由同 run-backend.cmd）。
title 前端 Vite 5173
cd /d "%~dp0..\frontend"
if not exist "..\storage" mkdir "..\storage"
del /q "..\storage\frontend-dev.log" >nul 2>nul
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "& npm run dev 2>&1 | Tee-Object -FilePath '..\storage\frontend-dev.log'"
