# 一键启动本地开发环境：PostgreSQL + 后端 + 前端
#
# 用法（项目根执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
#
# 停止：
#   powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1
#
# 后端与前端会各开一个独立窗口；同时输出写进 storage\backend-dev.log 与
# storage\frontend-dev.log。脚本在确认三个服务状态后立刻退出，不会挂住终端。
#
# ---------------------------------------------------------------------------
# 2026-09-23 重写，起因是一次"后端启动失败但页面打不开"的排障：
#
#   现象：脚本报「2/3 后端启动失败或健康检查未通过」，用户以为后端坏了；
#         实际后端起来了、/api/health 200，真正打不开的原因是**前端根本没被启动**。
#
#   根因：旧版第 2 步一旦健康检查没过就 `exit 1`，第 3 步（启动前端）永不执行。
#         一个健康检查的假阴性，直接把前端也一起放弃了。
#
#   另一处：旧版不给后端留任何日志（PG 有 .pgdata\server.log，后端没有），
#         错误只落在那句"请查看窗口"所指的独立窗口里，事后无法回溯 ——
#         这就是当时查不出原因的真正原因。
#
#   本次改动：
#     1. 三个服务各自独立尝试，**任何一个失败都不阻断后面的**，最后统一给结论。
#     2. 后端/前端输出落盘；任何一步失败，直接把该日志**尾部**打出来。
#     3. 新增第 0 步「解释器自检」：把 python 的真实路径和"有没有 uvicorn"
#        明确报出来。裸 `python` 指向缺依赖的解释器，是"秒退 + 健康检查全灭"
#        最常见的原因，值得在启动前就说清楚。
#     4. 每次等待都报"等了多久"，超时时报最后一次的错误。
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Continue'

# 项目根：本脚本在 scripts/ 下，上一级就是根目录。
$root = Split-Path -Parent $PSScriptRoot
$pgBin = 'C:\Program Files\PostgreSQL\18\bin'
$pgData = Join-Path $root '.pgdata'
$storageDir = Join-Path $root 'storage'
$backendLog = Join-Path $storageDir 'backend-dev.log'
$frontendLog = Join-Path $storageDir 'frontend-dev.log'

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

# 端口被监听不等于数据库可用：PostgreSQL 启动过程中会先监听端口，但此时连接会被拒绝
# （"the database system is starting up"），后端 lifespan 的 SELECT 1 会直接失败退出。
# 因此必须用 pg_isready 判定“真的能接受连接”。
function Test-PgReady([int]$Port = 5433) {
    & (Join-Path $pgBin 'pg_isready.exe') -h 127.0.0.1 -p $Port *> $null
    return ($LASTEXITCODE -eq 0)
}

function Wait-Port([int]$Port, [int]$TimeoutSeconds = 40) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-PgReady([int]$Port = 5433, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PgReady $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# 后端就绪判定：等 /api/health 真的能应答。
# 用 Invoke-RestMethod 而不是 Invoke-WebRequest：后者在本机对某些响应会长时间阻塞。
# 返回一个 hashtable：Ok / WaitedSeconds / LastError。不再只回 $null，
# 这样超时时能把"等了多久、最后一次什么错"报出来。
function Wait-BackendReady([int]$TimeoutSeconds = 120) {
    $started = Get-Date
    $deadline = $started.AddSeconds($TimeoutSeconds)
    $lastError = ''
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3
            return @{
                Ok            = $true
                Health        = $health
                WaitedSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
                LastError     = ''
            }
        } catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 500
        }
    }
    return @{
        Ok            = $false
        Health        = $null
        WaitedSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        LastError     = $lastError
    }
}

# 打印日志尾部。失败时把原因直接摆到终端上，而不是让用户去翻独立窗口。
# 日志用 Tee-Object 写出（PowerShell 默认 Unicode），所以一律用 Get-Content 读，
# 不要用 cmd 的 type。
#
# 噪音过滤：PowerShell 5.1 会把子进程写到 stderr 的每一行都包成 NativeCommandError，
# 于是日志里夹着 "At line:1 char:1" / "+ CategoryInfo" / "+ FullyQualifiedErrorId"
# 这类装饰行。真正有用的那行其实在装饰块前面（形如 "python.exe : INFO: ..."），
# 这里把装饰行滤掉，只留能读的。
function Show-LogTail([string]$Path, [int]$Lines = 20) {
    Write-Host "  ---- $Path （最后 $Lines 行）----" -ForegroundColor DarkGray
    if (-not (Test-Path $Path)) {
        Write-Host '  （日志还没生成 —— 说明进程可能连启动都没走到）' -ForegroundColor DarkGray
        return
    }
    $content = @(Get-Content -Path $Path -ErrorAction SilentlyContinue)
    $clean = @()
    foreach ($line in $content) {
        $t = "$line".TrimEnd()
        if ($t -match '^(At line:|CategoryInfo|FullyQualifiedErrorId)') { continue }
        if ($t -match '^\s*\+') { continue }
        if ($t -eq '') { continue }
        $clean += $t
    }
    $tail = @($clean | Select-Object -Last $Lines)
    if ($tail.Count -eq 0) {
        Write-Host '  （日志是空的）' -ForegroundColor DarkGray
        return
    }
    foreach ($line in $tail) { Write-Host "  $line" -ForegroundColor DarkGray }
}

$failed = @()

# ---------------------------------------------------------------------------
# 0/3 解释器自检
# ---------------------------------------------------------------------------
Write-Host '=== 0/3 解释器自检 ===' -ForegroundColor Cyan
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pyCmd) {
    Write-Host '  [X] PATH 上找不到 python' -ForegroundColor Red
    Write-Host '     前端仍可启动，但后端一定起不来。请先修好 PATH 再重跑。' -ForegroundColor Yellow
    $failed += '解释器'
} else {
    $pyPath = $pyCmd.Source
    Write-Host "  python -> $pyPath"
    & python -c "import uvicorn" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host '  [OK] 该解释器里有 uvicorn'
    } else {
        Write-Host '  [X] 该解释器里没有 uvicorn —— 后端会秒退，健康检查必然全灭。' -ForegroundColor Red
        Write-Host '     这通常说明 PATH 上的 python 不是装了依赖的那一个。' -ForegroundColor Yellow
        Write-Host '     检查：where python   （第一行应指向装了依赖的解释器）' -ForegroundColor Yellow
        Write-Host '     临时绕过（不影响自动启动）：' -ForegroundColor Yellow
        Write-Host "       & '$pyPath' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000" -ForegroundColor Yellow
        $failed += '解释器'
    }
}

# ---------------------------------------------------------------------------
# 1/3 PostgreSQL
# ---------------------------------------------------------------------------
Write-Host '=== 1/3 PostgreSQL ===' -ForegroundColor Cyan
if (Test-PgReady 5433) {
    Write-Host '  已在运行且可接受连接（端口 5433）'
} else {
    if (-not (Test-Path $pgData)) {
        Write-Host "  找不到数据目录 $pgData" -ForegroundColor Red
        Write-Host '  请先初始化集群：' -ForegroundColor Yellow
        Write-Host "  & '$pgBin\initdb.exe' -D '$pgData' -U postgres -E UTF8 --locale=C -A trust"
        $failed += 'PostgreSQL'
    } else {
        # 端口未监听才需要拉起；pg_ctl start 会占住控制台，所以用独立进程并立刻返回。
        if (-not (Test-Port 5433)) {
            Start-Process -FilePath (Join-Path $pgBin 'pg_ctl.exe') `
                -ArgumentList @('-D', $pgData, '-l', (Join-Path $pgData 'server.log'),
                                '-o', '"-p 5433 -c listen_addresses=127.0.0.1"', 'start') `
                -WorkingDirectory $root -WindowStyle Hidden | Out-Null
        }
        if (Wait-PgReady 5433) {
            Write-Host '  已启动'
        } else {
            Write-Host '  启动失败（等了 60 秒）' -ForegroundColor Red
            Show-LogTail (Join-Path $pgData 'server.log') 20
            $failed += 'PostgreSQL'
        }
    }
}

# ---------------------------------------------------------------------------
# 2/3 后端 FastAPI
# ---------------------------------------------------------------------------
Write-Host '=== 2/3 后端 FastAPI ===' -ForegroundColor Cyan
if (Test-Port 8000) {
    Write-Host '  已在运行（端口 8000）'
} else {
    # 独立窗口：日志直接可见，且不会把标准输出句柄传给本脚本（否则脚本无法退出）。
    # 窗口里的输出同时落盘到 $backendLog（见 run-backend.cmd）。
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/k', (Join-Path $root 'scripts\run-backend.cmd')) `
        -WorkingDirectory $root | Out-Null
    $health = Wait-BackendReady
    if ($health.Ok) {
        Write-Host "  已启动（status=$($health.Health.status), database=$($health.Health.database)，等了 $($health.WaitedSeconds) 秒）"
    } else {
        Write-Host "  [!]  健康检查未通过（等了 $($health.WaitedSeconds) 秒）—— 但**这不代表后端坏了**，往下看。" -ForegroundColor Red
        if ($health.LastError -ne '') {
            Write-Host "  最后一次请求的错误：$($health.LastError)" -ForegroundColor DarkGray
        }
        Show-LogTail $backendLog 20
        Write-Host '  自查：上面的日志里若出现 "No module named uvicorn" 之类，' -ForegroundColor Yellow
        Write-Host '        说明 PATH 上的 python 不是装了依赖的那个（见第 0 步）。' -ForegroundColor Yellow
        $failed += '后端'
    }
}

# ---------------------------------------------------------------------------
# 3/3 前端 Vite —— 无论后端成功与否都要尝试启动
# （旧版在这里因为第 2 步 exit 1 而永远执行不到，是"页面打不开"的直接原因）
# ---------------------------------------------------------------------------
Write-Host '=== 3/3 前端 Vite ===' -ForegroundColor Cyan
if (Test-Port 5173) {
    Write-Host '  已在运行（端口 5173）'
} else {
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/k', (Join-Path $root 'scripts\run-frontend.cmd')) `
        -WorkingDirectory (Join-Path $root 'frontend') | Out-Null
    # Vite 首次要预构建依赖，给足超时；端口监听即视为就绪。
    if (Wait-Port 5173 90) {
        Write-Host '  已启动'
    } else {
        Write-Host '  启动失败（等了 90 秒）' -ForegroundColor Red
        Show-LogTail $frontendLog 20
        $failed += '前端'
    }
}

# ---------------------------------------------------------------------------
# 结论
# ---------------------------------------------------------------------------
Write-Host ''
if ($failed.Count -eq 0) {
    Write-Host '全部就绪：' -ForegroundColor Green
    Write-Host '  前端      http://127.0.0.1:5173'
    Write-Host '  后端      http://127.0.0.1:8000'
    Write-Host '  健康检查  http://127.0.0.1:8000/api/health'
    Write-Host '  API 文档  http://127.0.0.1:8000/docs'
} else {
    Write-Host ("有服务没起来：" + ($failed -join '、')) -ForegroundColor Red
    Write-Host '  每个失败项的日志尾部已打印在上面；完整日志：' -ForegroundColor Yellow
    Write-Host "    后端  $backendLog"
    Write-Host "    前端  $frontendLog"
    Write-Host '  注意：后端失败也可能只是慢 —— 用下面的命令确认它其实起没起：' -ForegroundColor Yellow
    Write-Host '    curl http://127.0.0.1:8000/api/health'
}

Write-Host ''
Write-Host '常用命令（在 CMD 里直接敲）：' -ForegroundColor Yellow
Write-Host '  scripts\reset-today.cmd      重置今日学习，可重新生成练习卷'
Write-Host '  scripts\status.cmd           查看服务、今日学习与毕业条件'
Write-Host '  scripts\shift-days.cmd 2     跨天毕业测试：把历史挪到 2 天前'
Write-Host '  scripts\test.cmd             跑全部测试'
Write-Host '  scripts\stop-dev.cmd         停止全部服务'

if ($failed.Count -eq 0) { exit 0 } else { exit 1 }
