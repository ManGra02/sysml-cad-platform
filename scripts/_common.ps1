# Shared helpers for the Windows scripts (included via dot-sourcing).

function Initialize-PlatformEnvironment {
    # The user site is shared with a separately installed Python and
    # shadows FreeCAD's bundled packages.
    $env:PYTHONNOUSERSITE = '1'
    # If OPENSSL_CONF points to a missing file (e.g. from PostgreSQL),
    # node and pnpm abort with "OpenSSL configuration error".
    if ($env:OPENSSL_CONF -and -not (Test-Path $env:OPENSSL_CONF)) { Remove-Item Env:OPENSSL_CONF }
    # corepack should fetch the pnpm version pinned in package.json without prompting.
    $env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'
}

function Get-PnpmCommand {
    <#
        pnpm >= 10, matching the lockfile (v9). An older pnpm would not be able
        to read the lockfile and would silently re-resolve it -- in that case
        corepack is the way out: it uses exactly the version from "packageManager".
    #>
    $major = 0
    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        $version = (& pnpm --version 2>$null | Select-Object -First 1)
        if ($version -match '^(\d+)\.') { $major = [int]$Matches[1] }
    }
    if ($major -ge 10) { return @('pnpm') }
    if (Get-Command corepack -ErrorAction SilentlyContinue) { return @('corepack', 'pnpm') }
    throw "pnpm >= 10 is required (found: $(if ($major) { $major } else { 'none' })). Install: npm install -g pnpm@10"
}

function Invoke-Checked([string]$dir, [string[]]$command) {
    Push-Location $dir
    try {
        $exe = $command[0]
        $rest = @($command | Select-Object -Skip 1)
        & $exe @rest
        if ($LASTEXITCODE -ne 0) { throw "'$($command -join ' ')' failed (exit $LASTEXITCODE)." }
    } finally {
        Pop-Location
    }
}

function Invoke-Pnpm([string]$dir, [string[]]$arguments) {
    Invoke-Checked $dir (@(Get-PnpmCommand) + $arguments)
}
