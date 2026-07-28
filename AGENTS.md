# Automation Workbench rules

## Project boundary

- Keep all source, workflow definitions, scenario inputs, materials, reports
  and selected evidence inside this repository.
- Never write scenario artifacts elsewhere on the machine.
- Runtime state belongs under `.runtime/` and must remain untracked.
- Never commit `.env`, n8n credentials, cookies, browser profiles or secrets.
- Do not download Browserless or another bundled browser image. Browser work in
  Codex uses the in-app Browser; deterministic local fallback uses the Chrome
  already installed on the host.

## n8n

- n8n is the visual workflow and execution journal.
- Prefer workflow JSON in `workflows/` as the version-controlled source.
- Use the n8n CLI scripts for import/export. Use the UI only for publishing,
  visual editing and verification that cannot be done by the CLI.
- Bind n8n only to `127.0.0.1`.

## Website availability scenario

When asked to run the website availability scenario:

1. Read `scenarios/website-availability/sites.json` and
   `scenarios/website-availability/SCENARIO.md`.
2. Create exactly one run directory under
   `scenarios/website-availability/runs/`.
3. Check every configured health URL and record status, final URL, response
   time and error.
4. Use the Codex in-app Browser to open each `browser_url` and capture a PNG
   into the run's `snapshots/` directory.
5. Write `report.md` and `report.json` in the run directory root.
6. Set the gate to PASS only if every health check and screenshot succeeded.
7. POST `report.json` to the local n8n evidence gate described in
   `SCENARIO.md` and record its response in the report.
8. Start functional checks only after both the local result and n8n gate are
   PASS. Otherwise stop and report the
   exact failed sites.
9. Keep temporary browser tabs cleaned up; retain a useful result tab only
   when it helps the user.

## Evidence and Git

- Raw runs are intentionally ignored to keep clones compact.
- Copy only evidence explicitly selected for long-term retention into
  `evidence/<scenario>/<run-id>/`.
- Before committing, run `make check` and inspect `git status`.
