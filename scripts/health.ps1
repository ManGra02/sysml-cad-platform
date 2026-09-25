<#
.SYNOPSIS
    Fragt /api/cad/health der laufenden Bruecke ab.

.DESCRIPTION
    Liest Port und Token selbst aus der Handshake-Datei, die die Bruecke beim
    Start schreibt. Genau so macht es spaeter auch das Backend.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$handshake = Join-Path $env:APPDATA 'FreeCAD\v1-1\sysml-cad-platform\bridge.json'

if (-not (Test-Path $handshake)) {
    Write-Host "Keine Handshake-Datei gefunden:" -ForegroundColor Yellow
    Write-Host "  $handshake"
    Write-Host ""
    Write-Host "Das ist der Normalzustand, solange die Bruecke nicht laeuft."
    Write-Host "In FreeCAD: Workbench 'SysML-CAD Bruecke' -> Starten."
    exit 1
}

$data = Get-Content $handshake -Raw | ConvertFrom-Json
Write-Host "Bruecke: PID $($data.pid), Port $($data.port), Sitzung $($data.session_id.Substring(0,8))"
Write-Host ""

$uri = "http://127.0.0.1:$($data.port)/api/cad/health"
try {
    $response = Invoke-RestMethod -Uri $uri -Headers @{ Authorization = "Bearer $($data.token)" } -TimeoutSec 5
} catch {
    Write-Host "Keine Antwort von $uri" -ForegroundColor Red
    Write-Host "Laeuft die Bruecke noch? Die Handshake-Datei kann verwaist sein."
    exit 1
}

$response | ConvertTo-Json -Depth 5
