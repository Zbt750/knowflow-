[CmdletBinding()]
param([switch]$SkipBackend)

$ErrorActionPreference = 'Continue'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$startedAt = (Get-Date).ToUniversalTime().ToString('o')
$runId = [guid]::NewGuid().ToString('N')
$output = Join-Path $root ("storage/quality-audits/test-all-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + "-" + $runId.Substring(0, 8))
New-Item -ItemType Directory -Path $output -ErrorAction Stop | Out-Null
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-Logged([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    $log = Join-Path $output ($Name + '.log')
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments *> $log
        $code = $LASTEXITCODE
    } catch {
        $_ | Out-String | Set-Content -LiteralPath $log -Encoding utf8
        $code = 1
    } finally { Pop-Location }
    $entry = [pscustomobject]@{ name = $Name; exit_code = $code; log = [IO.Path]::GetRelativePath($output, $log) }
    $results.Add($entry)
    Write-Host ("{0}: exit={1}; log={2}" -f $Name, $code, $log)
    return $code
}

function Set-LastStatus([string]$Status, [hashtable]$Extra = @{}) {
    $current = $results[$results.Count - 1]
    $entry = [ordered]@{ name = $current.name; exit_code = $current.exit_code; status = $Status; log = $current.log }
    foreach ($key in $Extra.Keys) { $entry[$key] = $Extra[$key] }
    $results[$results.Count - 1] = [pscustomobject]$entry
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
$pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
$frontend = Join-Path $root 'frontend'

if ($pwsh) {
    $doctorCode = Invoke-Logged 'doctor' $pwsh @('-NoProfile', '-File', (Join-Path $PSScriptRoot 'doctor.ps1'), '-SkipFrontendSmoke') $root
    if ($doctorCode -ge 2) { Set-LastStatus 'BLOCKED' }
    elseif ($doctorCode -eq 1) { Set-LastStatus 'WARN' }
} else { $results.Add([pscustomobject]@{ name = 'doctor'; exit_code = $null; status = 'BLOCKED'; reason = 'pwsh.exe unavailable' }) }

if (-not $SkipBackend -and $python) {
    $backendOutput = Join-Path $output 'backend'
    $backendCode = Invoke-Logged 'backend-postgres-pytest' $python @('scripts/test_backend.py', '--output-dir', $backendOutput) $root
    $backendSummaryPath = Join-Path $backendOutput 'test-summary.json'
    if (Test-Path -LiteralPath $backendSummaryPath) {
        try {
            $backendSummary = Get-Content -LiteralPath $backendSummaryPath -Raw | ConvertFrom-Json
            if ($backendSummary.status -eq 'BLOCKED') {
                Set-LastStatus 'BLOCKED' @{ summary = 'backend/test-summary.json' }
            } elseif ($backendSummary.status -eq 'PASS') {
                Set-LastStatus 'PASS' @{ summary = 'backend/test-summary.json'; pytest_counts = $backendSummary.pytest_counts }
            }
        } catch { }
    }
} elseif (-not $SkipBackend) {
    $results.Add([pscustomobject]@{ name = 'backend-postgres-pytest'; exit_code = $null; status = 'BLOCKED'; reason = 'python unavailable' })
}

if ($npm -and (Test-Path -LiteralPath (Join-Path $frontend 'package.json'))) {
    $vitestCode = Invoke-Logged 'frontend-vitest' $npm @('run', 'test', '--', '--reporter=default', '--reporter=junit', "--outputFile=$(Join-Path $output 'frontend-junit.xml')") $frontend
    $vitestLog = Get-Content -LiteralPath (Join-Path $output 'frontend-vitest.log') -Raw -ErrorAction SilentlyContinue
    if ($vitestCode -ne 0 -and $vitestLog -match 'EPERM.{0,120}realpath|realpath.{0,120}EPERM') { Set-LastStatus 'BLOCKED' }
    $junitPath = Join-Path $output 'frontend-junit.xml'
    if (Test-Path -LiteralPath $junitPath) {
        try {
            [xml]$junit = Get-Content -LiteralPath $junitPath -Raw
            $suites = if ($junit.testsuites) { @($junit.testsuites.testsuite) } else { @($junit.testsuite) }
            $testCounts = @{ tests = 0; failures = 0; errors = 0; skipped = 0 }
            foreach ($suite in $suites) { foreach ($key in @('tests', 'failures', 'errors', 'skipped')) { $testCounts[$key] += [int]$suite.$key } }
            $vitestExecution = @{ test_files = $suites.Count; executed_tests = $null; collection_blocked = $false }
            if ($vitestLog -match 'Tests\s+no tests') {
                $vitestExecution.executed_tests = 0
                $vitestExecution.collection_blocked = $true
            } elseif ($vitestLog -match 'Tests\s+(\d+)\s+(?:passed|failed)') {
                $vitestExecution.executed_tests = [int]$Matches[1]
            }
            Set-LastStatus $(if ($results[$results.Count - 1].status) { $results[$results.Count - 1].status } else { if ($vitestCode -eq 0) { 'PASS' } else { 'FAIL' } }) @{ junit_report_totals = $testCounts; vitest_execution = $vitestExecution }
        } catch { }
    }
    Invoke-Logged 'typescript' $npm @('run', 'typecheck') $frontend | Out-Null
    $buildOutput = Join-Path $output 'frontend-build'
    $buildCode = Invoke-Logged 'vite-production-build' $npm @('run', 'build', '--', '--outDir', $buildOutput) $frontend
    $buildLog = Get-Content -LiteralPath (Join-Path $output 'vite-production-build.log') -Raw -ErrorAction SilentlyContinue
    if ($buildCode -ne 0 -and $buildLog -match 'EPERM.{0,120}realpath|realpath.{0,120}EPERM') { Set-LastStatus 'BLOCKED' }
} else {
    foreach ($name in @('frontend-vitest', 'typescript', 'vite-production-build')) {
        $results.Add([pscustomobject]@{ name = $name; exit_code = $null; status = 'BLOCKED'; reason = 'npm or frontend package unavailable' })
    }
}

if ($python) {
    $astProbe = @'
import ast, pathlib
root = pathlib.Path.cwd()
roots = ["backend", "desktop", "migrations", "scripts", "tests"]
files = [p for name in roots for p in (root / name).rglob("*.py") if "__pycache__" not in p.parts]
for path in files:
    ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
print(f"Python AST syntax: {len(files)} files PASS")
'@
    Invoke-Logged 'python-syntax' $python @('-c', $astProbe) $root | Out-Null
} else {
    $results.Add([pscustomobject]@{ name = 'python-syntax'; exit_code = $null; status = 'BLOCKED'; reason = 'python unavailable' })
}

$failed = @($results | Where-Object { $null -ne $_.exit_code -and $_.exit_code -ne 0 -and $_.status -ne 'BLOCKED' -and $_.status -ne 'WARN' }).Count
$blocked = @($results | Where-Object { $_.status -eq 'BLOCKED' }).Count
$warnings = @($results | Where-Object { $_.status -eq 'WARN' }).Count
$summary = [pscustomobject]@{
    format = 'naiwa-test-all-v1'
    started_at = $startedAt
    finished_at = (Get-Date).ToUniversalTime().ToString('o')
    output_directory = $output
    status = if ($failed -gt 0) { 'FAIL' } elseif ($blocked -gt 0) { 'BLOCKED' } elseif ($warnings -gt 0) { 'WARN' } else { 'PASS' }
    counts = [pscustomobject]@{ groups = $results.Count; failed = $failed; blocked = $blocked; warnings = $warnings; passed = @($results | Where-Object { $_.exit_code -eq 0 }).Count }
    groups = @($results)
    policy = 'One PostgreSQL initialization attempt at most per invocation; the owned stable data directory and failure logs are retained. Frontend build output is written under this run directory.'
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'test-summary.json') -Encoding utf8
Write-Host ("TEST_ALL={0}; PASS={1}; FAIL={2}; BLOCKED={3}; output={4}" -f $summary.status,
    $summary.counts.passed, $failed, $blocked, $output)
if ($failed -gt 0) { exit 1 }
if ($blocked -gt 0) { exit 2 }
if ($warnings -gt 0) { exit 1 }
exit 0
