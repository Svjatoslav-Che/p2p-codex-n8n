#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

run_id="${1:-}"
if [ -z "$run_id" ] || [ "$run_id" != "$(basename "$run_id")" ]; then
  echo "Usage: $0 <run-id>" >&2
  exit 2
fi

source_dir="scenarios/website-availability/runs/$run_id"
target_dir="evidence/website-availability/$run_id"

if [ ! -d "$source_dir" ]; then
  echo "Run not found: $source_dir" >&2
  exit 1
fi
if [ -e "$target_dir" ]; then
  echo "Evidence already exists; refusing to overwrite: $target_dir" >&2
  exit 1
fi

mkdir -p "$(dirname "$target_dir")"
cp -R "$source_dir" "$target_dir"

echo "Promoted evidence to $target_dir"
echo "Review it, then use: git add '$target_dir'"
