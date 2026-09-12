$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Install the project virtual environment first.'
}
$launcher = Join-Path $PSScriptRoot 'start_codex.py'
& $python $launcher @args
exit $LASTEXITCODE
