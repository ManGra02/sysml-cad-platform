<#
.SYNOPSIS
    Starts the platform in normal mode: ONE process, http://127.0.0.1:8000.

.DESCRIPTION
    The backend serves the built UI itself -- no Vite, no
    second port. If the build is stale (e.g. after "git pull"), it is
    rebuilt first. You start FreeCAD yourself; the order does not matter.

    For development with hot reload, use scripts\dev.ps1 instead.

.PARAMETER NoBrowser
    Don't open the browser.

.PARAMETER Rebuild
    Always rebuild the UI.
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
    throw "Backend not set up. Run scripts\setup.ps1 first."
}

# Already running? Then just open the browser -- a second backend would fail on the fixed port.
if (Test-Backend) {
    Write-Host "Backend already running -> $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}

# -- UI up to date? -------------------------------------------------------
Push-Location $backendDir
try {
    $state = (& uv run python ../scripts/build_status.py) -join ''
} finally {
    Pop-Location
}
if ($Rebuild -or $state -notlike 'fresh*') {
    Write-Host "UI: $state -> rebuilding ..."
    # install on every rebuild: dependencies may have changed after "git pull".
    Invoke-Pnpm $frontendDir @('install', '--frozen-lockfile')
    Invoke-Pnpm $frontendDir @('build')
}

# -- Backend --------------------------------------------------------------
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backendDir `
    -FilePath 'uv' -ArgumentList @('run', 'python', '-m', 'app')

$deadline = (Get-Date).AddSeconds(30)
while (-not (Test-Backend)) {
    if ($backend.HasExited) { throw "Backend exits immediately (port 8000 in use?). scripts\doctor.py helps." }
    if ((Get-Date) -gt $deadline) { throw "Backend does not respond within 30 s." }
    Start-Sleep -Milliseconds 300
}

Write-Host ""
Write-Host "Platform running -> $url" -ForegroundColor Green
Write-Host "FreeCAD: 'SysML-CAD Bridge' workbench, start the bridge. Ctrl+C stops."
if (-not $NoBrowser) { Start-Process $url }

try {
    Wait-Process -Id $backend.Id
} finally {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
}
