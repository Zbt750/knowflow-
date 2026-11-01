$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$audit=Join-Path $projectRoot 'storage\quality-audits\zero-paid-ux-deploy-20261019-v1'
Set-Location -LiteralPath $projectRoot
$expectedExe='C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe'
$listeners=@(Get-NetTCPConnection -LocalPort 8000 -State Listen)
if($listeners.Count -ne 1 -or $listeners[0].OwningProcess -ne 8560){throw 'Unexpected listener; no stop performed'}
$old=Get-CimInstance Win32_Process -Filter 'ProcessId=8560'
$oldManifest=Join-Path $projectRoot 'tmp\dev-backend-manifests\runtime-b27442342f47407e829337a2bad5ebcb.json'
$manifest=Get-Content -LiteralPath $oldManifest -Raw -Encoding UTF8|ConvertFrom-Json
if($old.ExecutablePath -ne $expectedExe -or $old.CommandLine -notlike '*scripts/run_phase4_backend.py*runtime-b27442342f47407e829337a2bad5ebcb.json*' -or $manifest.pid -ne 8560 -or $manifest.workspace -ne $projectRoot){throw 'Project identity mismatch'}
if((Get-Command python).Source -ne $expectedExe){throw 'Original launcher would select a different Python'}
$front=@(Get-NetTCPConnection -LocalPort 5173 -State Listen|Select-Object -ExpandProperty OwningProcess -Unique)
$pg=Get-CimInstance Win32_Process -Filter "Name='postgres.exe'"|Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath
@{backend=$old|Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate;frontend_pids=$front;postgres_processes=$pg;working_directory=$projectRoot;original_launcher='scripts/run-backend.cmd';python=$expectedExe}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $audit 'process-before.json') -Encoding utf8
Copy-Item -LiteralPath $oldManifest -Destination (Join-Path $audit 'old-runtime-manifest.json')
Copy-Item -LiteralPath 'storage\backend-dev.log' -Destination (Join-Path $audit 'backend-before.log')
Get-FileHash -LiteralPath 'scripts\run-backend.cmd','scripts\run_phase4_backend.py'|Select-Object Path,Hash|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $audit 'launcher-hashes.json') -Encoding utf8
# Final read-only activity recheck just before stopping the verified PID.
$env:PYTHONIOENCODING='utf-8'
& python -c "import sys;sys.path.insert(0,'.');from scripts.verify_zero_paid_deployment_20261019 import snapshot;snapshot('shutdown-check')"
# snapshot('shutdown-check') writes only an audit artifact and runs SELECTs.
if($LASTEXITCODE -ne 0){throw 'Activity recheck failed; no restart'}
$check=Get-NetTCPConnection -LocalPort 8000 -State Listen
if($check.OwningProcess -ne 8560){throw 'Listener changed; no stop performed'}
Stop-Process -Id 8560
for($n=0;$n -lt 40;$n++){
 if(-not(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)){break}
 Start-Sleep -Milliseconds 250
}
if(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue){throw 'Port not released; no second instance launched'}
$launch=Start-Process -FilePath $env:ComSpec -ArgumentList '/d /c scripts\run-backend.cmd' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
@{at=(Get-Date).ToString('o');old_pid=8560;launcher_pid=$launch.Id;launcher='scripts/run-backend.cmd';working_directory=$projectRoot;frontend_and_postgres_not_restarted=$true}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $audit 'restart-action.json') -Encoding utf8
Write-Output "Verified backend stopped; original launcher started PID $($launch.Id)."
