<#
.SYNOPSIS
    Setup from scratch: dependencies, UI build, addon link, diagnostics.

.DESCRIPTION
    After a fresh "git clone", this one script is all you need. It is
    repeatable: a second run only updates what has changed
    (e.g. after a "git pull").

    Prerequisites: FreeCAD 1.1, uv, node (22 LTS), pnpm >= 10 (otherwise
    corepack, which ships with node, takes over).

.PARAMETER FreeCadPython
    Path to FreeCAD's python.exe, if not in the usual location.

.PARAMETER SkipLink
    Don't link the addon into FreeCAD's Mod directory (e.g. for a
    second working copy while FreeCAD uses the first one).
#>
[CmdletBinding()]
param(
    [string]$FreeCadPython,
    [switch]$SkipLink
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot '_common.ps1')
Initialize-PlatformEnvironment

function Step([string]$title) {
    Write-Host ""
    Write-Host "== $title" -ForegroundColor Cyan
}


Step "Tools"
$missing = @()
foreach ($tool in @(
        @{ Name = 'uv'; Hint = 'https://docs.astral.sh/uv/  (winget install astral-sh.uv)' },
        @{ Name = 'node'; Hint = 'https://nodejs.org  (Node 22 LTS)' })) {
    $found = Get-Command $tool.Name -ErrorAction SilentlyContinue
    if ($found) { Write-Host ("  {0,-5} {1}" -f $tool.Name, $found.Source) }
    else { $missing += "  $($tool.Name) missing -> $($tool.Hint)" }
}
if ($missing) {
    $missing | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "Please install the missing tools and run the script again."
}
$pnpm = @(Get-PnpmCommand)
Write-Host "  pnpm  $($pnpm -join ' ')"

Step "Backend: Python environment (uv sync)"
Invoke-Checked (Join-Path $repo 'backend') @('uv', 'sync')

Step "Frontend: dependencies (pnpm install)"
Invoke-Pnpm (Join-Path $repo 'frontend') @('install', '--frozen-lockfile')

Step "Frontend: build UI (pnpm build)"
Invoke-Pnpm (Join-Path $repo 'frontend') @('build')

if ($SkipLink) {
    Step "Link addon: skipped (-SkipLink)"
} else {
    Step "Link addon into FreeCAD"
    $linkArgs = @{}
    if ($FreeCadPython) { $linkArgs.FreeCadPython = $FreeCadPython }
    & (Join-Path $PSScriptRoot 'link-addon.ps1') @linkArgs
}

Step "Diagnostics"
Invoke-Checked (Join-Path $repo 'backend') @('uv', 'run', 'python', '../scripts/doctor.py')

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  1. Start FreeCAD, select the 'SysML-CAD Bridge' workbench, start the bridge"
Write-Host "  2. scripts\start.ps1     -> http://127.0.0.1:8000"
Write-Host "     (development with hot reload: scripts\dev.ps1 -> http://127.0.0.1:5173)"
