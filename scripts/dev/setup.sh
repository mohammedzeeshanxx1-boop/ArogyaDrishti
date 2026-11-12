#!/usr/bin/env bash
# One-time local setup (macOS or Linux, no Docker):
#   1. Python >= 3.10 virtualenv in .venv with the API requirements
#   2. Node >= 20.19 (22.12+ for the web tests) and the web packages
#   3. A Java 11/17/21 runtime for HAPI FHIR (installs a private Java 17 if none is found)
# Every step runs and reports PASS / FAIL with the exact fix; exits 1 if anything failed.
set -uo pipefail
. "$(dirname "$0")/env.sh"
cd "$ROOT"
JDK4PY_VERSION="17.0.9.2"   # private Java 17 runtime (wheels for macOS arm64/x86_64 and Linux)
fail=0
ok()  { printf "PASS  %s\n" "$1"; }
bad() { printf "FAIL  %s\n      fix: %s\n" "$1" "$2"; fail=1; }

# ---------------------------------------------------------------- 1. Python
BASE_PY="$(find_python || true)"
if [ -z "$BASE_PY" ]; then
  bad "python >= 3.10 not found (macOS ships 3.9, which FastAPI 0.162 and this code do not support)" \
      "brew install python@3.12   (or: curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.12), then rerun"
else
  if [ -d .venv ] && ! py_ok .venv/bin/python; then
    old="$(py_version .venv/bin/python || echo unknown)"
    mv .venv ".venv.python-$old.bak.$(date +%Y%m%d%H%M%S)"
    echo "info  moved incompatible .venv (Python $old) aside; creating a new one"
  fi
  [ -x .venv/bin/python ] || "$BASE_PY" -m venv .venv
  if .venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1 \
     && .venv/bin/python -m pip install -q -r apps/api/requirements-dev.txt \
     && .venv/bin/python -c 'import fastapi, uvicorn, httpx, pydantic, yaml, websockets'; then
    ok "python $(py_version .venv/bin/python) venv (.venv): fastapi $(.venv/bin/python -c 'import fastapi; print(fastapi.__version__)'), pydantic $(.venv/bin/python -c 'import pydantic; print(pydantic.VERSION)')"
  else
    bad "pip install -r apps/api/requirements-dev.txt" "check the pip error above; the venv uses $(py_version .venv/bin/python)"
  fi
fi

# ---------------------------------------------------------------- 2. Node + web packages
if ! command -v node >/dev/null 2>&1; then
  bad "node not found" "brew install node@22   (Vite 8 needs Node ^20.19 or >= 22.12)"
else
  NODE_V="$(node -p 'process.versions.node')"
  node_ok="$(node -e 'const [a,b]=process.versions.node.split(".").map(Number); console.log((a===20&&b>=19)||(a===22&&b>=12)||a>=23?1:0)')"
  if [ "$node_ok" != 1 ]; then
    bad "node $NODE_V is too old (Vite 8 needs ^20.19 or >= 22.12; Vitest needs >= 22.12)" "brew install node@22 && brew link --overwrite node@22"
  elif npm --prefix apps/web ci --no-audit --no-fund >/dev/null 2>"$LOG_DIR/npm-ci.log" && [ -f apps/web/node_modules/vite/package.json ]; then
    ok "node $NODE_V, web packages installed (vite $(node -p 'require("./apps/web/node_modules/vite/package.json").version'))"
    case "$NODE_V" in 20.*) echo "warn  node $NODE_V runs the app; the web unit tests (Vitest) need >= 22.12" ;; esac
  else
    bad "npm ci in apps/web (see .local/logs/npm-ci.log)" "rm -rf apps/web/node_modules && npm --prefix apps/web ci"
  fi
fi

# ---------------------------------------------------------------- 3. Java for HAPI
if [ -z "$HAPI_JAVA" ] && [ -n "$BASE_PY" ]; then
  echo "info  no Java 11/17/21 found; installing a private Java $JDK4PY_VERSION runtime into .local/tools/jdk (PyPI jdk4py)"
  rm -rf .local/tools/jdk
  "$BASE_PY" -m venv .local/tools/jdk && .local/tools/jdk/bin/python -m pip install -q "jdk4py==$JDK4PY_VERSION"
  HAPI_JAVA="$(find_hapi_java || true)"
fi
if [ -n "$HAPI_JAVA" ]; then
  ok "java $(java_major "$HAPI_JAVA") for HAPI: $HAPI_JAVA"
else
  bad "no Java 11/17/21 runtime for HAPI" "brew install openjdk@17   (or set HAPI_JAVA=/path/to/java in .env.local)"
fi

# ---------------------------------------------------------------- tools used by HAPI setup
for t in curl unzip zip; do command -v "$t" >/dev/null 2>&1 || bad "$t not found" "install $t"; done
command -v java >/dev/null 2>&1 || echo "info  no 'java' on PATH: Synthea (scripts/dev/seed.sh) will use HAPI's Java via JAVA=$HAPI_JAVA"

echo
if [ $fail -eq 0 ]; then echo "SETUP OK. Next: scripts/dev/up.sh"; else echo "SETUP INCOMPLETE: fix the FAIL lines above and rerun scripts/dev/setup.sh"; fi
exit $fail
