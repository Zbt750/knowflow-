<#
.SYNOPSIS
启动「隔离测试后端」：APP_ENV=test + 测试库 + 独立存储目录，监听 8001。

.DESCRIPTION
为什么需要它：

端到端测试现在跑在**隔离模式**下——它拒绝连接 dev/prod 后端，只接受
`environment == "test"` 的服务。目的是防止 e2e 清空真实学习数据
（`reset_today` 会清空作答、学习事件与掌握状态，早先的 e2e 直接打开发库时
真的会动到用户数据）。

但隔离模式需要有人把这个后端起起来，而 `scripts\start-dev.cmd` 起的是
**开发**后端（8000 / dev 库）。缺了这一步，e2e 会在每个用例上重试到超时，
报出一堆看不懂的 fetch 错误。

存储目录也按每次启动的唯一运行 ID 隔离，使用前先通过只读数据库身份核验。
不设置安全默认数据库 URL；没有测试运行器的 URL 和端口所有权标记时会拒绝启动。

用法：
    # 先由隔离测试运行器在当前 PowerShell 进程中设置 TEST_DATABASE_URL 和
    # KAOYAN_OWNED_TEST_PORT，再执行下列命令。
    powershell -ExecutionPolicy Bypass -File scripts\start-test-backend.ps1
    # 停止：在这个窗口按 Ctrl+C
#>
[CmdletBinding()]
param(
    [int]$Port = 8001,
    [string]$TestDatabaseUrl = $env:TEST_DATABASE_URL,
    [string]$OwnedTestPort = $(if ($env:KAOYAN_OWNED_TEST_PORT) { $env:KAOYAN_OWNED_TEST_PORT } else { $env:PHASE45E_OWNED_TEST_PORT })
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Fail closed. Earlier defaults pointed DATABASE_URL at the ordinary kaoyan
# database; tests must receive an explicit, runner-owned isolated URL.
if (-not $TestDatabaseUrl -or -not $OwnedTestPort) {
    throw "必须由隔离测试运行器提供 TEST_DATABASE_URL 和 owned test port；未连接数据库。"
}

# 这些环境变量优先于 .env（pydantic-settings 的行为），所以隔离性是确定的。
$env:APP_ENV = "test"
$env:TEST_DATABASE_URL = $TestDatabaseUrl
$env:DATABASE_URL = $TestDatabaseUrl
$env:KAOYAN_OWNED_TEST_PORT = $OwnedTestPort
$runId = [guid]::NewGuid().ToString('N')
$runRoot = Join-Path $root 'storage/test-backend-runs'
[IO.Directory]::CreateDirectory($runRoot) | Out-Null
$runStorage = Join-Path $runRoot $runId
[IO.Directory]::CreateDirectory($runStorage) | Out-Null
$env:CHROMA_DIR = Join-Path $runStorage "chroma"
$env:UPLOAD_DIR = Join-Path $runStorage "uploads"
# 模型是本地缓存的：不联网也能跑，避免 e2e 卡在下载上。
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "隔离测试后端" -ForegroundColor Cyan
Write-Host "  APP_ENV           = $env:APP_ENV"
$identity = & python scripts/check_database_target.py
if ($LASTEXITCODE -ne 0) {
    throw "测试数据库身份核验失败；服务未启动，隔离数据目录保留在 $runStorage"
}
Write-Host "  数据库身份        = $identity"
Write-Host "  本次存储目录      = $runStorage"
Write-Host "  监听              = http://127.0.0.1:$Port"
Write-Host ""
Write-Host "启动后确认 /api/health 的 environment=test。" -ForegroundColor DarkGray
Write-Host "然后另开窗口执行：python scripts\prepare_e2e_data.py --apply" -ForegroundColor DarkGray
Write-Host "最后跑 e2e：cd frontend; npm run test:e2e" -ForegroundColor DarkGray
Write-Host "停止方式：在本窗口按 Ctrl+C；不要按端口结束进程。" -ForegroundColor DarkGray
Write-Host ""

python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port $Port --log-level warning
