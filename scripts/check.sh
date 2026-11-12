#!/usr/bin/env bash
# Runs every offline check for the current checkpoint. Exits non-zero on any failure.
# Usage: scripts/check.sh        (expects python3 and npm on PATH)
set -uo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
fail=0
step() {
  echo
  echo "=== $1 ==="
  shift
  if "$@"; then echo "--- PASS"; else echo "--- FAIL"; fail=1; fi
}

step "api: pytest" bash -c "cd apps/api && $PY -m pytest -q"
step "repo: scaffold + compose contract tests" "$PY" -m pytest -q tests
step "web: typecheck" npm --prefix apps/web run --silent typecheck
step "web: unit tests" npm --prefix apps/web run --silent test
step "web: production build" npm --prefix apps/web run --silent build

if command -v docker >/dev/null 2>&1; then
  step "compose: config validates" docker compose --env-file .env.example config --quiet
else
  echo; echo "=== compose: config validates ==="; echo "--- SKIPPED (docker not installed)"
fi

echo
if [ "$fail" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED"; fi
exit "$fail"
