#!/usr/bin/env bash
# Local HAPI FHIR R4 server for development without Docker (macOS or Linux).
#
# Runs the official HAPI FHIR 5.7.0 CLI `run-server` (a real HAPI JPA server; on-disk H2 database).
# The CLI's bundled Jandex cannot index 10 Guava classes, so a copy of the jar is patched once by a
# pure-Python tool that removes only type-use annotation attributes from those classes (no JDK needed).
# Verified on Java 11, 17 and 21.
#
# Needs: curl, unzip, zip, python3, and HAPI_JAVA=/path/to/java (11, 17 or 21).
# Usage: infra/hapi-local/run.sh [data-dir]      # serves http://localhost:${HAPI_PORT:-8090}/baseR4
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${HAPI_LOCAL_WORK:-$HERE/.work}"
DATA="${1:-$WORK/data}"
PORT="${HAPI_PORT:-8090}"
JAVA_BIN="${HAPI_JAVA:-${JAVA11:-java}}"
PYTHON_BIN="${PY:-python3}"
ZIP_URL="https://github.com/hapifhir/hapi-fhir/releases/download/v5.7.0/hapi-fhir-5.7.0-cli.zip"
ZIP_SHA256="e651aed72056a31045fadbc1dcb4d9b2d125a71bff8a47820eff86531a6cb6bf"
JAR_SHA256="0e55550bae56c3be1a23f12ba77509a561634f8c63a04cbd1bd8e5f0cf2c95d5"

sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
check() { [ "$(sha256 "$2")" = "$1" ] || { echo "[hapi-local] SHA-256 mismatch for $2" >&2; exit 1; }; }

case "$("$JAVA_BIN" -version 2>&1 | sed -n 's/.*version "\([0-9][0-9]*\)[^"]*".*/\1/p' | head -1)" in
  11|17|21) ;;
  *) echo "[hapi-local] WARNING: $JAVA_BIN is not Java 11/17/21; HAPI 5.7 was verified only on those" >&2 ;;
esac

mkdir -p "$WORK" "$DATA"
cd "$WORK"
if [ ! -f hapi-fhir-cli.jar ]; then
  echo "[hapi-local] downloading official HAPI FHIR 5.7.0 CLI (about 530 MB, one time)"
  curl -fL --retry 3 -o cli.zip "$ZIP_URL"
  check "$ZIP_SHA256" cli.zip
  unzip -q -o cli.zip hapi-fhir-cli.jar && rm cli.zip
fi
check "$JAR_SHA256" hapi-fhir-cli.jar

if [ ! -f hapi-fhir-cli-patched.jar ]; then
  echo "[hapi-local] patching 10 Guava classes (type-use annotations only)"
  rm -rf patch-classes && mkdir patch-classes
  "$PYTHON_BIN" "$HERE/strip_type_annotations.py" hapi-fhir-cli.jar "$HERE/patch-classes.txt" patch-classes
  cp hapi-fhir-cli.jar hapi-fhir-cli-patched.jar.tmp
  (cd patch-classes && zip -q ../hapi-fhir-cli-patched.jar.tmp $(cat "$HERE/patch-classes.txt"))
  mv hapi-fhir-cli-patched.jar.tmp hapi-fhir-cli-patched.jar
fi

cd "$DATA"
echo "[hapi-local] starting HAPI FHIR R4 on http://localhost:$PORT/baseR4 (java: $JAVA_BIN, data: $DATA)"
exec "$JAVA_BIN" -Xmx3g -jar "$WORK/hapi-fhir-cli-patched.jar" run-server -v r4 -p "$PORT" --reuse-search-results-milliseconds off
