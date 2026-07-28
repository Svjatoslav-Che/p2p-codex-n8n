# Local Codex adapter

Small dependency-free HTTP service for the local chain:

```text
n8n -> HTTP -> codex-adapter -> Codex CLI -> allowlisted local repository
```

The service binds only to `127.0.0.1`. It never invokes a shell and exposes
only the Codex `read-only` and `workspace-write` sandboxes. Codex user config
is ignored for adapter runs so unrelated global plugins, MCP servers, hooks,
or sandbox defaults cannot silently change the HTTP runner.

## Requirements

- Python 3.10+
- A working Codex CLI session (`codex login status`)
- n8n running locally

The adapter discovers a working Codex CLI from `PATH` or the standard Codex
desktop application locations. Set `codex_bin` in a local ignored config only
when automatic discovery is insufficient.

## Configure

Review `config.json` before starting. Every accepted `repo_path` must exactly
match one of the real paths in `allowed_repos`. When exactly one repository is
allowlisted, callers may omit `repo_path`; the adapter selects that repository
automatically. This keeps version-controlled n8n workflows portable.

For local authentication, create a random token and put it in the process
environment instead of committing it:

```bash
export CODEX_ADAPTER_TOKEN="$(openssl rand -hex 32)"
```

When the token is set, callers must send:

```text
Authorization: Bearer <token>
```

## Run

From this directory:

```bash
python3 -m codex_adapter --config config.json
```

Health check:

```bash
curl --fail --silent http://127.0.0.1:8765/health | python3 -m json.tool
```

Read-only request:

```bash
curl --fail-with-body \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "prompt": "Summarize this repository. Do not change files.",
    "repo_path": "/absolute/path/to/automation-workbench",
    "mode": "read_only",
    "timeout_seconds": 900,
    "request_id": "manual-smoke-1"
  }' \
  http://127.0.0.1:8765/codex/run
```

For a coding task, change `mode` to `workspace_write`. `danger-full-access` is
intentionally not part of the HTTP contract.

## n8n HTTP Request node

An importable workflow is included at
`../workflows/codex-adapter-mvp.workflow.json`. It exposes:

```text
POST http://127.0.0.1:5678/webhook/local-codex-run
```

The workflow is:

```text
Local Codex Webhook -> Run Codex -> Return Codex Result
```

Import it with the n8n UI, then publish it. For this repository's existing
container the equivalent CLI import is:

```bash
docker cp \
  ../workflows/codex-adapter-mvp.workflow.json \
  local-n8n:/tmp/codex-adapter-mvp.workflow.json
docker exec local-n8n n8n import:workflow \
  --input=/tmp/codex-adapter-mvp.workflow.json
```

Single-main n8n intentionally imports it as a draft; publish it once in the
editor to register the production webhook.

Use:

- Method: `POST`
- URL from host processes: `http://127.0.0.1:8765/codex/run`
- URL from the n8n Docker container: first test
  `http://host.docker.internal:8765/health`
- Send Body: JSON
- Content Type: JSON

Example body with an incoming webhook:

```json
{
  "prompt": "={{ $json.body.prompt }}",
  "repo_path": "={{ $json.body.repo_path }}",
  "mode": "={{ $json.body.mode || 'read_only' }}",
  "request_id": "={{ $execution.id }}"
}
```

Call the imported workflow:

```bash
curl --fail-with-body \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "prompt": "Reply with exactly N8N_CODEX_OK. Do not run commands.",
    "repo_path": "/absolute/path/to/automation-workbench",
    "mode": "read_only",
    "timeout_seconds": 120
  }' \
  http://127.0.0.1:5678/webhook/local-codex-run
```

This machine's Docker Desktop setup was verified to reach the loopback-bound
adapter through `host.docker.internal`. Do not change the adapter to
`0.0.0.0`. If the same health test fails after moving the setup to another
machine, use a narrowly scoped local relay or run the adapter in the same
controlled Docker network.

## Response

Successful HTTP execution returns:

```json
{
  "ok": true,
  "request_id": "manual-smoke-1",
  "repo_path": "/absolute/allowlisted/path",
  "mode": "read_only",
  "sandbox": "read-only",
  "exit_code": 0,
  "timed_out": false,
  "duration_ms": 1234,
  "final_output": "Agent final response",
  "events": [],
  "malformed_stdout_lines": [],
  "stderr": ""
}
```

The server returns `502` when Codex exits unsuccessfully, `429` when all run
slots are occupied, and `400` for invalid input.

## Test

```bash
python3 -m unittest discover -s tests -v
```

The next integration step is an importable n8n workflow and, after this HTTP
contract is stable, an optional runner backed by Codex MCP plus Agents SDK.

## Website availability fallback

`POST /sites/audit` creates one immutable evidence directory per run:

```text
../scenarios/website-availability/runs/
└── 20260728-130000-check-name-request/
    ├── report.md
    ├── report.json
    └── snapshots/
        ├── site-one.png
        └── site-two.png
```

The normal project strategy uses Codex and its in-app Browser, as described in
`../scenarios/website-availability/SCENARIO.md`. The adapter endpoint remains a
deterministic host-Chrome fallback: it checks every URL, records status and
response time, then captures a PNG with an already installed Chrome. No
additional browser image is downloaded.

Allowed target hosts are configured in `allowed_site_hosts`. Exact hostnames
and explicit wildcard subdomains such as `*.example.com` are supported.

The importable n8n gate workflow is:

```text
../workflows/website-availability-gate.workflow.json
```

Its production webhook is:

```text
POST http://127.0.0.1:5678/webhook/website-availability-gate
```

Codex posts the completed `report.json` to that webhook. Minimal example:

```bash
curl --fail-with-body \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "run_id": "20260728-130000-local-n8n-smoke",
    "check_name": "local-n8n-smoke",
    "all_ok": true,
    "result": "PASS",
    "report_path": "scenarios/website-availability/runs/20260728-130000-local-n8n-smoke/report.md",
    "next_stage": "functional_checks"
  }' \
  http://127.0.0.1:5678/webhook/website-availability-gate
```

The workflow returns HTTP 200 with `gate: passed` when functional checks may
start. It returns HTTP 424 with `gate: failed` when `all_ok` is not true.
