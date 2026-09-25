# 停止本地开发环境（PostgreSQL + 后端 + 前端）
# 用法（项目根执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1

$root = Split-Path -Parent $PSScriptRoot
$pgBin = 'C:\Program Files\PostgreSQL\18\bin'
$pgData = Join-Path $root '.pgdata'

function Stop-ByPort([int]$Port, [string]$Label) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "  $Label 未运行"
        return
    }
    foreach ($conn in $conns) {
        # 只结束监听该端口的进程；父进程（cmd/npm）随后会自行退出。
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Write-Host "  $Label 已停止"
}

Write-Host '=== 停止前端与后端 ===' -ForegroundColor Cyan
Stop-ByPort 5173 '前端 (5173)'
Stop-ByPort 8000 '后端 (8000)'

Write-Host '=== 停止 PostgreSQL ===' -ForegroundColor Cyan
if (Test-Path $pgData) {
    & (Join-Path $pgBin 'pg_ctl.exe') -D $pgData -m fast stop 2>&1 | Out-Null
    Write-Host '  PostgreSQL 已停止'
} else {
    Write-Host '  未找到数据目录，跳过'
}