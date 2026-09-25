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

存储目录也一起隔离：
- `CHROMA_DIR=storage/chroma-test`
- `UPLOAD_DIR=storage/uploads-test`
否则测试资料会被写进**开发用的向量库**，e2e 删资料时又只按 id 基线清理，
容易在开发索引里留下孤儿向量。

用法：
    powershell -ExecutionPolicy Bypass -File scripts\start-test-backend.ps1
    # 停止：Ctrl+C（或关闭窗口）
#>
[CmdletBinding()]
param(
    [int]$Port = 8001,
    [string]$TestDatabaseUrl = "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan_test",
    [string]$DatabaseUrl = "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 这些环境变量优先于 .env（pydantic-settings 的行为），所以隔离性是确定的。
$env:APP_ENV = "test"
$env:TEST_DATABASE_URL = $TestDatabaseUrl
# DATABASE_URL 是必填项，但它在本进程里不会被使用（Settings 只认 test_database_url）。
$env:DATABASE_URL = $DatabaseUrl
$env:CHROMA_DIR = Join-Path $root "storage/chroma-test"
$env:UPLOAD_DIR = Join-Path $root "storage/uploads-test"
# 模型是本地缓存的：不联网也能跑，避免 e2e 卡在下载上。
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "隔离测试后端" -ForegroundColor Cyan
Write-Host "  APP_ENV           = $env:APP_ENV"
Write-Host "  测试库            = kaoyan_test"
Write-Host "  向量目录          = $env:CHROMA_DIR"
Write-Host "  上传目录          = $env:UPLOAD_DIR"
Write-Host "  监听              = http://127.0.0.1:$Port"
Write-Host ""
Write-Host "启动后请确认：curl http://127.0.0.1:$Port/api/health 里 environment 应为 test" -ForegroundColor DarkGray
Write-Host "然后另开窗口执行：python scripts\prepare_e2e_data.py --apply" -ForegroundColor DarkGray
Write-Host "最后跑 e2e：cd frontend; npm run test:e2e" -ForegroundColor DarkGray
Write-Host ""

python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port $Port --log-level warning
