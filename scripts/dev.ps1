<#
.SYNOPSIS
    Startet Backend (und Vite, sobald das Frontend existiert) fuer die Entwicklung.

.DESCRIPTION
    FreeCAD startet ihr selbst; die Bruecke im Dock-Panel starten. Das Backend
    verbindet sich von allein, sobald sie laeuft -- die Reihenfolge ist egal.

    Backend:  http://127.0.0.1:8000   (mit --reload)
    Vite:     http://127.0.0.1:5173   (Proxy /api und /ws -> 8000)
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')
Initialize-PlatformEnvironment

$jobs = @()
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $repo 'backend') `
    -FilePath 'uv' -ArgumentList @('run', 'python', '-m', 'app', '--reload', '--dev')
$jobs += $backend
Write-Host "Backend gestartet (PID $($backend.Id)) -> http://127.0.0.1:8000"

$frontend = Join-Path $repo 'frontend'
if (Test-Path (Join-Path $frontend 'package.json')) {
    if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
        Invoke-Pnpm $frontend @('install', '--frozen-lockfile')
    }
    $pnpm = @(Get-PnpmCommand)
    $vite = Start-Process -PassThru -NoNewWindow -WorkingDirectory $frontend `
        -FilePath $pnpm[0] -ArgumentList (@($pnpm | Select-Object -Skip 1) + 'dev')
    $jobs += $vite
    Write-Host "Vite gestartet (PID $($vite.Id)) -> http://127.0.0.1:5173  <- im Browser oeffnen"
} else {
    Write-Host "Frontend noch nicht angelegt -- nur Backend."
}

Write-Host "Strg+C beendet alles."
try {
    Wait-Process -Id ($jobs | ForEach-Object { $_.Id })
} finally {
    foreach ($job in $jobs) {
        if (-not $job.HasExited) { Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue }
    }
}
