# Gemeinsame Helfer der Shell-Skripte (per "source" eingebunden).

# Das user-site schattet FreeCADs gebuendelte Pakete.
export PYTHONNOUSERSITE=1
# Zeigt OPENSSL_CONF auf eine fehlende Datei, brechen node und pnpm ab.
if [ -n "${OPENSSL_CONF:-}" ] && [ ! -f "$OPENSSL_CONF" ]; then unset OPENSSL_CONF; fi
# corepack soll die in package.json festgelegte pnpm-Version ohne Rueckfrage holen.
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

# pnpm >= 10, passend zum Lockfile (v9). Ein aelteres pnpm wuerde das Lockfile
# still neu aufloesen -- dann nimmt corepack genau die Version aus "packageManager".
pnpm_cmd() {
  local major=0
  if command -v pnpm >/dev/null 2>&1; then
    major="$(pnpm --version 2>/dev/null | head -1 | cut -d. -f1)"
    case "$major" in ''|*[!0-9]*) major=0 ;; esac
  fi
  if [ "$major" -ge 10 ]; then
    pnpm "$@"
  elif command -v corepack >/dev/null 2>&1; then
    corepack pnpm "$@"
  else
    echo "pnpm >= 10 wird gebraucht (gefunden: $major). Installieren: npm install -g pnpm@10" >&2
    return 1
  fi
}
