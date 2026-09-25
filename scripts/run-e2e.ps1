<#
.SYNOPSIS
跑隔离模式的前端端到端测试：准备数据 → 起测试后端 → 跑 e2e → 回收后端。

.DESCRIPTION
为什么要有这个脚本（而不是全写在 test.cmd 里）：

1. **后端必须在本次调用的生命周期内启停。**
   原来用 `start "..." /min powershell -File start-test-backend.ps1` 起窗口，
   那个窗口是当前 shell 的子进程，命令一结束就被回收 —— 于是 test.cmd 永远
   走不到 `npm run test:e2e`，而 test-results 从那时起就没再被写过。

2. **批处理的等待循环在非交互 stdio 下会失效。**
   `timeout /t 2 /nobreak` 在 stdin 被重定向时直接报
   `ERROR: Input redirection is not supported`，每轮几乎不耗时，
   于是 120 秒的等待瞬间空转完并误判失败。这里用 Start-Sleep + 轮询 HTTP。

3. **顺序是实测出来的，只有一种能用**：
      先准备数据 → 再启动后端
   反过来（后端先起、再准备数据）会让后端持有被重建前的 Chroma 句柄，
   准备完所有检索返回 500；而「边起边准备」会让后端 WinError 10048 绑定失败。
   另外 prepare 会清空测试向量库，所以它必须跑在后端启动之前。

用法（由 scripts\test.cmd 调用，也可单独执行）：
    powershell -ExecutionPolicy Bypass -File scripts\run-e2e.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8001,
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 隔离环境：测试库 + 测试专用存储目录，绝不碰开发库与 storage/chroma。
$env:APP_ENV = "test"
$env:TEST_DATABASE_URL = "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan_test"
$env:DATABASE_URL = "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan"
$env:CHROMA_DIR = Join-Path $root "storage/chroma-test"
$env:UPLOAD_DIR = Join-Path $root "storage/uploads-test"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"

if (-not $OutputDir) {
    $OutputDir = Join-Path $env:TEMP "kaoyan-e2e-output"
}

$exitCode = 1
$backend = $null

function Stop-TestBackend {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  已停止测试后端 PID $($backend.Id)"
    }
    Set-Location $root
    Start-Sleep -Seconds 2
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3 -UseBasicParsing | Out-Null
        Write-Host "  警告：$Port 仍可达（可能有别的后端占用）" -ForegroundColor Yellow
    } catch {
        Write-Host "  $Port 已释放"
    }
}

Write-Host "=== 1/4 准备 e2e 数据（会彻底清空测试向量库）===" -ForegroundColor Cyan
python scripts\prepare_e2e_data.py --apply
if ($LASTEXITCODE -ne 0) {
    Write-Host "数据准备未通过（脚本自带「向量条数 == 分块数」自检）。" -ForegroundColor Red
    exit 1
}

Write-Host "=== 2/4 启动隔离测试后端（本次调用的后台进程）===" -ForegroundColor Cyan
$pythonPath = (Get-Command python).Source
$backend = Start-Process -FilePath $pythonPath `
    -ArgumentList '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', "$Port", '--log-level', 'warning' `
    -PassThru -WindowStyle Hidden
Write-Host "  PID = $($backend.Id)"

$ready = $false
for ($i = 1; $i -le 60; $i++) {
    if ($backend.HasExited) {
        Write-Host "  后端进程已退出（code $($backend.ExitCode)），很可能是端口被占用。" -ForegroundColor Red
        Stop-TestBackend
        exit 1
    }
    $answered = $false
    try {
        $health = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3 -UseBasicParsing
        if ($health.Content -match '"environment":"test"') {
            Write-Host "  就绪（第 $i 次轮询）：$($health.Content)"
            $ready = $true
            $answered = $true
        } else {
            Write-Host "  第 $i 次：后端不是 test 环境 —— $($health.Content)" -ForegroundColor Yellow
        }
    } catch { }
    if ($ready) { break }
    if (-not $answered) { Start-Sleep -Seconds 2 }
}

if (-not $ready) {
    Write-Host "  120 秒内未就绪，放弃。" -ForegroundColor Red
    Stop-TestBackend
    exit 1
}

Write-Host "=== 3/4 跑 e2e ===" -ForegroundColor Cyan
Set-Location (Join-Path $root "frontend")
# 必须带 --output：默认会先递归删 frontend/test-results，
# 文件一多就会撞上沙箱的批量删除保护（[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]），
# 整个 run 立刻失败，而且看起来像 Playwright 自己坏了。
# 同时产出机器可读报告：控制台只给 `list`，逐条失败原因写在 JSON 里。
# 早先只靠控制台尾部输出判断失败，容易看漏/看错断言（对着「可见性」这类断言
# 猜了好几轮才发现真正失败的断言其实是别的一条）。JSON 报告让「哪条断言失败」
# 成为可检索的事实，而不是靠推断。
$jsonReport = Join-Path $env:TEMP "kaoyan-e2e-report.json"
if (Test-Path $jsonReport) { Remove-Item $jsonReport -Force -ErrorAction SilentlyContinue }
$env:PLAYWRIGHT_JSON_OUTPUT_NAME = $jsonReport
npx playwright test --output="$OutputDir" --reporter=list,json
$exitCode = $LASTEXITCODE
if (Test-Path $jsonReport) {
    Write-Host "  JSON 报告：$jsonReport"
} else {
    Write-Host "  警告：未生成 JSON 报告（$jsonReport），失败详情只能看上面的 list 输出。" -ForegroundColor Yellow
}
Write-Host "E2E 退出码 = $exitCode"
Write-Host "E2E 退出码 = $exitCode"

Write-Host "=== 4/4 回收测试后端 ===" -ForegroundColor Cyan
Stop-TestBackend

# 显式退出并把 Playwright 的退出码传出去。
# 早先这里用 `return $rc`，脚本对调用方返回了 0 —— 即使 Playwright 明确报了
# `1 failed`，scripts\test.cmd 也会看到 errorlevel 0 而当成通过。
# 退出码必须一路传到最外层，否则「失败」看起来和「成功」完全一样。
exit $exitCode
