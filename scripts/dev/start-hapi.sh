#!/usr/bin/env bash
# Foreground: HAPI FHIR R4 (native Java) on http://localhost:$HAPI_PORT/baseR4,
# data persisted in $HAPI_DATA_DIR (H2 file database).
set -euo pipefail
. "$(dirname "$0")/env.sh"
if [ -z "${JAVA11:-}" ]; then
  echo "[hapi] BLOCKED: no Java 11 runtime. Run scripts/dev/setup.sh or set JAVA11=/path/to/java11/bin/java" >&2
  exit 2
fi
export HAPI_PORT HAPI_LOCAL_WORK JAVA11
exec "$ROOT/infra/hapi-local/run.sh" "$HAPI_DATA_DIR"
