param(
  [Parameter(Mandatory = $true)][string]$CaseId
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Out = Join-Path $Root 'storage/quality-audits/final-real-user-20261016/realux-v1'
$PgData = Join-Path $Root 'storage/quality-audits/phase5-closeout-execution-20261015/ai-test/data'
$PgCtl = 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe'
$Python = (Get-Command python.exe).Source
$Node = (Get-Command node.exe).Source
$StartedPostgres = $false
$BackendProcess = $null
$FrontendProcess = $null

if (-not (Test-Path -LiteralPath (Join-Path $Out 'runtime-freeze.json'))) {
  throw 'runtime_not_frozen'
}
if (-not (Test-Path -LiteralPath $PgCtl) -or -not (Test-Path -LiteralPath $PgData)) {
  throw 'owned_postgres_runtime_missing'
}
if ($CaseId -notin @('SMOKE','PREFLIGHT') -and (Test-Path -LiteralPath (Join-Path $Out $CaseId))) {
  throw 'case_already_started_never_replay'
}
if ($CaseId -notin @('SMOKE','PREFLIGHT')) {
  $ledgerPath = Join-Path $Out 'provider-ledger.json'
  if (-not (Test-Path -LiteralPath $ledgerPath)) { throw 'provider_meter_not_initialized' }
  $ledger = Get-Content -LiteralPath $ledgerPath -Raw | ConvertFrom-Json
  if ($ledger.stop_reason -or $ledger.requests.Count -ge 20) { throw 'provider_budget_stopped' }
}

try {
  & $PgCtl status -D $PgData *> $null
  if ($LASTEXITCODE -ne 0) {
    & $PgCtl start -D $PgData -o '-p 59271' -w
    if ($LASTEXITCODE -ne 0) { throw 'owned_postgres_start_failed' }
    $StartedPostgres = $true
  }
  & $Python -m scripts.final_user_realux_server --check-cluster
  if ($LASTEXITCODE -ne 0) { throw 'owned_postgres_identity_check_failed' }

  if ($CaseId -eq 'PREFLIGHT') {
    & $Python -m scripts.final_user_realux_server --preflight
    if ($LASTEXITCODE -ne 0) { throw 'isolated_database_preflight_failed' }
    return
  }

  $BackendLog = Join-Path $Out 'backend-case.log'
  $FrontendLog = Join-Path $Out 'frontend-case.log'
  $BackendErr = Join-Path $Out 'backend-case.err.log'
  $FrontendErr = Join-Path $Out 'frontend-case.err.log'
  $BackendProcess = Start-Process -FilePath $Python -ArgumentList @('-m','uvicorn','scripts.final_user_realux_server:app','--factory','--host','127.0.0.1','--port','8000','--log-level','info') -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErr
  $FrontendProcess = Start-Process -FilePath $Node -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5184') -WorkingDirectory (Join-Path $Root 'frontend') -PassThru -WindowStyle Hidden -RedirectStandardOutput $FrontendLog -RedirectStandardError $FrontendErr

  $Health = $null
  for ($i = 0; $i -lt 90; $i++) {
    if ($BackendProcess.HasExited -or $FrontendProcess.HasExited) { throw 'local_server_exited_during_startup' }
    try {
      $Health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3
      $Front = Invoke-WebRequest -Uri 'http://127.0.0.1:5184/' -TimeoutSec 3
      if ($Front.StatusCode -eq 200) { break }
    } catch { Start-Sleep -Milliseconds 1000 }
  }
  if (-not $Health -or $Health.environment -ne 'test' -or $Health.llm_model -ne 'deepseek-flash') { throw 'local_health_identity_check_failed' }
  if ($CaseId -eq 'SMOKE') {
    & $Node (Join-Path $Root 'scripts/final_user_realux_smoke.cjs')
  } else {
    & $Node (Join-Path $Root 'scripts/final_user_realux_browser.cjs') $CaseId
  }
  if ($LASTEXITCODE -ne 0) { throw "browser_case_failed:$CaseId" }
} finally {
  if ($FrontendProcess -and -not $FrontendProcess.HasExited) { Stop-Process -Id $FrontendProcess.Id -Force }
  if ($BackendProcess -and -not $BackendProcess.HasExited) { Stop-Process -Id $BackendProcess.Id -Force }
  if ($StartedPostgres) { & $PgCtl stop -D $PgData -m fast -w; if ($LASTEXITCODE -ne 0) { Write-Warning 'owned_postgres_stop_failed' } }
}
