#!/usr/bin/env bash
# Generate (or reuse) the pinned Synthea cohort and load it into the local HAPI.
# Usage: scripts/dev/seed.sh [all|fetch|generate|select|import|verify]   (default: all)
set -euo pipefail
. "$(dirname "$0")/env.sh"
[ -n "$PY" ] || { echo "[seed] BLOCKED: no Python >= 3.10 venv; run scripts/dev/setup.sh" >&2; exit 2; }
# Synthea needs Java 11+; use HAPI's Java when there is no java on PATH.
export JAVA="${JAVA:-$(command -v java >/dev/null 2>&1 && command -v java || echo "$HAPI_JAVA")}"
exec "$PY" "$ROOT/services/synthea/pipeline.py" "${1:-all}" --fhir-base "$FHIR_BASE_URL"
