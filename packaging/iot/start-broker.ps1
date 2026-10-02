$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'mosquitto/mosquitto.exe'
$conf = Join-Path $PSScriptRoot 'runtime/mosquitto.conf'
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Mosquitto binary missing: $exe. See packaging/iot/README.md."
}
if (-not (Test-Path -LiteralPath $conf)) {
    throw "Broker config missing. Run .\packaging\iot\setup-broker.ps1 first."
}
$listener = Select-String -LiteralPath $conf -Pattern '^listener\s+\d+\s+(.+)$' |
    Select-Object -First 1
if ($listener) {
    $address = $listener.Matches[0].Groups[1].Value.Trim()
    $localAddresses = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
        ForEach-Object { $_.GetIPProperties().UnicastAddresses } |
        ForEach-Object { $_.Address.IPAddressToString }
    if ($address -ne '0.0.0.0' -and $address -notin $localAddresses) {
        throw "IP $address is not assigned to this computer. Run setup-broker.ps1 -BindAddress <current LAN IP>."
    }
}
Write-Host "Starting project Mosquitto with $conf (Ctrl+C to stop)."
& $exe -c $conf -v
if ($LASTEXITCODE -ne 0) { throw "Mosquitto exited with code $LASTEXITCODE" }
