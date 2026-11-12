#!/usr/bin/env bash
# Health check for the localhost stack. Prints PASS / FAIL / BLOCKED per check; exits 1 on any FAIL.
# A check is BLOCKED (not FAIL) when the thing it depends on is not running.
set -uo pipefail
. "$(dirname "$0")/env.sh"
PY="${PY:-python3}"
API="http://localhost:$API_PORT"
WEB="http://localhost:$WEB_PORT"
fail=0
blocked=0
report() { printf "%-8s %s\n" "$1" "$2"; [ "$1" = FAIL ] && fail=1; [ "$1" = BLOCKED ] && blocked=$((blocked+1)); return 0; }
up() { curl -fs -o /dev/null --max-time 5 "$1"; }

# HAPI
if up "$FHIR_BASE_URL/metadata"; then
  v=$(curl -fs --max-time 10 -H 'Accept: application/fhir+json' "$FHIR_BASE_URL/metadata" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("fhirVersion",""), d.get("software",{}).get("name",""), d.get("software",{}).get("version",""))')
  case "$v" in 4.0*) report PASS "hapi   $FHIR_BASE_URL/metadata -> FHIR $v" ;; *) report FAIL "hapi   not R4: $v" ;; esac
  n=$(curl -fs --max-time 20 "$FHIR_BASE_URL/Patient?identifier=https://github.com/synthetichealth/synthea%7C&_summary=count" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("total",0))')
  if [ "${n:-0}" -ge 5 ]; then report PASS "hapi   $n Synthea patients stored"; else report BLOCKED "hapi   only ${n:-0} Synthea patients; run scripts/dev/seed.sh"; fi
else
  report BLOCKED "hapi   not reachable at $FHIR_BASE_URL (scripts/dev/up.sh hapi)"
fi

# API
if up "$API/health"; then
  report PASS "api    $API/health"
  s=$(curl -fs --max-time 15 "$API/api/v1/status")
  echo "$s" | "$PY" -c 'import json,sys; s=json.load(sys.stdin)["services"]; sys.exit(0 if s["eventStore"]["status"]=="ok" else 1)' \
    && report PASS "api    event store (SQLite $APP_SQLITE_PATH)" || report FAIL "api    event store"
  echo "$s" | "$PY" -c 'import json,sys; f=json.load(sys.stdin)["services"]["fhir"]; sys.exit(0 if f["status"]=="ok" and f.get("isR4") else 1)' \
    && report PASS "api    sees HAPI as R4" || report BLOCKED "api    cannot reach HAPI at its FHIR_BASE_URL"
else
  report BLOCKED "api    not reachable at $API (scripts/dev/up.sh api)"
fi

# Web
if up "$WEB/"; then
  curl -fs "$WEB/" | grep -q "Arogya Drishti" && report PASS "web    $WEB/ serves the app" || report FAIL "web    page missing title"
  curl -fs "$WEB/api/v1/meta" | grep -q "Not for medical diagnosis" && report PASS "web    proxies /api to $VITE_DEV_API_TARGET" || report FAIL "web    /api proxy"
  "$PY" - "$WEB" <<'E' && report PASS "web    WebSocket /ws/heartbeat via proxy" || report FAIL "web    WebSocket proxy"
import asyncio, sys
import websockets
async def main():
    async with websockets.connect(sys.argv[1].replace("http", "ws", 1) + "/ws/heartbeat", open_timeout=5) as ws:
        assert '"hello"' in await ws.recv()
        await ws.send("ping")
        assert '"pong"' in await ws.recv()
asyncio.run(main())
E
else
  report BLOCKED "web    not reachable at $WEB (scripts/dev/up.sh web)"
fi

[ $fail -eq 0 ] && echo "HEALTH: no failures, $blocked blocked" || echo "HEALTH: FAILURES ($blocked blocked)"
exit $fail
