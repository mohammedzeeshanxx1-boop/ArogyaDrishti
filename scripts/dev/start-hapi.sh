#!/usr/bin/env bash
# Foreground: HAPI FHIR R4 (native Java 11/17/21) on http://localhost:$HAPI_PORT/baseR4,
# data persisted in $HAPI_DATA_DIR (H2 file database).
set -euo pipefail
. "$(dirname "$0")/env.sh"
if [ -z "${HAPI_JAVA:-}" ]; then
  echo "[hapi] BLOCKED: no Java 11/17/21 runtime. Run scripts/dev/setup.sh (installs a private Java 17)," >&2
  echo "       or: brew install openjdk@17, or set HAPI_JAVA=/path/to/java in .env.local" >&2
  exit 2
fi
export HAPI_PORT HAPI_LOCAL_WORK HAPI_JAVA
export PY="${PY:-python3}"
exec "$ROOT/infra/hapi-local/run.sh" "$HAPI_DATA_DIR"
