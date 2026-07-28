.PHONY: bootstrap start stop status check adapter evidence import-workflows export-workflows

bootstrap:
	./scripts/bootstrap.sh

start:
	./scripts/start.sh

stop:
	./scripts/stop.sh

status:
	./scripts/status.sh

check:
	./scripts/check.sh

adapter:
	cd adapter && python3 -m codex_adapter --config config.json

evidence:
	@test -n "$(RUN)" || (echo "Usage: make evidence RUN=<run-id>" >&2; exit 2)
	./scripts/promote-evidence.sh "$(RUN)"

import-workflows:
	./scripts/import-workflows.sh

export-workflows:
	./scripts/export-workflows.sh
