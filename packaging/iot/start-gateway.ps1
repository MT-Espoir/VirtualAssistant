param([string]$Python)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if (-not $Python) {
    $launcher = [IO.File]::ReadAllText((Join-Path $projectRoot 'launch_assistant.vbs'))
    $match = [regex]::Match($launcher, '(?m)^python = "([^"]+)"')
    $Python = if ($match.Success) { $match.Groups[1].Value } else { 'python' }
}
if (-not (Test-Path -LiteralPath $Python) -and -not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python not found: $Python"
}
$deps = Join-Path $PSScriptRoot 'python-deps'
if (-not (Test-Path -LiteralPath (Join-Path $deps 'paho'))) {
    throw "paho-mqtt is missing. Run: & '$Python' -m pip install --target '$deps' paho-mqtt==2.1.0"
}
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = "$deps;$($projectRoot)\src" +
    $(if ($previousPythonPath) { ";$previousPythonPath" } else { '' })
Push-Location (Join-Path $projectRoot 'src')
try {
    Write-Host 'Starting Alice IoT gateway (Ctrl+C to stop).'
    & $Python -m features.iot.gateway
    if ($LASTEXITCODE -ne 0) { throw "IoT gateway exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
