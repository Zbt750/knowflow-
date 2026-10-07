function Test-DevBackendHealth($Health) {
    return ($null -ne $Health -and $Health.status -eq 'ok' -and
            $Health.database -eq 'connected' -and $Health.environment -eq 'dev')
}

function Get-DevBackendProbe {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3 -ErrorAction Stop
        return @{
            Ok = (Test-DevBackendHealth $health)
            Health = $health
            ErrorCode = [string]$health.error.code
            LastError = $(if (Test-DevBackendHealth $health) { '' } else { '健康响应不是可用的本地开发服务' })
        }
    } catch {
        $failure = $_
        $body = $null
        try { $body = $failure.ErrorDetails.Message | ConvertFrom-Json -ErrorAction Stop } catch { }
        return @{
            Ok = $false
            Health = $body
            ErrorCode = [string]$body.error.code
            LastError = $(if ($body.error.message) { [string]$body.error.message } else { $failure.Exception.Message })
        }
    }
}

function Test-DevBackendOwner([string]$Root, $Process) {
    # A listener alone cannot authorize stopping it. Require this launcher's
    # local manifest, workspace, PID and start time to agree with the real process.
    try {
        if ([System.IO.Path]::GetFileName($Process.ExecutablePath) -notmatch '^pythonw?\.exe$') { return $false }
        if ($Process.CommandLine -notmatch '(?i)(?:^|[\s"/\\])run_phase4_backend\.py(?=[\s"]|$)') { return $false }
        $match = [regex]::Match($Process.CommandLine, '(?i)--manifest(?:=|\s+)(?:"([^"]+)"|([^\s]+))')
        if (-not $match.Success) { return $false }
        $argument = $(if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value })
        $workspace = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
        $path = $(if ([System.IO.Path]::IsPathRooted($argument)) { $argument } else { Join-Path $workspace $argument })
        $path = [System.IO.Path]::GetFullPath($path)
        $allowed = (Join-Path $workspace 'tmp') + [System.IO.Path]::DirectorySeparatorChar
        if (-not $path.StartsWith($allowed, [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
        $manifest = Get-Content -LiteralPath $path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ([int]$manifest.pid -ne [int]$Process.ProcessId -or
            [System.IO.Path]::GetFullPath([string]$manifest.workspace).TrimEnd('\', '/') -ne $workspace -or
            $manifest.module -ne 'backend.main:app' -or $manifest.bind -ne '127.0.0.1:8000') { return $false }
        $started = [DateTimeOffset]::Parse([string]$manifest.started_at)
        $created = [DateTimeOffset]$Process.CreationDate
        return ([Math]::Abs(($started - $created).TotalSeconds) -lt 30)
    } catch { return $false }
}
