# Starts the Dynasty Trade Helper at http://127.0.0.1:8000, reachable from phones on the same Wi-Fi.
# Creates the virtualenv on first run and installs any new requirements after an update.
# -LocalOnly keeps it on this computer (use it on networks you don't trust).
param([switch]$LocalOnly)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements.txt
$bind = "127.0.0.1"
if (-not $LocalOnly) {
    $bind = "0.0.0.0"
    $net = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | Select-Object -First 1
    if ($net) {
        Write-Host ""
        Write-Host "  On your phone (same Wi-Fi): http://$($net.IPv4Address.IPAddress):8000" -ForegroundColor Green
        Write-Host "  Settings in the app shows a QR code for it."
        if ((Get-NetConnectionProfile -InterfaceIndex $net.InterfaceIndex).NetworkCategory -eq "Public") {
            Write-Host "  This network is set to Public, so Windows Firewall will block phones. At home, set it to" -ForegroundColor Yellow
            Write-Host "  Private: Settings > Network & internet > Wi-Fi > (your network) > Private network." -ForegroundColor Yellow
        }
        Write-Host ""
    }
}
Start-Process "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host $bind --port 8000
