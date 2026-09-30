<#
.SYNOPSIS
    Links bridge/ as a FreeCAD addon (directory junction, not a copy).

.DESCRIPTION
    The target path is queried from FreeCAD at RUNTIME
    (FreeCAD.getUserAppDataDir()), not guessed. FreeCAD 1.1 uses
    versioned user directories -- "v1-1" with a hyphen. An addon in the
    unversioned path is invisible to FreeCAD 1.1.

    Alternative without linking, good for trying things out:
        & "<FreeCAD>\bin\freecad.exe" -M "<repo>\bridge"

.PARAMETER FreeCadPython
    Path to FreeCAD's python.exe. Otherwise searched for in the usual locations.

.PARAMETER Force
    Remove an existing target (only if it is a link, never a copy).
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
    throw "bridge/package.xml not found under $source"
}

# -- Find FreeCAD's Python --------------------------------------------
if (-not $FreeCadPython) {
    $candidates = @(
        "D:\Program Files\FreeCAD 1.1\bin\python.exe",
        "$env:ProgramFiles\FreeCAD 1.1\bin\python.exe",
        "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\python.exe"
    )
    $FreeCadPython = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $FreeCadPython) {
    throw "FreeCAD's python.exe not found. Specify it with -FreeCadPython <path>."
}
Write-Host "FreeCAD-Python: $FreeCadPython"

# -- Ask FreeCAD for the target directory ------------------------------
$env:PYTHONNOUSERSITE = '1'
$modDir = & $FreeCadPython -c "import FreeCAD, os; print(os.path.join(FreeCAD.getUserAppDataDir(), 'Mod'))"
if ($LASTEXITCODE -ne 0 -or -not $modDir) {
    throw "Could not ask FreeCAD for its user directory."
}
$modDir = $modDir.Trim()
Write-Host "Mod directory: $modDir"

if (-not (Test-Path $modDir)) {
    New-Item -ItemType Directory -Force -Path $modDir | Out-Null
}

$target = Join-Path $modDir $linkName

# -- Handle an existing target ----------------------------------------
if (Test-Path $target) {
    $item = Get-Item $target -Force
    $isLink = $item.Attributes -band [IO.FileAttributes]::ReparsePoint

    if (-not $isLink) {
        throw @"
$target exists and is a real COPY, not a link.
This is dangerous: you would be editing a dead copy.
Please check and delete it manually, then run this script again.
"@
    }
    if (-not $Force) {
        $current = @($item.Target)[0]
        if ($current -and ((Resolve-Path $current -ErrorAction SilentlyContinue).Path -ne (Resolve-Path $source).Path)) {
            Write-Host "Link points to a DIFFERENT repo: $current" -ForegroundColor Yellow
            Write-Host "FreeCAD will then load the bridge from there. Use -Force to redirect it to this repo."
        } else {
            Write-Host "Link already exists -> $current"
        }
        exit 0
    }
    Remove-Item $target -Force
    Write-Host "Removed old link."
}

New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Host ""
Write-Host "Linked: $target -> $source" -ForegroundColor Green
Write-Host "Restart FreeCAD, then select the 'SysML-CAD Bridge' workbench."
