# Sourced by the other dev scripts. Loads .env.local.example, then .env.local
# (overrides), then anything already exported in the shell (highest priority).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ROOT

_saved_env="$(export -p)"
set -a
# shellcheck disable=SC1091
. "$ROOT/.env.local.example"
[ -f "$ROOT/.env.local" ] && . "$ROOT/.env.local"
set +a
eval "$_saved_env"   # values exported by the caller win
unset _saved_env

abs() { case "$1" in /*) echo "$1" ;; *) echo "$ROOT/$1" ;; esac; }
export APP_SQLITE_PATH="$(abs "$APP_SQLITE_PATH")"
export HAPI_DATA_DIR="$(abs "$HAPI_DATA_DIR")"
export HAPI_LOCAL_WORK="$(abs "$HAPI_LOCAL_WORK")"

if [ -z "${JAVA11:-}" ] && [ -x "$ROOT/.local/tools/jdk11/bin/python" ]; then
  JAVA11="$("$ROOT/.local/tools/jdk11/bin/python" -c 'import jdk4py; print(jdk4py.JAVA)' 2>/dev/null || true)"
fi
export JAVA11

PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
export PY

RUN_DIR="$ROOT/.local/run"
LOG_DIR="$ROOT/.local/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"
