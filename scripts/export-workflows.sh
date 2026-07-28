#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

export_dir=".runtime/local-files/workflow-export"
mkdir -p "$export_dir"
docker exec local-n8n n8n export:workflow \
  --all \
  --separate \
  --output=/files/workflow-export

echo "Exported workflows to $export_dir"
echo "Review them before replacing version-controlled files in workflows/."

