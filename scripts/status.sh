#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

docker compose ps

echo
if curl --fail --silent --max-time 5 http://127.0.0.1:5678/healthz; then
  echo
  echo "n8n health: OK"
else
  echo "n8n health: unavailable"
fi

if curl --fail --silent --max-time 10 http://127.0.0.1:8765/health \
  > .runtime/adapter-health.json; then
  python3 -m json.tool .runtime/adapter-health.json
else
  echo "adapter health: not running (optional)"
fi
