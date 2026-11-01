# DeepSeek 全量大题生成启动脚本（Windows 宿主机）
# 默认只做 API 连通性检查 + dry-run；加 -Start 才调用 API。
#
# 用法：
#   .\scripts\run_long_question_api.ps1
#   .\scripts\run_long_question_api.ps1 -Start -MaxCalls 160
#   .\scripts\run_long_question_api.ps1 -Start -MaxCostCny 10
#
# 预算必须至少给一个；不打印 API Key。

param(
    [string]$PythonExe = "python",
    [switch]$Start,
    [int]$MaxCalls = 0,
    [double]$MaxCostCny = 0,
    [int]$BatchNodes = 10
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Test-Path ".env")) { throw "Missing .env" }
if (-not (Test-Path "handoff/long-question-full-20261018/node_coverage.csv")) {
    throw "Missing node_coverage.csv"
}

Write-Host "=== 1. DeepSeek API connectivity check ==="
& $PythonExe scripts/long_question_api_worker.py --check-api
if ($LASTEXITCODE -ne 0) {
    throw "DeepSeek API is unavailable or configuration is incomplete; generation was not started. Check host network, proxy, and API configuration."
}

Write-Host "`n=== 2. Current coverage gap dry-run ==="
& $PythonExe scripts/long_question_api_worker.py --dry-run
if ($LASTEXITCODE -ne 0) { throw "Dry-run failed." }

if (-not $Start) {
    Write-Host "`n[dry-run only] API is reachable. Add -Start -MaxCalls N or -MaxCostCny N to begin generation."
    exit 0
}
if ($MaxCalls -le 0 -and $MaxCostCny -le 0) {
    throw "Budget required: provide -MaxCalls N or -MaxCostCny N."
}

$workerArgs = @("scripts/long_question_api_worker.py", "--execute", "--batch-nodes", "$BatchNodes")
if ($MaxCalls -gt 0) { $workerArgs += @("--max-calls", "$MaxCalls") }
if ($MaxCostCny -gt 0) { $workerArgs += @("--max-cost-cny", "$MaxCostCny") }

Write-Host "`n=== 3. Starting full generation (resume enabled) ==="
& $PythonExe @workerArgs
$code = $LASTEXITCODE
Write-Host "`nworker exit=$code"
Write-Host "Progress: handoff/long-question-full-20261018/api_progress.json"
Write-Host "Handoff package: handoff/long-question-full-20261018/"
exit $code
