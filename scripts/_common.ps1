# Gemeinsame Helfer der Windows-Skripte (per Dot-Sourcing eingebunden).

function Initialize-PlatformEnvironment {
    # Das user-site wird mit einem separat installierten Python geteilt und
    # schattet FreeCADs gebuendelte Pakete.
    $env:PYTHONNOUSERSITE = '1'
    # Zeigt OPENSSL_CONF auf eine fehlende Datei (z. B. von PostgreSQL),
    # brechen node und pnpm mit "OpenSSL configuration error" ab.
    if ($env:OPENSSL_CONF -and -not (Test-Path $env:OPENSSL_CONF)) { Remove-Item Env:OPENSSL_CONF }
    # corepack soll die in package.json festgelegte pnpm-Version ohne Rueckfrage holen.
    $env:COREPACK_ENABLE_DOWNLOAD_PROMPT = '0'
}

function Get-PnpmCommand {
    <#
        pnpm >= 10, passend zum Lockfile (v9). Ein aelteres pnpm wuerde das
        Lockfile nicht lesen koennen und es still neu aufloesen -- dann ist
        corepack der Ausweg: es nimmt genau die Version aus "packageManager".
    #>
    $major = 0
    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        $version = (& pnpm --version 2>$null | Select-Object -First 1)
        if ($version -match '^(\d+)\.') { $major = [int]$Matches[1] }
    }
    if ($major -ge 10) { return @('pnpm') }
    if (Get-Command corepack -ErrorAction SilentlyContinue) { return @('corepack', 'pnpm') }
    throw "pnpm >= 10 wird gebraucht (gefunden: $(if ($major) { $major } else { 'keins' })). Installieren: npm install -g pnpm@10"
}

function Invoke-Checked([string]$dir, [string[]]$command) {
    Push-Location $dir
    try {
        $exe = $command[0]
        $rest = @($command | Select-Object -Skip 1)
        & $exe @rest
        if ($LASTEXITCODE -ne 0) { throw "'$($command -join ' ')' ist fehlgeschlagen (Exit $LASTEXITCODE)." }
    } finally {
        Pop-Location
    }
}

function Invoke-Pnpm([string]$dir, [string[]]$arguments) {
    Invoke-Checked $dir (@(Get-PnpmCommand) + $arguments)
}
