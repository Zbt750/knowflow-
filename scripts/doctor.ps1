[CmdletBinding()]
param([switch]$SkipFrontendSmoke)

$ErrorActionPreference = 'Continue'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$results = [System.Collections.Generic.List[object]]::new()
$runDirectory = Join-Path $root ('storage/quality-audits/doctor-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($runDirectory) | Out-Null

function Add-Check([string]$Name, [string]$Status, [string]$Detail) {
    $results.Add([pscustomobject]@{ name = $Name; status = $Status; detail = $Detail })
    $color = if ($Status -eq 'PASS') { 'Green' } elseif ($Status -eq 'WARN') { 'Yellow' } else { 'Red' }
    Write-Host ("[{0}] {1}: {2}" -f $Status, $Name, $Detail) -ForegroundColor $color
}

Push-Location $root
try {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $version = & python --version 2>&1
        Add-Check 'Python' 'PASS' ([string]$version)
        & python -c 'import pytest, sqlalchemy, psycopg; print("pytest/sqlalchemy/psycopg imports: PASS")' *> $null
        Add-Check 'Python test dependencies' $(if ($LASTEXITCODE -eq 0) { 'PASS' } else { 'BLOCKED' }) 'pytest, SQLAlchemy, psycopg import probe'
    } else { Add-Check 'Python' 'BLOCKED' 'python command is unavailable' }

    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($node) {
        Add-Check 'Node' 'PASS' ((& node --version 2>&1 | Out-String).Trim())
    } else { Add-Check 'Node' 'BLOCKED' 'node command is unavailable' }
    if ($npm) {
        Add-Check 'npm' 'PASS' ((& npm.cmd --version 2>&1 | Out-String).Trim())
    } else { Add-Check 'npm' 'BLOCKED' 'npm.cmd is unavailable' }

    $frontend = Join-Path $root 'frontend'
    $targets = @('C:\Windows', $root, (Join-Path $frontend 'src/main.ts'),
        (Join-Path $frontend 'node_modules'), $env:TEMP)
    $env:NAIWA_DOCTOR_PATHS = ConvertTo-Json -InputObject $targets -Compress
    $nodeProbe = @'
const fs = require("node:fs");
const { promisify } = require("node:util");
const targets = JSON.parse(process.env.NAIWA_DOCTOR_PATHS);
const callbackRealpath = promisify(fs.realpath);
(async () => {
  const out = [];
  for (const path of targets) {
    const item = { path, native: null, sync: null, promises: null, callback: null };
    for (const [name, run] of [
      ["native", () => fs.realpathSync.native(path)],
      ["sync", () => fs.realpathSync(path)],
      ["promises", () => fs.promises.realpath(path)],
      ["callback", () => callbackRealpath(path)],
    ]) {
      try { await run(); item[name] = "PASS"; }
      catch (error) { item[name] = error.code || error.name || "ERROR"; }
    }
    out.push(item);
  }
  process.stdout.write(JSON.stringify(out));
})().catch(() => process.exit(2));
'@
    try {
        $probeJson = & node -e $nodeProbe 2>$null | Out-String
        if ($LASTEXITCODE -eq 0) {
            $probe = $probeJson | ConvertFrom-Json
            $nativeErrors = @($probe | Where-Object { $_.native -ne 'PASS' })
            $syncCallbackErrors = @($probe | Where-Object { $_.sync -ne 'PASS' -or $_.callback -ne 'PASS' })
            $promiseErrors = @($probe | Where-Object { $_.promises -ne 'PASS' })
            $probe | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDirectory 'node-realpath.json') -Encoding utf8
            if ($syncCallbackErrors.Count -eq 0 -and $nativeErrors.Count -eq 0 -and $promiseErrors.Count -eq 0) {
                Add-Check 'Node realpath APIs' 'PASS' 'native and JavaScript realpath APIs resolved all diagnostic targets'
            } elseif ($syncCallbackErrors.Count -eq 0 -and $nativeErrors.Count -gt 0) {
                $nativeCodes = (($nativeErrors | ForEach-Object { $_.native } | Sort-Object -Unique) -join ',')
                $promiseCodes = (($promiseErrors | ForEach-Object { $_.promises } | Sort-Object -Unique) -join ',')
                Add-Check 'Node native realpath' 'BLOCKED' "native=$nativeCodes; promises=$promiseCodes; fs.realpathSync and callback realpath passed; details $runDirectory\node-realpath.json"
            } else {
                Add-Check 'Node realpath APIs' 'BLOCKED' "native/fallback path APIs failed; details $runDirectory\node-realpath.json"
            }
        } else { Add-Check 'Node realpath APIs' 'BLOCKED' 'Node probe process failed' }
    } catch { Add-Check 'Node realpath APIs' 'BLOCKED' 'Node diagnostic probe could not run' }
    Remove-Item Env:\NAIWA_DOCTOR_PATHS -ErrorAction SilentlyContinue

    if (Test-Path -LiteralPath (Join-Path $frontend 'node_modules\.bin\vitest.cmd')) {
        Add-Check 'Frontend dependencies' 'PASS' 'frontend node_modules and Vitest launcher exist'
    } else { Add-Check 'Frontend dependencies' 'BLOCKED' 'frontend dependencies or Vitest launcher are missing' }

    $modelCache = if ($env:MODEL_CACHE_DIR) { $env:MODEL_CACHE_DIR } else { Join-Path $root 'storage/models' }
    $modelRepo = Join-Path $modelCache 'models--BAAI--bge-small-zh-v1.5'
    $refFile = Join-Path $modelRepo 'refs/main'
    $snapshotHash = if (Test-Path -LiteralPath $refFile) { (Get-Content -LiteralPath $refFile -Raw).Trim() } else { '' }
    $snapshot = Join-Path $modelRepo ('snapshots/' + $snapshotHash)
    $requiredModelFiles = @('config.json', 'modules.json', 'tokenizer.json', 'vocab.txt', 'model.safetensors')
    $missingModelFiles = @($requiredModelFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $snapshot $_)) })
    if ($snapshotHash -match '^[a-f0-9]{40}$' -and $missingModelFiles.Count -eq 0) {
        Add-Check 'Offline embedding model cache' 'PASS' 'snapshot reference and model/tokenizer files exist; no model download was attempted'
    } else { Add-Check 'Offline embedding model cache' 'WARN' 'expected BAAI/bge-small-zh-v1.5 snapshot is incomplete; no model download was attempted' }

    $pgBin = if ($env:POSTGRES18_BIN) { $env:POSTGRES18_BIN } else { 'C:\Program Files\PostgreSQL\18\bin' }
    if ((Test-Path -LiteralPath (Join-Path $pgBin 'postgres.exe')) -and (Test-Path -LiteralPath (Join-Path $pgBin 'initdb.exe'))) {
        $pgVersion = & (Join-Path $pgBin 'postgres.exe') --version 2>&1
        if ($pgVersion -match '18\.') { Add-Check 'PostgreSQL 18 binaries' 'PASS' ([string]$pgVersion) }
        else { Add-Check 'PostgreSQL 18 binaries' 'BLOCKED' 'binary version does not match the managed test runner requirement' }
    } else { Add-Check 'PostgreSQL 18 binaries' 'BLOCKED' 'expected postgres.exe/initdb.exe are missing' }

    $stableRoot = Join-Path $root 'tmp\managed-test-clusters\naiwa-stable-test-pg\KaoyanStudy'
    $manifest = Join-Path $stableRoot 'config\postgres-test-runner.json'
    if (Test-Path -LiteralPath $manifest) {
        Add-Check 'Owned test cluster manifest' 'PASS' 'persistent test-cluster identity record exists; credentials are not read or printed'
    } elseif (Test-Path -LiteralPath (Join-Path $stableRoot 'postgres\cluster\PG_VERSION')) {
        Add-Check 'Owned test cluster manifest' 'BLOCKED' 'cluster data exists without the runner identity record; will not adopt it'
    } else { Add-Check 'Owned test cluster manifest' 'WARN' 'stable test cluster has not been initialized yet' }

    $pidFile = Join-Path $stableRoot 'postgres\cluster\postmaster.pid'
    if (Test-Path -LiteralPath $pidFile) {
        Add-Check 'Owned test PostgreSQL process' 'BLOCKED' 'postmaster.pid exists; process ownership is not inferred and no process was stopped'
    } else { Add-Check 'Owned test PostgreSQL process' 'PASS' 'no postmaster.pid at the dedicated cluster path' }

    if ($env:TEST_DATABASE_URL) {
        Add-Check 'TEST_DATABASE_URL' 'WARN' 'present; value intentionally withheld, no database connection attempted'
    } else { Add-Check 'TEST_DATABASE_URL' 'WARN' 'not set in this shell; the isolated runner supplies it only after identity checks' }
    if ($env:KAOYAN_OWNED_TEST_PORT -or $env:PHASE45E_OWNED_TEST_PORT) {
        Add-Check 'Owned test port marker' 'WARN' 'present; value withheld, this doctor did not connect to a database'
    } else { Add-Check 'Owned test port marker' 'WARN' 'not set; the isolated test runner assigns and verifies its own port' }

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { Add-Check 'Docker Linux Engine' 'WARN' 'Docker CLI unavailable; Windows PostgreSQL runner remains the configured path' }
    else {
        $null = & docker info --format '{{.ServerVersion}}' 2>$null
        if ($LASTEXITCODE -eq 0) { Add-Check 'Docker Linux Engine' 'PASS' 'read-only Docker server info query succeeded' }
        else { Add-Check 'Docker Linux Engine' 'WARN' 'Docker server API unavailable; no containers were created or changed' }
    }

    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($wsl) {
        $null = & wsl.exe --status 2>$null
        if ($LASTEXITCODE -eq 0) { Add-Check 'WSL' 'PASS' 'read-only WSL status query succeeded' }
        else { Add-Check 'WSL' 'WARN' 'WSL query denied or unavailable; no permission changes attempted' }
    } else { Add-Check 'WSL' 'WARN' 'wsl.exe unavailable' }

    if (-not $SkipFrontendSmoke -and $npm -and (Test-Path -LiteralPath (Join-Path $frontend 'node_modules\.bin\vitest.cmd'))) {
        Push-Location $frontend
        try {
            & npm.cmd run test -- 'src/components/PersonalTrainingStudyMode.state.test.ts' '--reporter=default' *> (Join-Path $runDirectory 'vitest-smoke.log')
            $code = $LASTEXITCODE
        } finally { Pop-Location }
        if ($code -eq 0) { Add-Check 'Vitest execution smoke' 'PASS' "targeted test exited 0; log $runDirectory\vitest-smoke.log" }
        else { Add-Check 'Vitest execution smoke' 'BLOCKED' "targeted test exited $code; log $runDirectory\vitest-smoke.log" }
    } elseif (-not $SkipFrontendSmoke) {
        Add-Check 'Vitest execution smoke' 'BLOCKED' 'cannot run the existing targeted test without npm and frontend dependencies'
    }
} finally { Pop-Location }

$blocked = @($results | Where-Object status -eq 'BLOCKED').Count
$warnings = @($results | Where-Object status -eq 'WARN').Count
$overall = if ($blocked -gt 0) { 'BLOCKED' } elseif ($warnings -gt 0) { 'WARN' } else { 'PASS' }
Write-Host ("DOCTOR={0}; PASS={1}; WARN={2}; BLOCKED={3}" -f $overall,
    @($results | Where-Object status -eq 'PASS').Count, $warnings, $blocked)
Write-Host "DOCTOR_EVIDENCE=$runDirectory"
if ($blocked -gt 0) { exit 2 }
if ($warnings -gt 0) { exit 1 }
exit 0
