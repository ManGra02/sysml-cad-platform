# Shared helpers for the shell scripts (included via "source").

# The user site shadows FreeCAD's bundled packages.
export PYTHONNOUSERSITE=1
# If OPENSSL_CONF points to a missing file, node and pnpm abort.
if [ -n "${OPENSSL_CONF:-}" ] && [ ! -f "$OPENSSL_CONF" ]; then unset OPENSSL_CONF; fi
# corepack should fetch the pnpm version pinned in package.json without prompting.
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

# pnpm >= 10, matching the lockfile (v9). An older pnpm would silently re-resolve the
# lockfile -- in that case corepack uses exactly the version from "packageManager".
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
    echo "pnpm >= 10 is required (found: $major). Install: npm install -g pnpm@10" >&2
    return 1
  fi
}
