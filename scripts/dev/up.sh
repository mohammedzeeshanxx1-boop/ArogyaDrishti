#!/usr/bin/env bash
# Start HAPI, API and web as background processes (logs in .local/logs, pids in .local/run),
# wait for each to answer, then run the health check.
# Usage: scripts/dev/up.sh [hapi] [api] [web]     (default: all three)
set -uo pipefail
. "$(dirname "$0")/env.sh"
want="${*:-hapi api web}"

running() { [ -f "$RUN_DIR/$1.pid" ] && kill -0 "$(cat "$RUN_DIR/$1.pid")" 2>/dev/null; }

start() {
  local name=$1 url=$2 timeout=$3
  if running "$name"; then echo "[up] $name already running (pid $(cat "$RUN_DIR/$name.pid"))"; return 0; fi
  nohup "$ROOT/scripts/dev/start-$name.sh" > "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$RUN_DIR/$name.pid"
  printf "[up] %s starting (pid %s, log .local/logs/%s.log) " "$name" "$!" "$name"
  for _ in $(seq 1 "$timeout"); do
    if curl -fs -o /dev/null "$url"; then echo "ready"; return 0; fi
    if ! running "$name"; then echo "EXITED"; tail -5 "$LOG_DIR/$name.log"; return 1; fi
    sleep 1; printf "."
  done
  echo "TIMEOUT"; return 1
}

rc=0
for s in $want; do
  case $s in
    hapi) start hapi "$FHIR_BASE_URL/metadata" 300 || rc=1 ;;
    api)  start api "http://localhost:$API_PORT/health" 60 || rc=1 ;;
    web)  start web "http://localhost:$WEB_PORT/" 60 || rc=1 ;;
  esac
done
"$ROOT/scripts/dev/health.sh" || rc=1
exit $rc
