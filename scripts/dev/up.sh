#!/usr/bin/env bash
# Start HAPI, API and web as background processes (logs in .local/logs, pids in .local/run),
# wait for each to answer, then run the health check.
# Usage: scripts/dev/up.sh [hapi] [api] [web]     (default: all three)
set -uo pipefail
. "$(dirname "$0")/env.sh"
want="${*:-hapi api web}"

# ---------------------------------------------------------------- preflight: fail fast with the fix
pre=0
need() { printf "BLOCKED  %s\n         fix: %s\n" "$1" "$2"; pre=1; }
case " $want " in *" api "*)
  if [ -z "$PY" ]; then need "api: no Python >= 3.10 venv (.venv)" "scripts/dev/setup.sh  (macOS: brew install python@3.12 first)"
  elif ! "$PY" -c 'import fastapi, uvicorn, httpx' 2>/dev/null; then need "api: packages missing in .venv" "scripts/dev/setup.sh"; fi ;;
esac
case " $want " in *" web "*)
  if ! command -v node >/dev/null 2>&1; then need "web: node not found" "brew install node@22"
  elif [ ! -f "$ROOT/apps/web/node_modules/vite/package.json" ]; then need "web: packages not installed (ERR_MODULE_NOT_FOUND)" "scripts/dev/setup.sh  (or npm --prefix apps/web ci)"
  elif [ "$(node -e 'const [a,b]=process.versions.node.split(".").map(Number); console.log((a===20&&b>=19)||(a===22&&b>=12)||a>=23?1:0)')" != 1 ]; then
    need "web: node $(node -p 'process.versions.node') too old for Vite 8" "brew install node@22"; fi ;;
esac
case " $want " in *" hapi "*)
  [ -n "$HAPI_JAVA" ] || need "hapi: no Java 11/17/21 runtime" "scripts/dev/setup.sh  (installs a private Java 17) or brew install openjdk@17" ;;
esac
[ $pre -eq 0 ] || { echo "Fix the BLOCKED items above, then rerun scripts/dev/up.sh"; exit 2; }

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
