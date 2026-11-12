#!/usr/bin/env bash
# Smoke test against a RUNNING stack (docker compose up -d). Exits non-zero on failure.
# HAPI can take a minute or more on first boot, so the FHIR check retries.
set -uo pipefail

WEB="${WEB_URL:-http://localhost:8080}"
API="${API_URL:-http://localhost:8000}"
HAPI="${HAPI_URL:-http://localhost:8090}"
fail=0
check() {
  if eval "$2"; then echo "PASS  $1"; else echo "FAIL  $1"; fail=1; fi
}

check "api /health" "curl -fsS $API/health | grep -q '\"ok\"'"
check "web serves index" "curl -fsS $WEB/ | grep -q 'Arogya Drishti'"
check "web proxies /api to api" "curl -fsS $WEB/api/v1/meta | grep -q 'Not for medical diagnosis'"

echo "waiting for HAPI FHIR (up to 300s)..."
ok=0
for _ in $(seq 1 60); do
  if curl -fsS -H 'Accept: application/fhir+json' "$HAPI/fhir/metadata" 2>/dev/null | grep -q '"fhirVersion"[[:space:]]*:[[:space:]]*"4\.0'; then ok=1; break; fi
  sleep 5
done
check "hapi /fhir/metadata declares FHIR 4.0.x (R4)" "[ $ok -eq 1 ]"
check "api sees hapi as R4" "curl -fsS $API/api/v1/status | grep -q '\"isR4\"[[:space:]]*:[[:space:]]*true'"

[ "$fail" -eq 0 ] && echo "SMOKE PASSED" || echo "SMOKE FAILED"
exit "$fail"
