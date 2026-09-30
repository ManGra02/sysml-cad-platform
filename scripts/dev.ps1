<#
.SYNOPSIS
    Starts the backend (and Vite, once the frontend exists) for development.

.DESCRIPTION
    You start FreeCAD yourself; start the bridge in the dock panel. The backend
    connects on its own as soon as it is running -- the order does not matter.

    Backend:  http://127.0.0.1:8000   (with --reload)
    Vite:     http://127.0.0.1:5173   (proxy /api and /ws -> 8000)
#>
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')
Initialize-PlatformEnvironment

$jobs = @()
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $repo 'backend') `
    -FilePath 'uv' -ArgumentList @('run', 'python', '-m', 'app', '--reload', '--dev')
$jobs += $backend
Write-Host "Backend started (PID $($backend.Id)) -> http://127.0.0.1:8000"

$frontend = Join-Path $repo 'frontend'
if (Test-Path (Join-Path $frontend 'package.json')) {
    if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
        Invoke-Pnpm $frontend @('install', '--frozen-lockfile')
    }
    $pnpm = @(Get-PnpmCommand)
    $vite = Start-Process -PassThru -NoNewWindow -WorkingDirectory $frontend `
        -FilePath $pnpm[0] -ArgumentList (@($pnpm | Select-Object -Skip 1) + 'dev')
    $jobs += $vite
    Write-Host "Vite started (PID $($vite.Id)) -> http://127.0.0.1:5173  <- open in the browser"
} else {
    Write-Host "Frontend not created yet -- backend only."
}

Write-Host "Ctrl+C stops everything."
try {
    Wait-Process -Id ($jobs | ForEach-Object { $_.Id })
} finally {
    foreach ($job in $jobs) {
        if (-not $job.HasExited) { Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue }
    }
}
