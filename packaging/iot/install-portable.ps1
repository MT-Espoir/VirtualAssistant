# Download a pinned Mosquitto Windows build without running system installers.

$ErrorActionPreference = 'Stop'
$cacheDir = Join-Path $PSScriptRoot '.cache'
$binDir = Join-Path $PSScriptRoot 'mosquitto'
foreach ($path in @($cacheDir, $binDir)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}
$brokerExe = Join-Path $binDir 'mosquitto.exe'
if (Test-Path -LiteralPath $brokerExe) {
    $versionText = (& $brokerExe -h 2>&1 | Out-String)
    $required = @('mosquitto_pub.exe', 'mosquitto_sub.exe',
                  'mosquitto_passwd.exe', 'mosquitto_common.dll',
                  'libcrypto-3-x64.dll', 'libssl-3-x64.dll')
    $complete = @($required | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $binDir $_))
    }).Count -eq 0
    $brokerHash = (Get-FileHash -LiteralPath $brokerExe -Algorithm SHA256).Hash
    if ($complete -and $versionText -match 'mosquitto version 2\.1\.2' -and
        $brokerHash -eq 'DAA688DBC3685890999084DA72F98EA0FAE9557F7544A2CB96B44EF46563F2A2') {
        Write-Host "Mosquitto 2.1.2 is already available at $binDir"
        return
    }
    throw "Mosquitto is incomplete or has another version at $brokerExe. Stop the broker and inspect it before replacing."
}

function Get-PinnedFile {
    param([string]$Url, [string]$Name, [string]$Sha256)
    $path = Join-Path $cacheDir $Name
    if (-not (Test-Path -LiteralPath $path)) {
        & curl.exe -L --fail --silent --show-error $Url -o $path
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actual -ne $Sha256) { throw "SHA256 mismatch for $Name; remove that file and retry." }
    return $path
}

$sevenR = Get-PinnedFile `
    'https://github.com/ip7z/7zip/releases/download/26.03/7zr.exe' `
    '7zr.exe' `
    'AD4C82FADCBDF93C03B4FC440F300509C7D60C5C2F4D183E35D9D70D6957037D'
$sevenInstaller = Get-PinnedFile `
    'https://github.com/ip7z/7zip/releases/download/26.03/7z2603-x64.exe' `
    '7z2603-x64.exe' `
    '0859C524B8A63551848F0C246ABDDCB1D0B7B656B0FBFE879F8D85E61A9E6EDD'
$mosquittoInstaller = Get-PinnedFile `
    'https://mosquitto.org/files/binary/win64/mosquitto-2.1.2-install-windows-x64.exe' `
    'mosquitto-2.1.2-install-windows-x64.exe' `
    '58008AD7A22ADA0B4073AFA415801746E027C5F583E4FA52D0F4E9193B98D6AA'

& $sevenR e $sevenInstaller '7z.exe' '7z.dll' "-o$cacheDir" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not extract 7-Zip.' }
$sevenZ = Join-Path $cacheDir '7z.exe'
$files = @(
    'mosquitto.exe', 'mosquitto_pub.exe', 'mosquitto_sub.exe',
    'mosquitto_passwd.exe', 'mosquitto.dll', 'mosquitto_common.dll',
    'cjson.dll', 'libcrypto-3-x64.dll', 'libmicrohttpd-dll.dll',
    'libssl-3-x64.dll', 'pthreadVC3.dll', 'sqlite3.dll',
    'mosquitto_password_file.dll', 'mosquitto_acl_file.dll',
    'NOTICE.md', 'edl-v10'
)
& $sevenZ e $mosquittoInstaller $files "-o$binDir" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not extract Mosquitto.' }
Write-Host "Mosquitto 2.1.2 extracted to $binDir"
Write-Host 'No system-wide installer or service was run.'
