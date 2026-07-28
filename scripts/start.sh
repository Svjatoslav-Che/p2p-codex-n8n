#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p .runtime/n8n .runtime/local-files .runtime/logs
docker compose up -d n8n

echo "n8n:     http://127.0.0.1:5678"
echo "Optional adapter: make adapter"
