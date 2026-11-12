# Sourced by the other dev scripts. Loads .env.local.example, then .env.local
# (overrides), then anything already exported in the shell (highest priority).
# Works with macOS bash 3.2 and Linux bash.
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

# ---------------------------------------------------------------- Python (>= 3.10 required)
py_ok() {  # $1 = interpreter; true if it runs and is >= 3.10
  [ -n "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}
py_version() { "$1" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null; }
find_python() {  # prints the first interpreter >= 3.10
  local c
  for c in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 \
           /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
           /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3.10 python3; do
    [ -z "$c" ] && continue
    if command -v "$c" >/dev/null 2>&1 && py_ok "$(command -v "$c")"; then command -v "$c"; return 0; fi
  done
  if command -v uv >/dev/null 2>&1; then
    c="$(uv python find '>=3.10' 2>/dev/null)" && py_ok "$c" && { echo "$c"; return 0; }
  fi
  return 1
}
PY="$ROOT/.venv/bin/python"
py_ok "$PY" || PY=""
export PY

# ---------------------------------------------------------------- Java for HAPI (11, 17 or 21)
java_major() {  # prints the major version of $1, e.g. 17
  "$1" -version 2>&1 | sed -n 's/.*version "\([0-9][0-9]*\)[^"]*".*/\1/p' | head -1
}
java_supported() { case "$(java_major "$1")" in 11|17|21) return 0 ;; *) return 1 ;; esac; }
find_hapi_java() {
  local c v
  for c in "${HAPI_JAVA:-}" "${JAVA11:-}"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  for c in "$ROOT/.local/tools/jdk/bin/python" "$ROOT/.local/tools/jdk11/bin/python"; do
    if [ -x "$c" ]; then
      v="$("$c" -c 'import jdk4py; print(jdk4py.JAVA)' 2>/dev/null)" && [ -x "$v" ] && { echo "$v"; return 0; }
    fi
  done
  if [ -x /usr/libexec/java_home ]; then   # macOS
    for v in 17 21 11; do
      c="$(/usr/libexec/java_home -v "$v" 2>/dev/null)/bin/java"
      [ -x "$c" ] && java_supported "$c" && { echo "$c"; return 0; }
    done
  fi
  for c in /opt/homebrew/opt/openjdk@17/bin/java /opt/homebrew/opt/openjdk@21/bin/java /opt/homebrew/opt/openjdk@11/bin/java \
           /usr/local/opt/openjdk@17/bin/java /usr/local/opt/openjdk@21/bin/java /usr/local/opt/openjdk@11/bin/java \
           "$(command -v java 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] && java_supported "$c" && { echo "$c"; return 0; }
  done
  return 1
}
HAPI_JAVA="$(find_hapi_java || true)"
export HAPI_JAVA

RUN_DIR="$ROOT/.local/run"
LOG_DIR="$ROOT/.local/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"
