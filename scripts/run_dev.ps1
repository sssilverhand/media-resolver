$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "$root\src;$root\vendor\python"

python -m media_resolver.app
