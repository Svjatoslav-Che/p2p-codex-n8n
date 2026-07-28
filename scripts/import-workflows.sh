#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

for workflow in workflows/*.json; do
  workflow_name="$(basename "$workflow")"
  docker cp "$workflow" "local-n8n:/tmp/$workflow_name"
  docker exec local-n8n n8n import:workflow --input="/tmp/$workflow_name"
done

echo "Workflows imported as drafts. Publish the required workflows in n8n."

