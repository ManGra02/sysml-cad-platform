<#
.SYNOPSIS
    Startet die Plattform im Normalbetrieb: EIN Prozess, http://127.0.0.1:8000.

.DESCRIPTION
    Das Backend liefert die gebaute Oberflaeche selbst aus -- kein Vite, kein
    zweiter Port. Ist der Build veraltet (etwa nach "git pull"), wird vorher
    neu gebaut. FreeCAD startet ihr selbst; die Reihenfolge ist egal.

    Zum Entwickeln mit Hot-Reload stattdessen scripts\dev.ps1.

.PARAMETER NoBrowser
    Den Browser nicht oeffnen.

.PARAMETER Rebuild
    Oberflaeche in jedem Fall neu bauen.
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repo 'backend'
$frontendDir = Join-Path $repo 'frontend'
$url = 'http://127.0.0.1:8000'
. (Join-Path $PSScriptRoot '_common.ps1')
Initialize-PlatformEnvironment

function Test-Backend {
    try {
        Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Path (Join-Path $backendDir '.venv'))) {
    throw "Backend nicht eingerichtet. Zuerst scripts\setup.ps1 ausfuehren."
}

# Laeuft schon? Dann nur den Browser oeffnen -- ein zweites Backend scheitert am festen Port.
if (Test-Backend) {
    Write-Host "Backend laeuft bereits -> $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}

# -- Oberflaeche aktuell? -------------------------------------------------
Push-Location $backendDir
try {
    $state = (& uv run python ../scripts/build_status.py) -join ''
} finally {
    Pop-Location
}
if ($Rebuild -or $state -notlike 'fresh*') {
    Write-Host "Oberflaeche: $state -> baue neu ..."
    # install bei jedem Neubau: nach "git pull" koennen sich Abhaengigkeiten geaendert haben.
    Invoke-Pnpm $frontendDir @('install', '--frozen-lockfile')
    Invoke-Pnpm $frontendDir @('build')
}

# -- Backend --------------------------------------------------------------
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backendDir `
    -FilePath 'uv' -ArgumentList @('run', 'python', '-m', 'app')

$deadline = (Get-Date).AddSeconds(30)
while (-not (Test-Backend)) {
    if ($backend.HasExited) { throw "Backend beendet sich sofort (Port 8000 belegt?). scripts\doctor.py hilft." }
    if ((Get-Date) -gt $deadline) { throw "Backend antwortet nicht innerhalb von 30 s." }
    Start-Sleep -Milliseconds 300
}

Write-Host ""
Write-Host "Plattform laeuft -> $url" -ForegroundColor Green
Write-Host "FreeCAD: Workbench 'SysML-CAD Bruecke', Bruecke starten. Strg+C beendet."
if (-not $NoBrowser) { Start-Process $url }

try {
    Wait-Process -Id $backend.Id
} finally {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
}
