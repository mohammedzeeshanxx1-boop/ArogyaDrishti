#!/usr/bin/env bash
# Create the local Doctor Portal and Patient Portal accounts: one doctor and one account per synthetic patient.
# Passwords are random per account and stored only as PBKDF2 hashes in the SQLite event store. The plain
# passwords are printed once and written to .local/api/credentials.json (mode 600, gitignored, never committed).
# Re-running keeps existing accounts; --reset issues new passwords (and ends existing sessions).
# Usage: scripts/dev/accounts.sh [--reset]
set -euo pipefail
. "$(dirname "$0")/env.sh"
[ -n "$PY" ] || { echo "[accounts] BLOCKED: no Python >= 3.10 venv; run scripts/dev/setup.sh" >&2; exit 2; }
cd "$ROOT/apps/api"
exec "$PY" -m app.auth provision --db "$APP_SQLITE_PATH" --fhir-base "$FHIR_BASE_URL" "$@"
