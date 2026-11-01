# 大题库一键导入闭环（Windows 宿主机 PowerShell）
#
# 默认：校验 + dry-run（不写库）。
# 正式执行：加 -Execute；默认只导 39 道 PASS；加 -IncludeReview 连同 11 道 REVIEW 作为参考练习导入。
#
# 示例：
#   .\scripts\run_long_question_import.ps1 `
#     -DatabaseUrl "postgresql+psycopg://kaoyan:***@127.0.0.1:5433/kaoyan_test"
#
#   .\scripts\run_long_question_import.ps1 `
#     -DatabaseUrl "postgresql+psycopg://kaoyan:***@127.0.0.1:5433/kaoyan_test" -Execute
#
#   .\scripts\run_long_question_import.ps1 `
#     -DatabaseUrl "..." -Execute -IncludeReview
#
# 安全：硬拒绝 kaoyan；要求 *_test；打印 host/port/database；不打印密码。

param(
    [string]$DatabaseUrl = $env:TEST_DATABASE_URL,
    [string]$PythonExe = "python",
    [switch]$Execute,
    [switch]$IncludeReview
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
if (-not (Test-Path "backend/services/long_question_bank.py")) {
    throw "项目目录不正确：缺少 backend/services/long_question_bank.py"
}
if (-not (Test-Path "content/long_question_packs")) {
    throw "项目目录不正确：缺少 content/long_question_packs"
}
if (-not $DatabaseUrl) { throw "缺少 -DatabaseUrl（或设置 TEST_DATABASE_URL）" }

$plain = $DatabaseUrl -replace "^postgresql\+psycopg://", "postgresql://"
$uri = [System.Uri]$plain
$database = $uri.AbsolutePath.TrimStart("/")
if ($database -eq "kaoyan") { throw "拒绝：目标是正式开发库 kaoyan。请使用隔离的 *_test 库。" }
if ($database -notlike "*_test") { throw "拒绝：库名 '$database' 不是 *_test。" }
Write-Host "[target] host=$($uri.Host) port=$($uri.Port) database=$database"

$env:APP_ENV = "test"
$env:TEST_DATABASE_URL = $DatabaseUrl

$packs = @(
    [pscustomobject]@{ File = "content/long_question_packs/pilot_20261018.json"; Batch = "longbank-20261018-pilot"; Tag = "pilot"; Ex = 2 },
    [pscustomobject]@{ File = "content/long_question_packs/os_batch01_20261018.json"; Batch = "longbank-20261018-os01"; Tag = "os01"; Ex = 1 },
    [pscustomobject]@{ File = "content/long_question_packs/ds_batch01_20261018.json"; Batch = "longbank-20261018-ds01"; Tag = "ds01"; Ex = 1 },
    [pscustomobject]@{ File = "content/long_question_packs/co_batch01_20261018.json"; Batch = "longbank-20261018-co01"; Tag = "co01"; Ex = 1 },
    [pscustomobject]@{ File = "content/long_question_packs/cn_batch01_20261018.json"; Batch = "longbank-20261018-cn01"; Tag = "cn01"; Ex = 1 }
)

Write-Host "`n=== 1. 数据库身份确认（只读） ==="
& $PythonExe scripts/check_database_target.py --expect-database $database
if ($LASTEXITCODE -ne 0) { throw "数据库身份确认失败；未执行任何写入。" }

Write-Host "`n=== 2. 内容包校验 + 三级审核 ==="
foreach ($p in $packs) {
    & $PythonExe scripts/validate_long_question_pack.py --pack $p.File `
        --out "docs/long-question-validation-$($p.Tag)-20261018.json" `
        --report "docs/long-question-validation-$($p.Tag)-20261018.md"
    if ($LASTEXITCODE -ne 0) { throw "校验失败：$($p.File)" }

    & $PythonExe scripts/triage_long_question_pack.py --pack $p.File `
        --validation "docs/long-question-validation-$($p.Tag)-20261018.json" `
        --out "docs/long-question-triage-$($p.Tag)-20261018.json" `
        --report "docs/long-question-triage-$($p.Tag)-20261018.md"
    if ($LASTEXITCODE -ne 0) { throw "审核失败：$($p.File)" }
}

Write-Host "`n=== 3. 导入 dry-run（默认只 PASS） ==="
foreach ($p in $packs) {
    $importArgs = @("scripts/import_long_question_bank.py", "--pack", $p.File, "--dry-run",
                    "--verdicts", "docs/long-question-triage-$($p.Tag)-20261018.json")
    if ($IncludeReview) { $importArgs += "--include-review" }
    & $PythonExe @importArgs
    if ($LASTEXITCODE -ne 0) { throw "dry-run 失败：$($p.File)" }
}

if (-not $Execute) {
    Write-Host "`n[dry-run only] 内容包已通过。确认后加 -Execute 正式写入 $database。"
    Write-Host "提示：默认只导 39 PASS；加 -IncludeReview 会连同 11 REVIEW 作为参考练习导入（仍保留 PENDING）。"
    exit 0
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$batchArgs = @()
foreach ($p in $packs) { $batchArgs += @("--batch-key", $p.Batch) }

Write-Host "`n=== 4. 导入前数据库基线 ==="
$pre = "docs/long-question-db-pre-$stamp.json"
& $PythonExe scripts/long_question_db_report.py @batchArgs --out $pre
if ($LASTEXITCODE -ne 0) { throw "导入前统计失败" }
$preJson = Get-Content $pre -Raw | ConvertFrom-Json

Write-Host "`n=== 5. 正式导入（第一遍） ==="
foreach ($p in $packs) {
    $importArgs = @("scripts/import_long_question_bank.py", "--pack", $p.File,
                    "--confirm-database", $database,
                    "--verdicts", "docs/long-question-triage-$($p.Tag)-20261018.json")
    if ($IncludeReview) { $importArgs += "--include-review" }
    & $PythonExe @importArgs
    if ($LASTEXITCODE -ne 0) { throw "导入失败：$($p.File)" }
}

$post1 = "docs/long-question-db-post1-$stamp.json"
& $PythonExe scripts/long_question_db_report.py @batchArgs --out $post1
if ($LASTEXITCODE -ne 0) { throw "导入后统计失败" }
$post1Json = Get-Content $post1 -Raw | ConvertFrom-Json

Write-Host "`n=== 6. 第二次导入（幂等验证） ==="
foreach ($p in $packs) {
    $importArgs = @("scripts/import_long_question_bank.py", "--pack", $p.File,
                    "--confirm-database", $database,
                    "--verdicts", "docs/long-question-triage-$($p.Tag)-20261018.json")
    if ($IncludeReview) { $importArgs += "--include-review" }
    & $PythonExe @importArgs
    if ($LASTEXITCODE -ne 0) { throw "第二轮导入失败：$($p.File)" }
}

$post2 = "docs/long-question-db-post2-$stamp.json"
& $PythonExe scripts/long_question_db_report.py @batchArgs --out $post2
if ($LASTEXITCODE -ne 0) { throw "第二轮统计失败" }
$post2Json = Get-Content $post2 -Raw | ConvertFrom-Json

if ($post1Json.total_questions -ne $post2Json.total_questions -or
    $post1Json.total_versions -ne $post2Json.total_versions) {
    throw "幂等失败：第二轮题数/版本数发生变化（$($post1Json.total_questions) → $($post2Json.total_questions)）"
}
if ($post2Json.public_leak -ne 0) { throw "安全失败：批次内出现非 personal 题" }

Write-Host "`n=== 7. 闭环核验（版本/资格/节点题库/练习项/作答事件） ==="
$verifyResults = @()
foreach ($p in $packs) {
    $verifyArgs = @("scripts/verify_long_question_bank.py", "--batch-key", $p.Batch,
                    "--exercise", "--exercise-count", "$($p.Ex)")
    if (-not $IncludeReview) { $verifyArgs += "--allow-partial" }
    & $PythonExe @verifyArgs
    $rc = $LASTEXITCODE
    $verifyPath = "docs/long-question-verify-$($p.Batch).json"
    $verifyJson = if (Test-Path $verifyPath) { Get-Content $verifyPath -Raw | ConvertFrom-Json } else { $null }
    $verifyResults += [pscustomobject]@{
        batch = $p.Batch
        exit = $rc
        passed = if ($verifyJson) { $verifyJson.passed } else { $false }
        report = $verifyPath
    }
    if ($rc -ne 0) { throw "核验失败：$($p.Batch)" }
}

Write-Host "`n=== 8. 生成闭环报告 ==="
$packMeta = @()
foreach ($p in $packs) {
    $packMeta += [pscustomobject]@{
        file = $p.File
        batch_key = $p.Batch
        sha256 = (Get-FileHash -Path $p.File -Algorithm SHA256).Hash.ToLower()
    }
}
$summary = [ordered]@{
    timestamp = (Get-Date).ToString("o")
    database = $post2Json.database
    host = $post2Json.server_addr
    port = $post2Json.server_port
    include_review = [bool]$IncludeReview
    packs = $packMeta
    baseline = $preJson
    after_first_import = $post1Json
    after_second_import = $post2Json
    idempotent = ($post1Json.total_questions -eq $post2Json.total_questions -and
                  $post1Json.total_versions -eq $post2Json.total_versions)
    verify = $verifyResults
}
$summaryPath = "docs/long-question-import-closure-$stamp.json"
$summary | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 $summaryPath

Write-Host "`n=== 完成 ==="
Write-Host "题目：$($post2Json.total_questions)　版本：$($post2Json.total_versions)　public 泄漏：$($post2Json.public_leak)"
Write-Host "幂等：$($summary.idempotent)"
Write-Host "闭环报告：$summaryPath"
Write-Host "批次统计：$post1 / $post2"
