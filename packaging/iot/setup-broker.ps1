param(
    [string]$BindAddress = '192.168.2.19',
    [ValidateRange(1, 65535)][int]$Port = 1883,
    [switch]$ResetCredentials
)

$ErrorActionPreference = 'Stop'
$iotDir = $PSScriptRoot
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $iotDir '../..')).Path
$binDir = Join-Path $iotDir 'mosquitto'
$runtimeDir = Join-Path $iotDir 'runtime'
$passwdTool = Join-Path $binDir 'mosquitto_passwd.exe'
if (-not (Test-Path -LiteralPath $passwdTool)) {
    throw "Mosquitto portable binary is missing: $passwdTool. See packaging/iot/README.md."
}

foreach ($path in @($runtimeDir, (Join-Path $runtimeDir 'data'),
                    (Join-Path $runtimeDir 'logs'))) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}
$credentialsPath = Join-Path $runtimeDir 'credentials.json'
$passwordsPath = Join-Path $runtimeDir 'passwords'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

if ($ResetCredentials -or -not (Test-Path -LiteralPath $credentialsPath) -or
    -not (Test-Path -LiteralPath $passwordsPath)) {
    $credentials = [ordered]@{
        gateway_username = 'alice-gateway'
        gateway_password = New-Secret
        device_username = 'esp32s3-ir-gateway'
        device_password = New-Secret
    }
    $plain = "{0}:{1}`n{2}:{3}`n" -f $credentials.gateway_username,
        $credentials.gateway_password, $credentials.device_username,
        $credentials.device_password
    [IO.File]::WriteAllText($passwordsPath, $plain, $utf8)
    try {
        & $passwdTool -U $passwordsPath
        if ($LASTEXITCODE -ne 0) { throw "mosquitto_passwd failed: $LASTEXITCODE" }
    } catch {
        Remove-Item -LiteralPath $passwordsPath -Force -ErrorAction SilentlyContinue
        throw
    }
    [IO.File]::WriteAllText($credentialsPath,
        ($credentials | ConvertTo-Json -Depth 3), $utf8)
} else {
    $credentials = Get-Content -LiteralPath $credentialsPath -Raw |
        ConvertFrom-Json
}

$aclPath = Join-Path $runtimeDir 'acl'
Copy-Item -LiteralPath (Join-Path $iotDir 'acl.example') -Destination $aclPath -Force
$confPath = Join-Path $runtimeDir 'mosquitto.conf'
$unixPath = { param($path) $path.Replace('\', '/') }
$passwordsFile = & $unixPath $passwordsPath
$aclFile = & $unixPath $aclPath
$dataDir = (& $unixPath (Join-Path $runtimeDir 'data')) + '/'
$conf = @"
listener $Port $BindAddress
allow_anonymous false
password_file $passwordsFile
acl_file $aclFile
persistence true
persistence_location $dataDir
autosave_interval 60
log_dest stdout
log_type error
log_type warning
log_type notice
"@
[IO.File]::WriteAllText($confPath, $conf + "`n", $utf8)

# Keep the existing Alice settings and secrets; change only the IoT connection keys.
$envPath = Join-Path $projectRoot 'src/.env'
$envText = if (Test-Path -LiteralPath $envPath) {
    [IO.File]::ReadAllText($envPath)
} else { '' }
$values = [ordered]@{
    IOT_MQTT_HOST = $BindAddress
    IOT_MQTT_PORT = [string]$Port
    IOT_MQTT_USERNAME = [string]$credentials.gateway_username
    IOT_MQTT_PASSWORD = [string]$credentials.gateway_password
    IOT_COMMAND_PROTOCOL = 'composite'
    IOT_COMMANDS_ENABLED = 'true'
    IOT_AUTOMATION_ENABLED = 'false'
}
foreach ($key in $values.Keys) {
    $line = "$key=$($values[$key])"
    $pattern = '(?m)^' + [regex]::Escape($key) + '=.*$'
    if ([regex]::IsMatch($envText, $pattern)) {
        $envText = [regex]::Replace($envText, $pattern,
            [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $line })
    } else {
        if ($envText.Length -gt 0 -and -not $envText.EndsWith("`n")) {
            $envText += "`n"
        }
        $envText += "$line`n"
    }
}
[IO.File]::WriteAllText($envPath, $envText, $utf8)

$gatewayOpts = "-h $BindAddress`n-p $Port`n-u $($credentials.gateway_username)`n-P $($credentials.gateway_password)`n"
$deviceOpts = "-h $BindAddress`n-p $Port`n-u $($credentials.device_username)`n-P $($credentials.device_password)`n"
[IO.File]::WriteAllText((Join-Path $runtimeDir 'gateway-client.opts'), $gatewayOpts, $utf8)
[IO.File]::WriteAllText((Join-Path $runtimeDir 'device-client.opts'), $deviceOpts, $utf8)
Write-Host "Broker configured at $BindAddress`:$Port"
Write-Host "Config: $confPath"
Write-Host "ESP32 credentials: $credentialsPath (keep private)"
Write-Host 'Run .\packaging\iot\start-broker.ps1 to start the broker.'
