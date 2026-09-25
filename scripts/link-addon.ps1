<#
.SYNOPSIS
    Verlinkt bridge/ als FreeCAD-Addon (Directory Junction, keine Kopie).

.DESCRIPTION
    Der Zielpfad wird zur LAUFZEIT von FreeCAD erfragt
    (FreeCAD.getUserAppDataDir()), nicht geraten. FreeCAD 1.1 nutzt
    versionierte Benutzerverzeichnisse -- "v1-1" mit Bindestrich. Ein Addon im
    unversionierten Pfad ist fuer FreeCAD 1.1 unsichtbar.

    Alternative ohne Verlinkung, gut zum Ausprobieren:
        & "<FreeCAD>\bin\freecad.exe" -M "<repo>\bridge"

.PARAMETER FreeCadPython
    Pfad zu FreeCADs python.exe. Wird sonst an den ueblichen Stellen gesucht.

.PARAMETER Force
    Ein vorhandenes Ziel entfernen (nur wenn es ein Link ist, nie eine Kopie).
#>
[CmdletBinding()]
param(
    [string]$FreeCadPython,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repo 'bridge'
$linkName = 'SysMLCadPlatform'

if (-not (Test-Path (Join-Path $source 'package.xml'))) {
    throw "bridge/package.xml nicht gefunden unter $source"
}

# -- FreeCADs Python finden --------------------------------------------
if (-not $FreeCadPython) {
    $candidates = @(
        "D:\Program Files\FreeCAD 1.1\bin\python.exe",
        "$env:ProgramFiles\FreeCAD 1.1\bin\python.exe",
        "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe"
    )
    $FreeCadPython = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $FreeCadPython) {
    throw "FreeCADs python.exe nicht gefunden. Mit -FreeCadPython <Pfad> angeben."
}
Write-Host "FreeCAD-Python: $FreeCadPython"

# -- Zielverzeichnis von FreeCAD erfragen ------------------------------
$env:PYTHONNOUSERSITE = '1'
$modDir = & $FreeCadPython -c "import FreeCAD, os; print(os.path.join(FreeCAD.getUserAppDataDir(), 'Mod'))"
if ($LASTEXITCODE -ne 0 -or -not $modDir) {
    throw "FreeCAD konnte nicht nach seinem Benutzerverzeichnis gefragt werden."
}
$modDir = $modDir.Trim()
Write-Host "Mod-Verzeichnis: $modDir"

if (-not (Test-Path $modDir)) {
    New-Item -ItemType Directory -Force -Path $modDir | Out-Null
}

$target = Join-Path $modDir $linkName

# -- Bestehendes Ziel behandeln ----------------------------------------
if (Test-Path $target) {
    $item = Get-Item $target -Force
    $isLink = $item.Attributes -band [IO.FileAttributes]::ReparsePoint

    if (-not $isLink) {
        throw @"
$target existiert und ist eine echte KOPIE, kein Link.
Das ist gefaehrlich: ihr wuerdet eine tote Kopie bearbeiten.
Bitte manuell pruefen und loeschen, dann dieses Skript erneut ausfuehren.
"@
    }
    if (-not $Force) {
        Write-Host "Link existiert bereits -> $($item.Target)"
        Write-Host "Mit -Force neu anlegen."
        exit 0
    }
    Remove-Item $target -Force
    Write-Host "Alten Link entfernt."
}

New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Host ""
Write-Host "Verlinkt: $target -> $source" -ForegroundColor Green
Write-Host "FreeCAD neu starten, dann Workbench 'SysML-CAD Bruecke' waehlen."
