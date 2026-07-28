#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

for command_name in docker python3 curl openssl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker Desktop is not available" >&2
  exit 1
fi

mkdir -p .runtime/n8n .runtime/local-files .runtime/logs

if [ ! -f .env ]; then
  umask 077
  encryption_key="$(openssl rand -hex 32)"
  printf 'N8N_ENCRYPTION_KEY=%s\n' "$encryption_key" > .env
  echo "Created local .env"
fi

docker compose config --quiet
(cd adapter && python3 -m unittest discover -s tests -v)
docker compose pull n8n

echo
echo "Bootstrap complete."
echo "Run: make start"

