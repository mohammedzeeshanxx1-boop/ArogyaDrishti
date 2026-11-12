#!/usr/bin/env bash
# Fallback HAPI FHIR R4 server for machines WITHOUT Docker Hub access.
#
# The supported path is `docker compose up` (official hapiproject/hapi image +
# PostgreSQL). This script exists because the C1 build environment could not
# pull container images. It runs the official HAPI FHIR 5.7.0 CLI `run-server`
# (a real HAPI JPA server; on-disk Derby database) and was used to produce the
# C1 evidence in CHECKPOINTS.md.
#
# Needs: curl, unzip, zip, a JDK >= 11 with javac (to build the patch tool) and
# a Java 11 runtime to run HAPI 5.7 (JAVA11=/path/to/java; Java 21 also fails).
#
# Usage: infra/hapi-local/run.sh [data-dir]      # serves http://localhost:8090/baseR4
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${HAPI_LOCAL_WORK:-$HERE/.work}"
DATA="${1:-$WORK/data}"
PORT="${HAPI_PORT:-8090}"
JAVA11="${JAVA11:-java}"
ZIP_URL="https://github.com/hapifhir/hapi-fhir/releases/download/v5.7.0/hapi-fhir-5.7.0-cli.zip"
ZIP_SHA256="e651aed72056a31045fadbc1dcb4d9b2d125a71bff8a47820eff86531a6cb6bf"
JAR_SHA256="0e55550bae56c3be1a23f12ba77509a561634f8c63a04cbd1bd8e5f0cf2c95d5"

mkdir -p "$WORK" "$DATA"
cd "$WORK"

if [ ! -f hapi-fhir-cli.jar ]; then
  echo "[hapi-local] downloading official HAPI FHIR 5.7.0 CLI"
  curl -fsSL -o cli.zip "$ZIP_URL"
  echo "$ZIP_SHA256  cli.zip" | sha256sum -c -
  unzip -q -o cli.zip hapi-fhir-cli.jar && rm cli.zip
fi
echo "$JAR_SHA256  hapi-fhir-cli.jar" | sha256sum -c -

if [ ! -f hapi-fhir-cli-patched.jar ]; then
  echo "[hapi-local] finding classes the bundled Jandex cannot index"
  javac --release 11 -cp hapi-fhir-cli.jar -d tools "$HERE/Scan.java" "$HERE/Strip.java"
  java -cp hapi-fhir-cli.jar:tools Scan hapi-fhir-cli.jar | tee scan-before.txt | tail -1
  grep '^BAD ' scan-before.txt | awk '{print $2}' > patch-list.txt
  rm -rf classes && mkdir classes
  (cd classes && unzip -q -o ../hapi-fhir-cli.jar $(cat ../patch-list.txt) && java -cp ../hapi-fhir-cli.jar:../tools Strip $(cat ../patch-list.txt))
  cp hapi-fhir-cli.jar hapi-fhir-cli-patched.jar
  (cd classes && zip -q ../hapi-fhir-cli-patched.jar $(cat ../patch-list.txt))
  java -cp hapi-fhir-cli.jar:tools Scan hapi-fhir-cli-patched.jar | tail -1 | tee scan-after.txt
  grep -q 'bad=0' scan-after.txt || { echo "[hapi-local] patch did not fix all classes"; exit 1; }
fi

"$JAVA11" -version 2>&1 | grep -q 'version "11' || echo "[hapi-local] WARNING: HAPI 5.7 was verified only on Java 11 (JAVA11=$JAVA11)"
cd "$DATA"
echo "[hapi-local] starting HAPI FHIR R4 on http://localhost:$PORT/baseR4 (data: $DATA)"
exec "$JAVA11" -Xmx3g -jar "$WORK/hapi-fhir-cli-patched.jar" run-server -v r4 -p "$PORT" --reuse-search-results-milliseconds off
