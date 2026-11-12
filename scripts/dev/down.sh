#!/usr/bin/env bash
# Stop the processes started by up.sh. Data in .local/ is kept.
. "$(dirname "$0")/env.sh"
for name in web api hapi; do
  f="$RUN_DIR/$name.pid"
  [ -f "$f" ] || continue
  pid=$(cat "$f")
  if kill -0 "$pid" 2>/dev/null; then
    pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    echo "[down] stopped $name (pid $pid)"
  fi
  rm -f "$f"
done
