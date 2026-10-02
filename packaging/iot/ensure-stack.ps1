param([Parameter(Mandatory = $true)][string]$Python)

$ErrorActionPreference = 'Stop'
$iotDir = $PSScriptRoot
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $iotDir '../..')).Path
$runtimeDir = Join-Path $iotDir 'runtime'
$logsDir = Join-Path $runtimeDir 'logs'
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$startupLog = Join-Path $logsDir 'startup.log'

function Write-StartupLog([string]$Message) {
    Add-Content -LiteralPath $startupLog -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}

function Test-ListeningPort([string]$HostName, [int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($connect)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-Broker([string]$HostName, [int]$Port) {
    if (-not (Test-ListeningPort $HostName $Port)) { return $false }
    $pub = Join-Path $iotDir 'mosquitto/mosquitto_pub.exe'
    $options = Join-Path $runtimeDir 'gateway-client.opts'
    if (-not (Test-Path -LiteralPath $pub) -or -not (Test-Path -LiteralPath $options)) {
        throw 'Mosquitto client or credentials are missing. Run install-portable.ps1 and setup-broker.ps1 once.'
    }
    # Windows PowerShell 5.1 can leave Start-Process.PassThru.ExitCode empty
    # even after WaitForExit(), so use the native command's LASTEXITCODE.
    & $pub -o $options -t 'alice/iot/healthcheck' -m 'startup-probe' `
        1> (Join-Path $logsDir 'broker-probe.out.log') `
        2> (Join-Path $logsDir 'broker-probe.err.log')
    return ($LASTEXITCODE -eq 0)
}

function Get-GatewayStatus([int]$Port) {
    $tokenPath = Join-Path $projectRoot 'data/iot_api_token'
    if (-not (Test-Path -LiteralPath $tokenPath)) { return $null }
    try {
        $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/status" `
            -Headers @{ 'X-Alice-IoT-Token' = $token } -TimeoutSec 2
    } catch {
        return $null
    }
}

$mutex = New-Object System.Threading.Mutex($false, 'Local\AliceIoTStartup')
$locked = $false
try {
    try {
        $locked = $mutex.WaitOne(15000)
    } catch [System.Threading.AbandonedMutexException] {
        $locked = $true
    }
    if (-not $locked) { throw 'Timed out waiting for another IoT startup.' }

    if (-not (Test-Path -LiteralPath $Python)) { throw "Alice Python is missing: $Python" }
    $broker = Join-Path $iotDir 'mosquitto/mosquitto.exe'
    $conf = Join-Path $runtimeDir 'mosquitto.conf'
    if (-not (Test-Path -LiteralPath $broker) -or -not (Test-Path -LiteralPath $conf)) {
        throw 'Broker files are missing. Run install-portable.ps1 and setup-broker.ps1 once.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $iotDir 'mosquitto/mosquitto_pub.exe')) -or
        -not (Test-Path -LiteralPath (Join-Path $runtimeDir 'gateway-client.opts'))) {
        throw 'Broker healthcheck files are missing. Run install-portable.ps1 and setup-broker.ps1 once.'
    }
    $listener = Select-String -LiteralPath $conf -Pattern '^listener\s+(\d+)\s+(\S+)' | Select-Object -First 1
    if (-not $listener) { throw "No listener found in $conf" }
    $brokerPort = [int]$listener.Matches[0].Groups[1].Value
    $brokerHost = $listener.Matches[0].Groups[2].Value
    $localAddresses = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
        ForEach-Object { $_.GetIPProperties().UnicastAddresses } |
        ForEach-Object { $_.Address.IPAddressToString }
    if ($brokerHost -ne '0.0.0.0' -and $brokerHost -notin $localAddresses) {
        throw "Broker IP $brokerHost is no longer assigned to this PC. Rerun setup-broker.ps1 -BindAddress <current LAN IP>."
    }

    if (Test-Broker $brokerHost $brokerPort) {
        Write-StartupLog "Broker already available at $brokerHost`:$brokerPort."
    } else {
        if (Test-ListeningPort $brokerHost $brokerPort) {
            throw "Port $brokerHost`:$brokerPort is open, but authenticated MQTT probe failed. Check broker-probe.err.log."
        }
        $brokerProcess = Start-Process -FilePath $broker -ArgumentList ('-c "' + $conf + '"') `
            -WorkingDirectory $iotDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logsDir 'broker.stdout.log') `
            -RedirectStandardError (Join-Path $logsDir 'broker.stderr.log')
        Write-StartupLog "Started broker (PID $($brokerProcess.Id))."
        $brokerReady = $false
        for ($attempt = 0; $attempt -lt 16; $attempt++) {
            Start-Sleep -Milliseconds 500
            if (Test-Broker $brokerHost $brokerPort) { $brokerReady = $true; break }
            if ($brokerProcess.HasExited) { break }
        }
        if (-not $brokerReady) { throw "Broker did not become ready. See $logsDir." }
    }

    $apiPort = 18787
    $envFile = Join-Path $projectRoot 'src/.env'
    if ($env:IOT_API_PORT) {
        $apiPort = [int]$env:IOT_API_PORT
    } elseif (Test-Path -LiteralPath $envFile) {
        $apiSetting = Select-String -LiteralPath $envFile -Pattern '^IOT_API_PORT\s*=\s*(\d+)' | Select-Object -Last 1
        if ($apiSetting) { $apiPort = [int]$apiSetting.Matches[0].Groups[1].Value }
    }
    $gatewayStatus = Get-GatewayStatus $apiPort
    if ($null -ne $gatewayStatus -and $gatewayStatus.policy_version -ne 2) {
        # Upgrade only the authenticated gateway listening on our loopback port.
        # Never stop an arbitrary Python process or restart the MQTT broker.
        $gatewayListener = Get-NetTCPConnection -LocalAddress '127.0.0.1' `
            -LocalPort $apiPort -State Listen -ErrorAction Stop | Select-Object -First 1
        $oldGatewayPid = [int]$gatewayListener.OwningProcess
        $oldGatewayProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $oldGatewayPid"
        if ($null -eq $oldGatewayProcess -or
            $oldGatewayProcess.ExecutablePath -ne $Python -or
            $oldGatewayProcess.CommandLine -notmatch '(?i)(?:^|\s)-m\s+features\.iot\.gateway(?:\s|$)') {
            throw 'The existing gateway needs an update, but its process could not be verified. Restart that gateway manually.'
        }
        Write-StartupLog "Reloading old gateway policy (PID $oldGatewayPid)."
        Stop-Process -Id $oldGatewayPid -ErrorAction Stop
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (-not (Test-ListeningPort '127.0.0.1' $apiPort)) { break }
            Start-Sleep -Milliseconds 250
        }
        $gatewayStatus = $null
    }
    if ($null -ne $gatewayStatus) {
        Write-StartupLog "Gateway already available at 127.0.0.1:$apiPort."
    } else {
        if (Test-ListeningPort '127.0.0.1' $apiPort) {
            throw "Port 127.0.0.1:$apiPort is open, but the authenticated gateway API did not respond."
        }
        $gatewayProcess = Start-Process -FilePath $Python -ArgumentList '-X utf8 -m features.iot.gateway' `
            -WorkingDirectory (Join-Path $projectRoot 'src') -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logsDir 'gateway.stdout.log') `
            -RedirectStandardError (Join-Path $logsDir 'gateway.stderr.log')
        Write-StartupLog "Started gateway (PID $($gatewayProcess.Id))."
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Milliseconds 500
            $gatewayStatus = Get-GatewayStatus $apiPort
            if ($null -ne $gatewayStatus) { break }
            if ($gatewayProcess.HasExited) { break }
        }
        if ($null -eq $gatewayStatus) { throw "Gateway did not become ready. See $logsDir." }
    }

    for ($attempt = 0; $attempt -lt 10 -and -not $gatewayStatus.broker_connected; $attempt++) {
        Start-Sleep -Milliseconds 500
        $gatewayStatus = Get-GatewayStatus $apiPort
        if ($null -eq $gatewayStatus) { throw 'Gateway API stopped during startup.' }
    }
    if (-not $gatewayStatus.broker_connected) { throw 'Gateway API is running, but MQTT is disconnected.' }
    Write-StartupLog 'IoT broker and gateway are ready.'
    exit 0
} catch {
    Write-StartupLog "Startup failed: $($_.Exception.Message)"
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
