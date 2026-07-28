# Run prompt

Use this prompt in Codex from the `automation-workbench` project:

```text
Run the website availability scenario using
scenarios/website-availability/sites.json and follow AGENTS.md exactly.
Create one timestamped run folder, check every health URL, use the Codex
Browser for screenshots, write report.md and report.json, submit report.json
to the n8n evidence gate, and continue to functional checks only if both gates
pass.
```

Edit `sites.json` before the run. Do not put credentials in that file; login
data for a future functional scenario must remain in local ignored runtime or
be supplied through a secret store.
