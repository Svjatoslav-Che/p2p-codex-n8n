# Website availability evidence gate

## Goal

Подтвердить доступность каждого сайта HTTP-проверкой и PNG-снапшотом. Только
полный PASS разрешает перейти к функциональным проверкам.

## Input

Source: `sites.json`.

Each entry:

- `name`: человекочитаемое имя;
- `health_url`: URL для HTTP-проверки;
- `browser_url`: страница, которую нужно открыть в Codex Browser;
- `expected_statuses`: допустимые HTTP-коды.

## Run layout

```text
runs/<YYYYMMDD-HHMMSS>-<check-name>/
├── report.md
├── report.json
└── snapshots/
    └── <site-slug>.png
```

## Required report fields

- timestamp and run id;
- `check_name`;
- URL and final URL;
- HTTP status;
- response time in milliseconds;
- availability result;
- screenshot path and result;
- error text;
- boolean `all_ok` plus final `PASS` or `FAIL`;
- `next_stage`: `functional_checks` only for PASS, otherwise `blocked`.

## Gate

PASS requires every configured health check and screenshot. Do not continue to
login/logout or other functional tests after a partial result.

After writing the local report, Codex sends the same JSON to:

```text
POST http://127.0.0.1:5678/webhook/website-availability-gate
Content-Type: application/json
```

The n8n workflow returns `gate: passed` and
`proceed_to: functional_checks` only when `all_ok` is exactly `true`. Save the
n8n response in `report.json` as `n8n_gate`. A failed or unreachable n8n gate
blocks the next stage even when the local checks succeeded.
