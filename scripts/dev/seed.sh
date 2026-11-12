#!/usr/bin/env bash
# Generate (or reuse) the pinned Synthea cohort and load it into the local HAPI.
# Usage: scripts/dev/seed.sh [all|fetch|generate|select|import|verify]   (default: all)
set -euo pipefail
. "$(dirname "$0")/env.sh"
exec "$PY" "$ROOT/services/synthea/pipeline.py" "${1:-all}" --fhir-base "$FHIR_BASE_URL"
