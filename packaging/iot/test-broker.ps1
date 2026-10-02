$ErrorActionPreference = 'Stop'
$binDir = Join-Path $PSScriptRoot 'mosquitto'
$runtimeDir = Join-Path $PSScriptRoot 'runtime'
$pub = Join-Path $binDir 'mosquitto_pub.exe'
$sub = Join-Path $binDir 'mosquitto_sub.exe'
$options = Join-Path $runtimeDir 'gateway-client.opts'
if (-not (Test-Path -LiteralPath $pub) -or -not (Test-Path -LiteralPath $sub) -or
    -not (Test-Path -LiteralPath $options)) {
    throw 'Run setup-broker.ps1 and start-broker.ps1 first.'
}
$topic = 'alice/iot/healthcheck'
$payload = 'ping-' + [guid]::NewGuid().ToString('N')
$output = Join-Path $runtimeDir 'healthcheck.out'
$errorOutput = Join-Path $runtimeDir 'healthcheck.err'
$subArgs = '-o "' + $options + '" -t ' + $topic + ' -C 1'
$subscriber = Start-Process -FilePath $sub -ArgumentList $subArgs -PassThru `
    -WindowStyle Hidden -RedirectStandardOutput $output -RedirectStandardError $errorOutput
try {
    Start-Sleep -Milliseconds 600
    & $pub -o $options -t $topic -m $payload
    if ($LASTEXITCODE -ne 0) { throw "Publish failed: $LASTEXITCODE" }
    if (-not $subscriber.WaitForExit(5000)) { throw 'Subscribe timed out after 5 seconds' }
    $received = (Get-Content -LiteralPath $output -Raw).Trim()
    if ($subscriber.ExitCode -ne 0 -or $received -ne $payload) {
        throw "MQTT round trip failed. See $errorOutput"
    }
    Write-Host 'MQTT publish/subscribe succeeded with project broker authentication.'
    Write-Host "Topic: $topic"
} finally {
    if (-not $subscriber.HasExited) { Stop-Process -Id $subscriber.Id -Force }
}
