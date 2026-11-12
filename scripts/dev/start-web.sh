#!/usr/bin/env bash
# Foreground: Vite dev server on http://localhost:$WEB_PORT, proxying /api and /ws to $VITE_DEV_API_TARGET.
set -euo pipefail
. "$(dirname "$0")/env.sh"
cd "$ROOT/apps/web"
exec npx vite --port "$WEB_PORT" --strictPort
