<#
.SYNOPSIS
    Einrichtung von Null: Abhaengigkeiten, Oberflaeche bauen, Addon verlinken, Diagnose.

.DESCRIPTION
    Nach einem frischen "git clone" genuegt dieses eine Skript. Es ist
    wiederholbar: ein zweiter Lauf aktualisiert nur, was sich geaendert hat
    (etwa nach einem "git pull").

    Voraussetzungen: FreeCAD 1.1, uv, node (22 LTS), pnpm >= 10 (sonst
    uebernimmt corepack, das mit node kommt).

.PARAMETER FreeCadPython
    Pfad zu FreeCADs python.exe, falls nicht am ueblichen Ort.

.PARAMETER SkipLink
    Addon nicht nach FreeCADs Mod-Verzeichnis verlinken (etwa fuer eine
    zweite Arbeitskopie, waehrend FreeCAD die erste benutzt).
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


Step "Werkzeuge"
$missing = @()
foreach ($tool in @(
        @{ Name = 'uv'; Hint = 'https://docs.astral.sh/uv/  (winget install astral-sh.uv)' },
        @{ Name = 'node'; Hint = 'https://nodejs.org  (Node 22 LTS)' })) {
    $found = Get-Command $tool.Name -ErrorAction SilentlyContinue
    if ($found) { Write-Host ("  {0,-5} {1}" -f $tool.Name, $found.Source) }
    else { $missing += "  $($tool.Name) fehlt -> $($tool.Hint)" }
}
if ($missing) {
    $missing | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "Bitte die fehlenden Werkzeuge installieren und das Skript erneut starten."
}
$pnpm = @(Get-PnpmCommand)
Write-Host "  pnpm  $($pnpm -join ' ')"

Step "Backend: Python-Umgebung (uv sync)"
Invoke-Checked (Join-Path $repo 'backend') @('uv', 'sync')

Step "Frontend: Abhaengigkeiten (pnpm install)"
Invoke-Pnpm (Join-Path $repo 'frontend') @('install', '--frozen-lockfile')

Step "Frontend: Oberflaeche bauen (pnpm build)"
Invoke-Pnpm (Join-Path $repo 'frontend') @('build')

if ($SkipLink) {
    Step "Addon verlinken: uebersprungen (-SkipLink)"
} else {
    Step "Addon nach FreeCAD verlinken"
    $linkArgs = @{}
    if ($FreeCadPython) { $linkArgs.FreeCadPython = $FreeCadPython }
    & (Join-Path $PSScriptRoot 'link-addon.ps1') @linkArgs
}

Step "Diagnose"
Invoke-Checked (Join-Path $repo 'backend') @('uv', 'run', 'python', '../scripts/doctor.py')

Write-Host ""
Write-Host "Fertig." -ForegroundColor Green
Write-Host "  1. FreeCAD starten, Workbench 'SysML-CAD Bruecke' waehlen, Bruecke starten"
Write-Host "  2. scripts\start.ps1     -> http://127.0.0.1:8000"
Write-Host "     (Entwicklung mit Hot-Reload: scripts\dev.ps1 -> http://127.0.0.1:5173)"
