param([string[]]$TestPaths = @(
    'tests/integration/test_question_immutable_versions.py',
    'tests/integration/test_answer_submissions.py',
    'tests/integration/test_learning_loop.py'
))
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pgBin = 'C:\Program Files\PostgreSQL\18\bin'
$data = Join-Path $repo 'storage\quality-audits\y6-isolated-20261014-run02\data'
$root = Split-Path $data -Parent
$port = 59231
$database = 'phase45y6_contract14_test'
$url = "postgresql+psycopg://postgres@127.0.0.1:$port/$database"
$pgCtl = Join-Path $pgBin 'pg_ctl.exe'
$psql = Join-Path $pgBin 'psql.exe'

if ($port -eq 5433 -or $database -notlike '*_test') { throw 'Refusing a non-isolated test database target' }
if (-not (Test-Path (Join-Path $data 'PG_VERSION'))) { throw 'Isolated cluster is missing' }

& $pgCtl -D $data -l (Join-Path $root 'contract-tests.log') `
    -o "-p $port -h 127.0.0.1 -c listen_addresses=127.0.0.1" -w start
if ($LASTEXITCODE -ne 0) { throw 'Could not start the isolated cluster' }
try {
    & (Join-Path $pgBin 'pg_isready.exe') -h 127.0.0.1 -p $port -t 3
    if ($LASTEXITCODE -ne 0) { throw 'Isolated cluster is not ready' }
    $existsLines = @(& $psql -h 127.0.0.1 -p $port -U postgres -d postgres -X -A -t -v ON_ERROR_STOP=1 `
        -c "SELECT 1 FROM pg_database WHERE datname='$database'")
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect isolated test database list' }
    $exists = ($existsLines -join '').Trim()
    if ($exists -ne '1') {
        & (Join-Path $pgBin 'createdb.exe') -h 127.0.0.1 -p $port -U postgres $database
        if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated contract test database' }
    }

    $env:APP_ENV = 'test'
    $env:TEST_DATABASE_URL = $url
    $env:DATABASE_URL = $url
    $env:KAOYAN_OWNED_TEST_PORT = "$port"
    alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Could not migrate the isolated contract test database' }
    pytest -o addopts= -q --tb=short -x @TestPaths
    if ($LASTEXITCODE -ne 0) { throw "Question version and learning-loop tests failed: $LASTEXITCODE" }
    alembic check
    if ($LASTEXITCODE -ne 0) { throw 'Alembic model/schema consistency check failed' }
    & $psql -h 127.0.0.1 -p $port -U postgres -d $database -X -v ON_ERROR_STOP=1 -P pager=off `
        -c "SELECT version_num FROM alembic_version; SELECT 'question_versions',count(*) FROM question_versions; SELECT 'attempt_version_nulls',count(*) FROM question_attempts WHERE question_id IS NOT NULL AND question_version_id IS NULL; SELECT 'practice_item_version_nulls',count(*) FROM practice_items WHERE question_id IS NOT NULL AND question_version_id IS NULL;"
    if ($LASTEXITCODE -ne 0) { throw 'Final contract database verification failed' }
}
finally {
    & $pgCtl -D $data -m fast -w stop
    if ($LASTEXITCODE -ne 0) { Write-Error 'Could not normally stop the isolated cluster' }
}
