#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

python3 -m json.tool scenarios/website-availability/sites.json >/dev/null
for workflow in workflows/*.json; do
  python3 -m json.tool "$workflow" >/dev/null
done
(cd adapter && python3 -m compileall -q codex_adapter tests)
(cd adapter && python3 -m unittest discover -s tests -v)
docker compose config --quiet

echo "All project checks passed."
