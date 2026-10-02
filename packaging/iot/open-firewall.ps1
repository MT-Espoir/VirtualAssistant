param(
    [string]$LocalAddress = '192.168.2.19',
    [string]$RemoteSubnet = '192.168.2.0/24',
    [ValidateRange(1, 65535)][int]$Port = 1883
)

$ErrorActionPreference = 'Stop'
$ruleName = 'Alice IoT Mosquitto LAN'
$program = Join-Path $PSScriptRoot 'mosquitto/mosquitto.exe'
if (-not (Test-Path -LiteralPath $program)) { throw "Mosquitto missing: $program" }
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell terminal.'
}
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $ruleName"
    return
}
New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $Port -LocalAddress $LocalAddress `
    -RemoteAddress $RemoteSubnet -Program $program -Profile Any | Out-Null
Write-Host "Allowed TCP $Port to $LocalAddress from $RemoteSubnet for project Mosquitto."
