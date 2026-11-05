param([ValidateSet('start','status','stop')][string]$Action='status')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskData=Join-Path $taskRoot 'storage/manual-experience/naiwa-student-ui-acceptance-20261024-handoffc1'
$env:NAIWA_UI_TEST_STATION_ID='handoffc1'
$env:NAIWA_UI_TEST_FIXTURE_PROFILE='answer_handoff_v1'
$env:NAIWA_UI_TEST_PG_PORT='64765'
$env:NAIWA_UI_TEST_API_PORT='63121'
$env:NAIWA_UI_TEST_WEB_PORT='63122'
$env:NAIWA_UI_TEST_AUDIT_NAME='naiwa-student-ui-acceptance-20261024-handoffc1'
$env:NAIWA_UI_TEST_STOP_NAME='stop-handoffc1.request'
$env:PYTHONIOENCODING='utf-8'
$taskPython='C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe'
if($Action -eq 'start') {
    if(Test-Path -LiteralPath $taskData){throw 'Dedicated station already exists; preserve it. Do not reset or re-seed.'}
    foreach($taskPort in 64765,63121,63122){
        $taskListener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$taskPort)
        try{$taskListener.Start()}finally{$taskListener.Stop()}
    }
    $taskOut=Join-Path $taskRoot 'storage/quality-audits/naiwa-answer-handoff-20261024-launch.stdout.log'
    $taskErr=Join-Path $taskRoot 'storage/quality-audits/naiwa-answer-handoff-20261024-launch.stderr.log'
    if((Test-Path $taskOut) -or (Test-Path $taskErr)){throw 'Launch logs already exist; refusing overwrite.'}
    $taskProcess=Start-Process -FilePath $taskPython -ArgumentList @('scripts/naiwa_student_ui_acceptance_20261024.py','serve') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput $taskOut -RedirectStandardError $taskErr -PassThru
    Write-Output "Isolated supervisor requested: PID=$($taskProcess.Id); URL=http://127.0.0.1:63122/study"
} elseif($Action -eq 'stop') {
    $taskRuntime=Get-Content -Raw (Join-Path $taskData 'runtime.json') | ConvertFrom-Json
    if($taskRuntime.database -ne 'naiwa_student_ui_20261024_handoffc1_test' -or $taskRuntime.ports.postgres -ne 64765){throw 'Station identity mismatch; refusing stop.'}
    Push-Location $taskRoot
    try { & $taskPython scripts/naiwa_student_ui_acceptance_20261024.py stop; if($LASTEXITCODE -ne 0){throw 'Stop request failed'} } finally {Pop-Location}
} else {
    Get-Content -Raw (Join-Path $taskData 'runtime.json')
}
