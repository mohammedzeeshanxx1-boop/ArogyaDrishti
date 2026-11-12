#!/usr/bin/env bash
# One-time local setup: Python venv for the API, npm packages for the web app,
# and a Java 11 runtime for HAPI FHIR 5.7 (unless JAVA11 is already set).
# Synthea needs Java 11+ on PATH (`java`).
set -euo pipefail
. "$(dirname "$0")/env.sh"
cd "$ROOT"

echo "[setup] python venv (.venv) + API requirements"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q -r apps/api/requirements-dev.txt

echo "[setup] web packages"
npm --prefix apps/web ci --no-audit --no-fund

if [ -z "${JAVA11:-}" ]; then
  echo "[setup] Java 11 runtime for HAPI (PyPI package jdk4py==11.0.13.1 -> .local/tools/jdk11)"
  python3 -m venv .local/tools/jdk11
  .local/tools/jdk11/bin/pip install -q "jdk4py==11.0.13.1"
fi

echo "[setup] java for Synthea: $(java -version 2>&1 | grep -m1 version || echo 'NOT FOUND - install Java 11+')"
echo "[setup] done. Next: scripts/dev/up.sh"
