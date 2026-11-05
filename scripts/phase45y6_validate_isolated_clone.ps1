param(
    [switch]$RunContractTests,
    [switch]$RestoreBackup,
    [string]$TargetDatabase = 'phase45y6_devclone_final_test'
)
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pgBin = 'C:\Program Files\PostgreSQL\18\bin'
$data = Join-Path $repo 'storage\quality-audits\y6-isolated-20261014-run02\data'
$port = 59231
$database = $TargetDatabase
$backup = Join-Path $repo 'storage\quality-audits\phase45y3-20261014-run01\kaoyan-live-premerge.dump'
$expectedBackupSha256 = 'DBB296C037C229FCA6B1197638E3C8212A97C268D01C44FEA777DD3997370029'
$url = "postgresql+psycopg://postgres@127.0.0.1:$port/$database"
$pgCtl = Join-Path $pgBin 'pg_ctl.exe'
$psql = Join-Path $pgBin 'psql.exe'

if ($port -eq 5433 -or $database -notlike '*_test') { throw 'Refusing a non-isolated database target' }
if (-not (Test-Path (Join-Path $data 'PG_VERSION'))) { throw 'Isolated restored cluster is missing' }

& $pgCtl -D $data -l (Join-Path (Split-Path $data -Parent) 'postgresql.log') `
    -o "-p $port -h 127.0.0.1 -c listen_addresses=127.0.0.1" -w start
if ($LASTEXITCODE -ne 0) { throw "Isolated PostgreSQL start failed: $LASTEXITCODE" }

try {
    & (Join-Path $pgBin 'pg_isready.exe') -h 127.0.0.1 -p $port -t 3
    if ($LASTEXITCODE -ne 0) { throw 'Isolated PostgreSQL is not accepting connections' }
    Write-Output 'ISOLATED_CLUSTER_SYSTEM_ID:'
    & (Join-Path $pgBin 'pg_controldata.exe') $data | Select-String 'Database system identifier|Database cluster state'

    if ($RestoreBackup) {
        if ($database -notlike '*_test' -or $database -eq 'kaoyan') {
            throw 'Refusing to restore backup into a non-test database name'
        }
        if (-not (Test-Path $backup)) { throw 'Y3 custom-format backup is missing' }
        $backupSha256 = (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($backupSha256 -ne $expectedBackupSha256) { throw "Backup SHA-256 mismatch: $backupSha256" }
        $databaseExists = @(& $psql -h 127.0.0.1 -p $port -U postgres -d postgres -X -A -t `
            -v ON_ERROR_STOP=1 -c "SELECT 1 FROM pg_database WHERE datname='$database'") -join ''
        if ($LASTEXITCODE -ne 0) { throw 'Could not verify target database absence' }
        if ($databaseExists.Trim() -eq '1') { throw "Refusing to overwrite existing isolated database: $database" }
        Write-Output "BACKUP_SHA256:$backupSha256"
        Write-Output 'PG_RESTORE_TOC_READABLE:'
        & (Join-Path $pgBin 'pg_restore.exe') --list $backup | Select-Object -First 12
        if ($LASTEXITCODE -ne 0) { throw 'Backup TOC listing failed' }
        & (Join-Path $pgBin 'createdb.exe') -h 127.0.0.1 -p $port -U postgres $database
        if ($LASTEXITCODE -ne 0) { throw 'Could not create new isolated restore database' }
        & (Join-Path $pgBin 'pg_restore.exe') --exit-on-error --no-owner --no-privileges `
            -h 127.0.0.1 -p $port -U postgres -d $database $backup
        if ($LASTEXITCODE -ne 0) { throw 'Y3 backup restore into the new isolated database failed' }
        Write-Output "RESTORED_DATABASE:$database"
    }

    $env:APP_ENV = 'test'
    $env:TEST_DATABASE_URL = $url
    $env:DATABASE_URL = $url
    $env:KAOYAN_OWNED_TEST_PORT = "$port"

    $historicalCountSql = @"
SELECT 'practice_items|'||count(*) FROM practice_items
UNION ALL SELECT 'question_attempts|'||count(*) FROM question_attempts
UNION ALL SELECT 'learning_events|'||count(*) FROM learning_events
UNION ALL SELECT 'kp_states|'||count(*) FROM kp_states
ORDER BY 1;
"@
    Write-Output 'F46_HISTORICAL_COUNTS:'
    $historicCounts = @(& $psql -h 127.0.0.1 -p $port -U postgres -d $database -X -v ON_ERROR_STOP=1 -A -t -c $historicalCountSql)
    if ($LASTEXITCODE -ne 0) { throw 'Could not count historical records at f46' }
    $historicCounts | ForEach-Object { Write-Output $_ }

    $baselineSql = @"
SELECT 'questions|'||count(*)||'|'||md5(coalesce(string_agg((to_jsonb(t)-'current_version_id')::text,E'\n' ORDER BY id),'')) FROM questions t
UNION ALL SELECT 'practice_items|'||count(*)||'|'||md5(coalesce(string_agg((to_jsonb(t)-'question_version_id')::text,E'\n' ORDER BY id),'')) FROM practice_items t
UNION ALL SELECT 'question_attempts|'||count(*)||'|'||md5(coalesce(string_agg((to_jsonb(t)-'question_version_id')::text,E'\n' ORDER BY id),'')) FROM question_attempts t
UNION ALL SELECT 'learning_events|'||count(*)||'|'||md5(coalesce(string_agg((to_jsonb(t)-'question_version_id')::text,E'\n' ORDER BY id),'')) FROM learning_events t
UNION ALL SELECT 'kp_states|'||count(*)||'|'||md5(coalesce(string_agg(to_jsonb(t)::text,E'\n' ORDER BY kp_id),'')) FROM kp_states t
UNION ALL SELECT 'graduation_sets|'||count(*)||'|'||md5(coalesce(string_agg((to_jsonb(t)-'question_version_ids'-'question_version_ids_sha256')::text,E'\n' ORDER BY kp_id,set_version),'')) FROM kp_graduation_question_set_versions t
ORDER BY 1;
"@
    Write-Output 'PRE_MIGRATION_IDENTITY_AND_COUNTS:'
    & $psql -h 127.0.0.1 -p $port -U postgres -d $database -X -v ON_ERROR_STOP=1 -A -t -c `
        'SELECT current_database(), current_setting(''server_version_num''), version_num FROM alembic_version;' 
    if ($LASTEXITCODE -ne 0) { throw 'Could not read clone identity/revision' }
    alembic current
    if ($LASTEXITCODE -ne 0) { throw 'alembic current failed' }
    alembic upgrade f52a6c8d301e
    if ($LASTEXITCODE -ne 0) { throw 'Alembic upgrade to f52 failed on isolated restored clone' }
    Write-Output 'F52_HISTORICAL_FINGERPRINTS:'
    $before = @(& $psql -h 127.0.0.1 -p $port -U postgres -d $database -X -v ON_ERROR_STOP=1 -A -t -c $baselineSql)
    if ($LASTEXITCODE -ne 0) { throw 'Could not compute f52 historical fingerprints' }
    $before | ForEach-Object { Write-Output $_ }
    Write-Output 'F52_HISTORICAL_COUNTS:'
    $f52Counts = @(& $psql -h 127.0.0.1 -p $port -U postgres -d $database -X -v ON_ERROR_STOP=1 -A -t -c $historicalCountSql)
    if ($LASTEXITCODE -ne 0) { throw 'Could not count historical records at f52' }
    $f52Counts | ForEach-Object { Write-Output $_ }
    alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Alembic upgrade failed on isolated restored clone' }
    alembic check
    if ($LASTEXITCODE -ne 0) { throw 'Alembic model/schema consistency check failed on isolated restored clone' }
    Write-Output 'POST_MIGRATION_IDENTITY_AND_VERSION_COUNTS:'
    & $psql -h 127.0.0.1 -p $port -U postgres -d $database -X -v ON_ERROR_STOP=1 -A -t -c `
        "SELECT version_num FROM alembic_version; SELECT 'questions',count(*) FROM questions UNION ALL SELECT 'question_versions',count(*) FROM question_versions UNION ALL SELECT 'items_bound',count(*) FROM practice_items WHERE question_id IS NOT NULL AND question_version_id IS NOT NULL UNION ALL SELECT 'attempts_bound',count(*) FROM question_attempts WHERE question_id IS NOT NULL AND question_version_id IS NOT NULL UNION ALL SELECT 'learning_events_bound',count(*) FROM learning_events WHERE question_version_id IS NOT NULL UNION ALL SELECT 'graduation_sets_bound',count(*) FROM kp_graduation_question_set_versions WHERE question_version_ids IS NOT NULL AND question_version_ids_sha256 IS NOT NULL; SELECT 'unbound_learning_event|'||event_type||'|'||count(*) FROM learning_events WHERE question_version_id IS NULL GROUP BY event_type ORDER BY event_type;"
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify migrated version bindings' }
    Write-Output 'POST_MIGRATION_HISTORICAL_FINGERPRINTS:'
    $after = @(& $psql -h 127.0.0.1 -p $port -U postgres -d $database -X -v ON_ERROR_STOP=1 -A -t -c $baselineSql)
    if ($LASTEXITCODE -ne 0) { throw 'Could not compute post-migration fingerprints' }
    $after | ForEach-Object { Write-Output $_ }
    if (Compare-Object $before $after) { throw 'Historical table fingerprints changed during migration' }
    Write-Output 'HISTORICAL_FINGERPRINTS_UNCHANGED: true'
    if (Compare-Object $historicCounts $f52Counts) { throw 'Legacy migration unexpectedly changed attempt/event/state row counts' }
    Write-Output 'F46_TO_F52_HISTORY_ROW_COUNTS_UNCHANGED: true'

    if ($RunContractTests) {
        $contractDb = 'phase45y6_contract_test'
        $contractUrl = "postgresql+psycopg://postgres@127.0.0.1:$port/$contractDb"
        $exists = [string](& $psql -h 127.0.0.1 -p $port -U postgres -d postgres -X -A -t -c `
            "SELECT 1 FROM pg_database WHERE datname='$contractDb'"
        )
        if ($exists.Trim() -ne '1') {
            & (Join-Path $pgBin 'createdb.exe') -h 127.0.0.1 -p $port -U postgres $contractDb
            if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated contract test database' }
        }
        $env:TEST_DATABASE_URL = $contractUrl
        $env:DATABASE_URL = $contractUrl
        alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Could not migrate isolated contract test database' }
        pytest -q tests/integration/test_question_immutable_versions.py
        if ($LASTEXITCODE -ne 0) { throw 'Question immutable-version contract tests failed' }
    }
}
finally {
    & $pgCtl -D $data -m fast -w stop
    if ($LASTEXITCODE -ne 0) { Write-Error 'Could not normally stop isolated PostgreSQL cluster' }
}
