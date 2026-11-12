#!/usr/bin/env bash
# DEVELOPMENT ONLY: stream SIMULATED wearable readings for one patient through the normal
# ingestion endpoint (POST /api/fhir/Observation -> HAPI -> risk assessment -> alerts -> dashboard).
# Every Observation is labelled "Arogya Drishti virtual wearable (simulated)"; no physical device is involved.
#
# Usage: scripts/dev/simulate.sh <patient-id> [stable|deterioration] [steps] [interval-seconds]
#   patient ids: shown in .local/api/credentials.json (patientId) after scripts/dev/accounts.sh
set -euo pipefail
. "$(dirname "$0")/env.sh"
[ $# -ge 1 ] || { sed -n '2,8p' "$0"; exit 2; }
[ -n "$PY" ] || { echo "[simulate] BLOCKED: no Python >= 3.10 venv; run scripts/dev/setup.sh" >&2; exit 2; }
cd "$ROOT/apps/api"
CREDS="$(dirname "$APP_SQLITE_PATH")/credentials.json"
[ -f "$CREDS" ] || { echo "[simulate] BLOCKED: no accounts yet; run scripts/dev/accounts.sh" >&2; exit 2; }
export AROGYA_USER=doctor
AROGYA_PASSWORD="$("$PY" -c 'import json,sys; print(next(a["password"] for a in json.load(open(sys.argv[1]))["accounts"] if a["role"]=="doctor"))' "$CREDS")"
export AROGYA_PASSWORD
exec "$PY" -m app.simulator --patient "$1" --scenario "${2:-deterioration}" --steps "${3:-20}" --interval "${4:-2}" \
  --api "http://localhost:$API_PORT"
