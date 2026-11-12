#!/usr/bin/env bash
# Foreground: FastAPI on http://localhost:$API_PORT (auto-reload with RELOAD=1).
set -euo pipefail
. "$(dirname "$0")/env.sh"
mkdir -p "$(dirname "$APP_SQLITE_PATH")"
cd "$ROOT/apps/api"
echo "[api] FHIR_BASE_URL=$FHIR_BASE_URL  APP_SQLITE_PATH=$APP_SQLITE_PATH"
exec "$PY" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" ${RELOAD:+--reload}
