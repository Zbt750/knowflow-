[CmdletBinding()]
param()

# Run this script from an ordinary, non-elevated Windows PowerShell session.
# It deliberately keeps every run's logs and sends Vite output to a new audit
# directory so an existing frontend/dist directory is not overwritten.
$ErrorActionPreference = 'Continue'
# Keep native non-zero exit codes available to Invoke-LoggedCommand even when
# a PowerShell 7 profile enables native-command error promotion.
$PSNativeCommandUseErrorActionPreference = $false
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$frontendRoot = Join-Path $repoRoot 'frontend'
$auditBase = Join-Path $repoRoot 'storage/quality-audits'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$auditDir = Join-Path $auditBase ("naiwa-frontend-ordinary-{0}-r1" -f $stamp)
if (Test-Path -LiteralPath $auditDir) {
    $auditDir = Join-Path $auditBase ("naiwa-frontend-ordinary-{0}-{1}-r1" -f $stamp, [guid]::NewGuid().ToString('N').Substring(0, 8))
}
[IO.Directory]::CreateDirectory($auditDir) | Out-Null

$script:results = New-Object 'System.Collections.Generic.List[object]'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, $script:utf8NoBom)
}

function Get-TestCounts([string]$Text) {
    $files = $null
    $tests = $null
    $failed = $null
    $skipped = $null
    $todo = $null
    # Vitest emits ANSI color sequences even when redirected. They can appear
    # between words (for example, between "Tests" and the count), so remove
    # them before parsing rather than trying to account for every color span.
    $ansiPattern = [string]::Format('{0}\[[0-?]*[ -/]*[@-~]', [char]27)
    $plainText = [regex]::Replace([string]$Text, $ansiPattern, '')
    $fileLine = [regex]::Match($plainText, '(?m)^\s*Test Files\s+([^\r\n]+)')
    if ($fileLine.Success) {
        $fileTotal = [regex]::Match($fileLine.Groups[1].Value, '\((\d+)\)')
        if ($fileTotal.Success) { $files = [int]$fileTotal.Groups[1].Value }
        else {
            $fileParts = [regex]::Matches($fileLine.Groups[1].Value, '(\d+)\s+(?:passed|failed|skipped|error)')
            if ($fileParts.Count -gt 0) { $files = 0; foreach ($part in $fileParts) { $files += [int]$part.Groups[1].Value } }
        }
    }
    $testLine = [regex]::Match($plainText, '(?m)^\s*Tests\s+([^\r\n]+)')
    if ($testLine.Success -and $testLine.Groups[1].Value -match '^no tests') { $tests = 0 }
    elseif ($testLine.Success) {
        foreach ($part in [regex]::Matches($testLine.Groups[1].Value, '(\d+)\s+(passed|failed|skipped|todo)')) {
            $count = [int]$part.Groups[1].Value
            switch ($part.Groups[2].Value) {
                'passed' { if ($null -eq $tests) { $tests = 0 }; $tests += $count }
                'failed' { if ($null -eq $failed) { $failed = 0 }; $failed += $count }
                'skipped' { if ($null -eq $skipped) { $skipped = 0 }; $skipped += $count }
                'todo' { if ($null -eq $todo) { $todo = 0 }; $todo += $count }
            }
        }
    }
    return [pscustomobject]@{ test_files = $files; passed = $tests; failed = $failed; skipped = $skipped; todo = $todo }
}

function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory=$true)][string]$WorkingDirectory,
        [switch]$RequireVitestTests
    )
    $start = (Get-Date).ToUniversalTime()
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $stdoutPath = Join-Path $auditDir ($Name + '.stdout.log')
    $stderrPath = Join-Path $auditDir ($Name + '.stderr.log')
    $exitCode = 1
    $launchError = $null
    $oldLocation = Get-Location
    try {
        Set-Location -LiteralPath $WorkingDirectory
        & $FilePath @Arguments 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
    } catch {
        $launchError = $_.Exception.Message
        Add-Content -LiteralPath $stderrPath -Value $launchError -Encoding UTF8
        $exitCode = 1
    } finally {
        Set-Location -LiteralPath $oldLocation.Path
        $watch.Stop()
    }
    $stdout = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -LiteralPath $stdoutPath -Raw } else { '' }
    $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { '' }
    $combined = $stdout + "`n" + $stderr
    $counts = if ($RequireVitestTests) { Get-TestCounts $combined } else { $null }
    $status = if ($exitCode -eq 0) { 'PASS' } elseif ($combined -match '(?is)EPERM.{0,160}realpath|realpath.{0,160}EPERM') { 'BLOCKED_ENVIRONMENT' } else { 'FAIL' }
    if ($RequireVitestTests -and $exitCode -eq 0 -and ($null -eq $counts.passed -or $counts.passed -eq 0)) {
        $status = 'FAIL_NO_TESTS_CONFIRMED'
    }
    $entry = [pscustomobject]@{
        name = $Name
        command = [pscustomobject]@{ executable = $FilePath; arguments = @($Arguments); working_directory = $WorkingDirectory }
        started_at_utc = $start.ToString('o')
        finished_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        elapsed_seconds = [Math]::Round($watch.Elapsed.TotalSeconds, 3)
        # Keep the actual process exit code distinct from the verification
        # gate. A successful command with no collected tests is a verification
        # failure, but its process exit code remains the truthful native code.
        exit_code = [int]$exitCode
        verification_exit_code = [int]$(if ($status -eq 'PASS') { 0 } else { 1 })
        status = $status
        stdout = [IO.Path]::GetFileName($stdoutPath)
        stderr = [IO.Path]::GetFileName($stderrPath)
        vitest_counts = $counts
        launch_error = $launchError
    }
    $script:results.Add($entry)
    Write-Host ('[{0}] {1} exit={2} ({3:n1}s)' -f $status, $Name, $exitCode, $entry.elapsed_seconds)
}

function Add-InternalCheck {
    param([string]$Name, [bool]$Passed, [string]$Detail, [ValidateSet('FAIL','BLOCKED')][string]$FailureStatus = 'FAIL')
    $outFile = Join-Path $auditDir ($Name + '.stdout.log')
    $errFile = Join-Path $auditDir ($Name + '.stderr.log')
    Write-Utf8NoBom $outFile ($Detail + "`r`n")
    Write-Utf8NoBom $errFile ''
    $code = if ($Passed) { 0 } else { 1 }
    $script:results.Add([pscustomobject]@{
        name = $Name; command = [pscustomobject]@{ executable = 'internal-check'; arguments = @(); working_directory = (Get-Location).Path }
        started_at_utc = (Get-Date).ToUniversalTime().ToString('o'); finished_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        elapsed_seconds = 0; exit_code = $code; verification_exit_code = $code; status = $(if ($Passed) { 'PASS' } elseif ($FailureStatus -eq 'BLOCKED') { 'BLOCKED' } else { 'FAIL' })
        stdout = [IO.Path]::GetFileName($outFile); stderr = [IO.Path]::GetFileName($errFile); vitest_counts = $null; launch_error = $null
    })
    Write-Host ('[{0}] {1}' -f $(if ($Passed) { 'PASS' } else { 'FAIL' }), $Name)
}

$launchedFrom = [IO.Path]::GetFullPath((Get-Location).ProviderPath).TrimEnd('\')
$rootMatches = [StringComparer]::OrdinalIgnoreCase.Equals($launchedFrom, $repoRoot)
$markersPresent = (Test-Path -LiteralPath (Join-Path $repoRoot '.git')) -and
                  (Test-Path -LiteralPath (Join-Path $repoRoot 'backend')) -and
                  (Test-Path -LiteralPath (Join-Path $repoRoot 'frontend/package.json'))
Add-InternalCheck 'formal-project-directory' ($rootMatches -and $markersPresent) (
    "launched_from=$launchedFrom`nformal_root=$repoRoot`nroot_matches=$rootMatches`nproject_markers_present=$markersPresent")

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($nodeCommand) {
    Invoke-LoggedCommand 'node-version' $nodeCommand.Source @('--version') $repoRoot
} else {
    Add-InternalCheck 'node-version' $false 'node.exe was not found on PATH; independent checks will still be recorded as blocked.' 'BLOCKED'
}
if ($npmCommand) {
    Invoke-LoggedCommand 'npm-version' $npmCommand.Source @('--version') $repoRoot
} else {
    Add-InternalCheck 'npm-version' $false 'npm.cmd was not found on PATH; independent checks will still be recorded as blocked.' 'BLOCKED'
}

if ($nodeCommand) {
    $probePath = Join-Path $auditDir 'realpath-probe.cjs'
    $probe = @'
const fs = require("node:fs");
const path = require("node:path");
const root = process.env.NAIWA_VERIFY_ROOT;
const targets = [root, path.join(root, "frontend", "src", "main.ts"), path.join(root, "frontend", "node_modules")];
(async () => {
  const results = [];
  let failed = false;
  for (const target of targets) {
    const item = { target, native: null, promises: null };
    try { item.native = await fs.realpathSync.native(target); } catch (error) { item.native = { code: error.code || null, message: error.message }; failed = true; }
    try { item.promises = await fs.promises.realpath(target); } catch (error) { item.promises = { code: error.code || null, message: error.message }; failed = true; }
    results.push(item);
  }
  process.stdout.write(JSON.stringify({ execPath: process.execPath, version: process.version, cwd: process.cwd(), results }, null, 2) + "\n");
  if (failed) process.exitCode = 1;
})().catch(error => { process.stderr.write(String(error && error.stack || error) + "\n"); process.exitCode = 2; });
'@
    Write-Utf8NoBom $probePath $probe
    $env:NAIWA_VERIFY_ROOT = $repoRoot
    Invoke-LoggedCommand 'native-and-promise-realpath' $nodeCommand.Source @($probePath) $repoRoot
    Remove-Item Env:\NAIWA_VERIFY_ROOT -ErrorAction SilentlyContinue
} else {
    Add-InternalCheck 'native-and-promise-realpath' $false 'Skipped because node.exe is unavailable; no test command was skipped.' 'BLOCKED'
}

if ($npmCommand) {
    Invoke-LoggedCommand 'known-study-state-regressions' $npmCommand.Source @('run','test','--','--reporter=verbose','src/components/PersonalTrainingStudyMode.state.test.ts','src/pages/StudyPage.answer-state.test.ts') $frontendRoot -RequireVitestTests
    Invoke-LoggedCommand 'full-vitest' $npmCommand.Source @('run','test','--','--reporter=verbose') $frontendRoot -RequireVitestTests
    Invoke-LoggedCommand 'typescript-typecheck' $npmCommand.Source @('run','typecheck') $frontendRoot
    $buildOutput = Join-Path $auditDir 'vite-production-dist'
    Invoke-LoggedCommand 'vite-production-build' $npmCommand.Source @('run','build','--','--outDir',$buildOutput) $frontendRoot
} else {
    foreach ($name in @('known-study-state-regressions','full-vitest','typescript-typecheck','vite-production-build')) {
        Add-InternalCheck $name $false 'npm.cmd unavailable; stage not executed.' 'BLOCKED'
    }
}

$steps = @()
$failedCount = 0
$blockedCount = 0
foreach ($result in $script:results) {
    $steps += $result
    if ([string]$result.status -like 'BLOCKED*') { $blockedCount++ }
    elseif ([string]$result.status -like 'FAIL*' -or [int]$result.exit_code -ne 0) { $failedCount++ }
}
$overallStatus = if ($failedCount -gt 0) { 'FAIL' } elseif ($blockedCount -gt 0) { 'BLOCKED' } else { 'PASS' }
$summary = [pscustomobject]@{
    format = 'naiwa-ordinary-powershell-frontend-verification-v1'
    audit_directory = $auditDir
    repository_root = $repoRoot
    launched_from = $launchedFrom
    started_at_utc = $script:results[0].started_at_utc
    finished_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    status = $overallStatus
    counts = [pscustomobject]@{ steps = $steps.Count; failed = $failedCount; blocked = $blockedCount; passed = $steps.Count - $failedCount - $blockedCount }
    steps = $steps
    note = 'A command exit code of zero is recorded as such; Vitest is not considered successful when no tests were collected. Every command retains separate stdout/stderr logs. Build output is isolated under this audit directory.'
}
try {
    $summaryJson = ConvertTo-Json -InputObject $summary -Depth 8
    Write-Utf8NoBom (Join-Path $auditDir 'results.json') $summaryJson
} catch {
    $summaryError = $_.Exception.ToString()
    Write-Utf8NoBom (Join-Path $auditDir 'summary-error.log') $summaryError
    $summary.status = 'FAIL'
    $overallStatus = 'FAIL'
    $fallbackSteps = @()
    foreach ($result in $steps) {
        $fallbackSteps += [pscustomobject]@{
            name = [string]$result.name
            exit_code = [int]$result.exit_code
            status = [string]$result.status
            stdout = [string]$result.stdout
            stderr = [string]$result.stderr
        }
    }
    $fallback = [pscustomobject]@{
        format = 'naiwa-ordinary-powershell-frontend-verification-v1'
        audit_directory = $auditDir
        status = 'FAIL'
        counts = [pscustomobject]@{ steps = $fallbackSteps.Count; failed = $failedCount; blocked = $blockedCount }
        steps = $fallbackSteps
        summary_error = [string]$_.Exception.Message
    }
    Write-Utf8NoBom (Join-Path $auditDir 'results.json') (ConvertTo-Json -InputObject $fallback -Depth 6)
}
Write-Host ("FRONTEND_VERIFY={0}; audit={1}" -f $overallStatus, $auditDir)
        if ($summary.status -ne 'PASS') { exit 1 }
exit 0
