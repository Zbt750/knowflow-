param([ValidateSet('start','status','stop','builtin-fault-on','builtin-fault-off')][string]$Action='status')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskAudit=Join-Path $taskRoot 'storage/quality-audits/naiwa-ui-round2-repair-20261025'
$taskConfig=Join-Path $taskAudit 'station-config.json'
$taskData=Join-Path $taskRoot 'storage/manual-experience/naiwa-student-ui-acceptance-20261024-round2fix1'
if($Action -eq 'start') {
    if((Test-Path -LiteralPath $taskConfig) -or (Test-Path -LiteralPath $taskData)){throw 'Existing station/evidence must be preserved. Refusing start/reset.'}
    $taskPorts=@()
    while($taskPorts.Count -lt 3) {
        $taskProbe=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
        try{$taskProbe.Start();$taskPort=$taskProbe.LocalEndpoint.Port}finally{$taskProbe.Stop()}
        if($taskPort -gt 18000 -and $taskPort -notin @(5433,8000,5173) -and $taskPort -notin $taskPorts){$taskPorts+=$taskPort}
    }
    [ordered]@{station='round2fix1';database='naiwa_student_ui_20261024_round2fix1_test';postgres=$taskPorts[0];api=$taskPorts[1];web=$taskPorts[2];created_at=(Get-Date -Format o)} | ConvertTo-Json | Set-Content -LiteralPath $taskConfig -Encoding utf8
}
if(!(Test-Path -LiteralPath $taskConfig)){throw 'No station configuration; run start once.'}
$taskSettings=Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json
if($taskSettings.station -ne 'round2fix1' -or $taskSettings.database -ne 'naiwa_student_ui_20261024_round2fix1_test'){throw 'Station identity mismatch'}
$env:NAIWA_UI_TEST_STATION_ID='round2fix1'
$env:NAIWA_UI_TEST_FIXTURE_PROFILE='answer_handoff_v1'
$env:NAIWA_UI_TEST_PG_PORT=[string]$taskSettings.postgres
$env:NAIWA_UI_TEST_API_PORT=[string]$taskSettings.api
$env:NAIWA_UI_TEST_WEB_PORT=[string]$taskSettings.web
$env:NAIWA_UI_TEST_AUDIT_NAME='naiwa-student-ui-acceptance-20261024-round2fix1'
$env:NAIWA_UI_TEST_STOP_NAME='stop-round2fix1.request'
$env:NAIWA_UI_TEST_FAULTS='1'
$env:PYTHONIOENCODING='utf-8'
$taskPython='C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe'
if($Action -eq 'start') {
    $taskProc=Start-Process -FilePath $taskPython -ArgumentList @('scripts/naiwa_student_ui_acceptance_20261024.py','serve') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskAudit 'station.stdout.log') -RedirectStandardError (Join-Path $taskAudit 'station.stderr.log') -PassThru
    Write-Output "Isolated supervisor PID=$($taskProc.Id); URL=http://127.0.0.1:$($taskSettings.web)/study"
} elseif($Action -eq 'builtin-fault-on' -or $Action -eq 'builtin-fault-off') {
    $taskRuntime=Get-Content -LiteralPath (Join-Path $taskData 'runtime.json') -Raw | ConvertFrom-Json
    if($taskRuntime.database -ne $taskSettings.database -or $taskRuntime.ports.postgres -ne $taskSettings.postgres){throw 'Runtime identity mismatch'}
    $taskMarker=Join-Path $taskData 'fault-builtin-materials-500.flag'
    if($Action -eq 'builtin-fault-on'){Set-Content -LiteralPath $taskMarker -Value 'SYNTHETIC GET fault; expires after one hour' -Encoding utf8}
    elseif(Test-Path -LiteralPath $taskMarker){Remove-Item -LiteralPath $taskMarker}
} else {
    Push-Location $taskRoot
    try{& $taskPython scripts/naiwa_student_ui_acceptance_20261024.py $Action; if($LASTEXITCODE -ne 0){throw 'Station action failed'}}finally{Pop-Location}
}
