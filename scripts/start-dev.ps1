# 一键启动本地开发环境：PostgreSQL + 后端 + 前端
#
# 用法（项目根执行）：
#   powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
#
# 停止：
#   powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1
#
# 后端与前端在后台启动；同时输出写进 storage\backend-dev.log 与
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
# 2026-10-16 改动，起因是一次"脚本说 PG 启动失败、但页面还能用"的排障：
#
#   现象：1/3 报「启动失败（等了 60 秒）」，日志尾部只有 autovacuum 警告；
#         同一时刻后端 /api/health 却是 database=connected。
#
#   根因：PostgreSQL 进程其实一直活着（15:40 启动），但已经不再接受新连接
#         ——pg_isready 全程 no response，后端日志里刷了 63 次
#         "server closed the connection unexpectedly"，autovacuum 连一个 worker
#         都拉不起来（225 次 "took too long to start"）。旧提示把这误报成"启动失败"。
#
#   本次改动：
#     1. pg_isready 带 -U/-d（从 .env 的 DATABASE_URL 解析，回退 kaoyan）。
#        不带 -U 时它默认用 Windows 用户名当角色名，会往 PG 日志里刷
#        FATAL: role "ZBT" does not exist，也和后端连的账号不是同一个。
#     2. 区分「没起来」与「在监听但拒绝新连接」：后者直接判定实例卡死，
#        并打印具体修复命令，不再只丢一句"启动失败"。
#     3. 端口已在监听时缩短等待（15 秒）：卡死时等满 60 秒也不会有结果。
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Continue'

# 项目根：本脚本在 scripts/ 下，上一级就是根目录。
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'dev-service-health.ps1')
$pgBin = 'C:\Program Files\PostgreSQL\18\bin'
$pgData = Join-Path $root '.pgdata'
$storageDir = Join-Path $root 'storage'
$pgLog = Join-Path $storageDir 'postgres-dev.log'
$backendLog = Join-Path $storageDir 'backend-dev.log'
$frontendLog = Join-Path $storageDir 'frontend-dev.log'

# pg_isready 不指定 -U 时，默认拿「当前 Windows 用户名」当角色名。本集群里没有这个角色，
# 于是每次探测都会往 PG 日志写一条 FATAL: role "ZBT" does not exist —— 既刷噪音，
# 又让探测用的身份和后端实际连接的身份（.env 里的 DATABASE_URL）不是同一个。
function Get-PgIdentity {
    $userName = 'kaoyan'
    $dbName = 'kaoyan'
    $envPath = Join-Path $root '.env'
    if (Test-Path $envPath) {
        $line = Get-Content $envPath -ErrorAction SilentlyContinue |
            Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
        if ($line -and ($line -match '://([^:/@]+)(:[^@]*)?@[^/]+/([A-Za-z0-9_]+)')) {
            $userName = $Matches[1]
            $dbName = $Matches[3]
        }
    }
    return @{ User = $userName; Db = $dbName }
}
$pgIdent = Get-PgIdentity

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

# 端口被监听不等于数据库可用：PostgreSQL 启动过程中会先监听端口，但此时连接会被拒绝
# （"the database system is starting up"），后端 lifespan 的 SELECT 1 会直接失败退出。
# 因此必须用 pg_isready 判定“真的能接受连接”。
# 注意必须带 -U/-d：用后端一致的账号探测，且 2026-10-16 之前不带 -U 会往 PG 日志刷
# FATAL: role "ZBT" does not exist。
# -t 5 显式给超时：默认 3 秒，机器繁忙时可能不够而误判成 no response。
function Test-PgReady([int]$Port = 5433) {
    & (Join-Path $pgBin 'pg_isready.exe') -h 127.0.0.1 -p $Port -U $pgIdent.User -d $pgIdent.Db -t 5 *> $null
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
        $probe = Get-DevBackendProbe
        if ($probe.Ok) {
            return @{
                Ok            = $true
                Health        = $probe.Health
                WaitedSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
                LastError     = ''
            }
        }
        $lastError = $probe.LastError
        if ($probe.ErrorCode -eq 'instance_lock_lost') { break }
        Start-Sleep -Milliseconds 500
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
            # PG 崩溃恢复会扫描数据目录；日志句柄放在目录内可触发 Windows sharing violation。
            New-Item -ItemType Directory -Path $storageDir -Force | Out-Null
            Start-Process -FilePath (Join-Path $pgBin 'pg_ctl.exe') `
                -ArgumentList @('-D', $pgData, '-l', $pgLog,
                                '-o', '"-p 5433 -c listen_addresses=127.0.0.1"', 'start') `
                -WorkingDirectory $root -WindowStyle Hidden | Out-Null
        }
        # 端口已在监听 => 不是冷启动。若是卡死，等满 60 秒也不会有结果，缩短等待更快出结论。
        $pgWait = 60
        if (Test-Port 5433) { $pgWait = 15 }
        if (Wait-PgReady 5433 $pgWait) {
            Write-Host '  已启动'
        } else {
            if (Test-Port 5433) {
                # 2026-10-16：区分「没起来」与「起来了但拒绝新连接」。
                # 后者是实例卡死：pg_isready 报 no response、后端日志报
                # "server closed the connection unexpectedly"，但已建立的连接仍能用，
                # 所以页面看起来是正常的 —— 旧提示会把这种情况误报成"启动失败"。
                Write-Host "  5433 在监听，但 $pgWait 秒内始终不接受新连接 —— 这个实例很可能已经卡死。" -ForegroundColor Red
                Write-Host '  自检：backend-dev.log 里若出现 server closed the connection unexpectedly，即是此症。' -ForegroundColor Yellow
                Write-Host '  修复（在项目根执行这两条）：' -ForegroundColor Yellow
                Write-Host "    & '$pgBin\pg_ctl.exe' -D '$pgData' -m fast stop"
                Write-Host "    & '$pgBin\pg_ctl.exe' -D '$pgData' -l '$pgLog' -o `"-p 5433 -c listen_addresses=127.0.0.1`" start"
                Write-Host '  若 stop 迟迟不返回，用 .pgdata\postmaster.pid 第一行的 PID 强制结束' -ForegroundColor Yellow
                Write-Host '  （会走崩溃恢复，数据由 WAL 兜底）：taskkill /F /PID <那个 PID>'
            } else {
                Write-Host "  启动失败（等了 $pgWait 秒）" -ForegroundColor Red
            }
            Show-LogTail $pgLog 20
            $failed += 'PostgreSQL'
        }
    }
}

# ---------------------------------------------------------------------------
# 2/3 后端 FastAPI
# ---------------------------------------------------------------------------
Write-Host '=== 2/3 后端 FastAPI ===' -ForegroundColor Cyan
$launchBackend = -not (Test-Port 8000)
if (-not $launchBackend) {
    $probe = Get-DevBackendProbe
    if ($probe.Ok) {
        $backendPids = @(Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
        $owner = $(if ($backendPids.Count -eq 1) { Get-CimInstance Win32_Process -Filter "ProcessId=$($backendPids[0])" } else { $null })
        if ($owner -and (Test-DevBackendOwner $root $owner)) {
            if (Test-DevBackendSnapshotCurrent $root $owner) {
                Write-Host '  已在运行且健康检查通过（端口 8000）'
            } else {
                Write-Host '  后端源码与启动快照不一致，正在重启本项目后端以加载最新代码…' -ForegroundColor Yellow
                try {
                    Stop-Process -Id $owner.ProcessId -Force -ErrorAction Stop
                    for ($i = 0; $i -lt 80 -and (Test-Port 8000); $i++) { Start-Sleep -Milliseconds 100 }
                    $launchBackend = -not (Test-Port 8000)
                    if (-not $launchBackend) { throw '旧后端端口尚未释放' }
                } catch {
                    Write-Host "  无法安全重启后端：$($_.Exception.Message)" -ForegroundColor Red
                    $failed += '后端'
                }
            }
        } else {
            Write-Host '  端口 8000 健康，但无法核对启动进程归属；为安全起见不自动停止。' -ForegroundColor Yellow
        }
    } elseif ($probe.ErrorCode -eq 'instance_lock_lost') {
        $backendPids = @(Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
        $owner = $(if ($backendPids.Count -eq 1) { Get-CimInstance Win32_Process -Filter "ProcessId=$($backendPids[0])" } else { $null })
        if ($owner -and (Test-DevBackendOwner $root $owner)) {
            Write-Host '  检测到本项目后端丢失数据库锁，正在重新启动该失效实例…' -ForegroundColor Yellow
            try {
                Stop-Process -Id $owner.ProcessId -Force -ErrorAction Stop
                for ($i = 0; $i -lt 50 -and (Test-Port 8000); $i++) { Start-Sleep -Milliseconds 100 }
                $launchBackend = -not (Test-Port 8000)
                if (-not $launchBackend) { throw '失效后端端口尚未释放' }
            } catch {
                Write-Host "  无法恢复后端：$($_.Exception.Message)" -ForegroundColor Red
                $failed += '后端'
            }
        } else {
            Write-Host '  后端已失去数据库锁，但无法核对进程归属；未停止该进程。' -ForegroundColor Red
            $failed += '后端'
        }
    } else {
        Write-Host '  端口已监听，正在确认服务是否真正就绪…' -ForegroundColor Yellow
    }
}
if ($launchBackend) {
    # 后台独立进程；输出落盘，并写启动清单供后续核对进程归属。
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/c', ('"' + (Join-Path $root 'scripts\run-backend.cmd') + '"')) `
        -WorkingDirectory $root -WindowStyle Hidden | Out-Null
}
if ($failed -notcontains '后端') {
    $health = Wait-BackendReady
    if ($health.Ok) {
        $backendLabel = $(if ($launchBackend) { '已启动' } else { '健康检查通过' })
        Write-Host "  $backendLabel（status=$($health.Health.status), database=$($health.Health.database)，等了 $($health.WaitedSeconds) 秒）"
    } else {
        Write-Host "  [!] 健康检查未通过（等了 $($health.WaitedSeconds) 秒），服务尚不可用。" -ForegroundColor Red
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
                -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden | Out-Null
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
    if ($failed -contains 'PostgreSQL') {
        Write-Host '  提示：PostgreSQL 卡死时，已经建立的连接仍然可用，页面可能暂时看着正常；' -ForegroundColor Yellow
        Write-Host '        但只要有新连接（刷新数据、重启后端）就会失败。请先按上面第 1 步给的两条命令重启它。' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host '常用命令（在 CMD 里直接敲）：' -ForegroundColor Yellow
Write-Host '  scripts\reset-today.cmd      重置今日学习，可重新生成练习卷'
Write-Host '  scripts\status.cmd           查看服务、今日学习与毕业条件'
Write-Host '  scripts\shift-days.cmd 2     跨天毕业测试：把历史挪到 2 天前'
Write-Host '  scripts\test.cmd             跑全部测试'
Write-Host '  scripts\stop-dev.cmd         停止全部服务'

if ($failed.Count -eq 0) { exit 0 } else { exit 1 }
