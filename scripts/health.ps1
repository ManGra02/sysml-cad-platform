<#
.SYNOPSIS
    Queries /api/cad/health of the running bridge.

.DESCRIPTION
    Reads port and token itself from the handshake file that the bridge writes
    on startup. This is exactly how the backend does it later, too.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$handshake = Join-Path $env:APPDATA 'FreeCAD\v1-1\sysml-cad-platform\bridge.json'

if (-not (Test-Path $handshake)) {
    Write-Host "No handshake file found:" -ForegroundColor Yellow
    Write-Host "  $handshake"
    Write-Host ""
    Write-Host "This is the normal state as long as the bridge is not running."
    Write-Host "In FreeCAD: workbench 'SysML-CAD Bridge' -> Start bridge."
    exit 1
}

$data = Get-Content $handshake -Raw | ConvertFrom-Json
Write-Host "Bridge: PID $($data.pid), port $($data.port), session $($data.session_id.Substring(0,8))"
Write-Host ""

$uri = "http://127.0.0.1:$($data.port)/api/cad/health"
try {
    $response = Invoke-RestMethod -Uri $uri -Headers @{ Authorization = "Bearer $($data.token)" } -TimeoutSec 5
} catch {
    Write-Host "No response from $uri" -ForegroundColor Red
    Write-Host "Is the bridge still running? The handshake file may be orphaned."
    exit 1
}

$response | ConvertTo-Json -Depth 5
