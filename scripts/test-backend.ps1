[CmdletBinding()]
param([string[]]$PytestFile = @())

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$python = Get-Command python -ErrorAction Stop
$out = Join-Path $root ("storage/quality-audits/backend-test-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + "-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$arguments = @('scripts/test_backend.py', '--output-dir', $out)
foreach ($file in $PytestFile) { $arguments += @('--pytest-file', $file) }
Push-Location $root
try { & $python.Source @arguments; exit $LASTEXITCODE }
finally { Pop-Location }
