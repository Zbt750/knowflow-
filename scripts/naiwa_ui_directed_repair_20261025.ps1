param([ValidateSet('start','status','stop','sessions-fault-on','sessions-fault-off','messages-fault-on','messages-fault-off','fault-clear')][string]$Action='status',[string]$SessionId='')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskAudit=Join-Path $taskRoot 'storage/quality-audits/naiwa-ui-directed-repair-20261025'
$taskConfig=Join-Path $taskAudit 'station-config.json'
$taskData=Join-Path $taskRoot 'storage/manual-experience/naiwa-student-ui-acceptance-20261024-uihandoff2'
$taskStationAudit=Join-Path $taskRoot 'storage/quality-audits/naiwa-student-ui-acceptance-20261024-uihandoff2'
$taskPython='C:\Users\ZBT\AppData\Local\Programs\Python\Python312\python.exe'

if($Action -eq 'start') {
    if((Test-Path -LiteralPath $taskConfig) -or (Test-Path -LiteralPath $taskData) -or (Test-Path -LiteralPath $taskStationAudit)) {
        throw 'This fresh epoch already has data or evidence; preserve it and choose another station ID.'
    }
    if(!(Test-Path -LiteralPath $taskPython)){throw 'Configured Python runtime is unavailable.'}
    $taskPorts=@()
    while($taskPorts.Count -lt 3) {
        $taskProbe=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
        try{$taskProbe.Start();$taskPort=$taskProbe.LocalEndpoint.Port}finally{$taskProbe.Stop()}
        if($taskPort -gt 18000 -and $taskPort -notin @(5433,8000,5173) -and $taskPort -notin $taskPorts){$taskPorts+=$taskPort}
    }
    $config=[ordered]@{station='uihandoff2';database='naiwa_student_ui_20261024_uihandoff2_test';postgres=$taskPorts[0];api=$taskPorts[1];web=$taskPorts[2];created_at=(Get-Date -Format o)}
    [IO.File]::WriteAllText($taskConfig,($config|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false))
}

if(!(Test-Path -LiteralPath $taskConfig)){throw 'No fresh station configuration; run start once.'}
$settings=Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json
if($settings.station -ne 'uihandoff2' -or $settings.database -ne 'naiwa_student_ui_20261024_uihandoff2_test') {throw 'Station identity mismatch.'}

if($Action -eq 'start') {
    if((Test-Path -LiteralPath (Join-Path $taskAudit 'station-supervisor.stdout.log')) -or (Test-Path -LiteralPath (Join-Path $taskAudit 'station-supervisor.stderr.log'))){throw 'Supervisor log already exists; refusing to overwrite.'}
    $env:NAIWA_UI_TEST_STATION_ID='uihandoff2'
    $env:NAIWA_UI_TEST_FIXTURE_PROFILE='answer_handoff_v1'
    $env:NAIWA_UI_TEST_PG_PORT=[string]$settings.postgres
    $env:NAIWA_UI_TEST_API_PORT=[string]$settings.api
    $env:NAIWA_UI_TEST_WEB_PORT=[string]$settings.web
    $env:NAIWA_UI_TEST_AUDIT_NAME='naiwa-student-ui-acceptance-20261024-uihandoff2'
    $env:NAIWA_UI_TEST_STOP_NAME='stop-uihandoff2.request'
    $env:NAIWA_UI_TEST_FAULTS='1'
    $env:PYTHONIOENCODING='utf-8'
    $stdout=Join-Path $taskAudit 'station-supervisor.stdout.log'
    $stderr=Join-Path $taskAudit 'station-supervisor.stderr.log'
    $proc=Start-Process -FilePath $taskPython -ArgumentList @('scripts/naiwa_student_ui_acceptance_20261024.py','serve') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Write-Output "Isolated supervisor PID=$($proc.Id); station=uihandoff2; database=$($settings.database); URL=http://127.0.0.1:$($settings.web)/study"
    exit 0
}

if(!(Test-Path -LiteralPath (Join-Path $taskData 'runtime.json'))){throw 'Fresh station runtime is not present.'}
$runtime=Get-Content -LiteralPath (Join-Path $taskData 'runtime.json') -Raw | ConvertFrom-Json
if($runtime.database -ne $settings.database -or $runtime.ports.postgres -ne $settings.postgres -or $runtime.paid_enabled -ne $false -or $runtime.provider_mode -ne 'FIXED-OFFLINE-NO-PAID-MODEL') {throw 'Runtime database/provider identity mismatch.'}

if($Action -eq 'status') {
    Push-Location $taskRoot; try{& $taskPython scripts/naiwa_student_ui_acceptance_20261024.py status}finally{Pop-Location}
    exit 0
}
if($Action -eq 'stop') {
    $stop=Join-Path $taskData 'stop-uihandoff2.request'; if(!(Test-Path -LiteralPath $stop)){[IO.File]::WriteAllText($stop,'stop requested',[Text.UTF8Encoding]::new($false))}
    Write-Output 'Stop requested for ui handoff epoch; synthetic database files are retained.'; exit 0
}

$markers=@{
    'sessions-fault-on'=@{name='fault-chat-sessions-500.json';payload=@{station_id='uihandoff2';route='sessions';expires_at=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+900)}}
    'messages-fault-on'=@{name='fault-chat-messages-500.json';payload=$null}
}
if($Action -eq 'fault-clear') {
    foreach($name in @('fault-chat-sessions-500.json','fault-chat-messages-500.json','fault-builtin-materials-500.flag')){$path=Join-Path $taskData $name;if(Test-Path -LiteralPath $path){Remove-Item -LiteralPath $path}}
    Write-Output 'Cleared runner-owned GET fault markers.'; exit 0
}
if($Action -eq 'sessions-fault-off' -or $Action -eq 'messages-fault-off') {
    $name=if($Action -eq 'sessions-fault-off'){'fault-chat-sessions-500.json'}else{'fault-chat-messages-500.json'}
    $path=Join-Path $taskData $name;if(Test-Path -LiteralPath $path){Remove-Item -LiteralPath $path};Write-Output "Cleared $name";exit 0
}
if($Action -eq 'sessions-fault-on') {
    $entry=$markers[$Action];$path=Join-Path $taskData $entry.name
    [IO.File]::WriteAllText($path,($entry.payload|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false));Write-Output 'Enabled a 15-minute, sessions-list GET-only fault for this isolated station.';exit 0
}
if($Action -eq 'messages-fault-on') {
    $parsed=[guid]::Empty;if(![guid]::TryParse($SessionId,[ref]$parsed)){throw 'Supply the exact current chat session UUID with -SessionId.'}
    $entry=$markers[$Action];$entry.payload=@{station_id='uihandoff2';route='messages';session_id=$parsed.ToString();expires_at=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+900)}
    $path=Join-Path $taskData $entry.name;[IO.File]::WriteAllText($path,($entry.payload|ConvertTo-Json -Depth 4),[Text.UTF8Encoding]::new($false));Write-Output "Enabled a 15-minute messages GET-only fault for session $($parsed.ToString()).";exit 0
}
throw 'Unsupported station action.'
