from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import AdapterConfig


DEFAULT_EXPECTED_STATUSES = frozenset(
    [*range(200, 300), 301, 302, 303, 307, 308]
)
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class AuditRequestError(ValueError):
    """Raised when a website audit request is invalid."""


@dataclass(frozen=True)
class SiteTarget:
    name: str
    url: str
    snapshot_url: str
    slug: str
    expected_statuses: frozenset[int]


@dataclass(frozen=True)
class SiteAuditRequest:
    check_name: str
    sites: tuple[SiteTarget, ...]
    request_id: str


def slugify(value: str, *, fallback: str) -> str:
    slug = SLUG_PATTERN.sub("-", value.lower()).strip("-")
    return (slug or fallback)[:80]


def host_is_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    candidate = host.lower().rstrip(".")
    for allowed in allowed_hosts:
        if allowed.startswith("*."):
            suffix = allowed[1:]
            if candidate.endswith(suffix) and candidate != suffix[1:]:
                return True
        elif candidate == allowed:
            return True
    return False


def _validate_url(value: Any, config: AdapterConfig) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditRequestError("Every site url must be a non-empty string")
    url = value.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise AuditRequestError(f"Site URL must use http or https: {url}")
    if not parsed.hostname:
        raise AuditRequestError(f"Site URL has no hostname: {url}")
    if parsed.username or parsed.password:
        raise AuditRequestError("Credentials are not allowed inside site URLs")
    if not host_is_allowed(parsed.hostname, config.allowed_site_hosts):
        raise AuditRequestError(
            f"Site host is not in allowed_site_hosts: {parsed.hostname}"
        )
    return url


def _expected_statuses(value: Any) -> frozenset[int]:
    if value is None:
        return DEFAULT_EXPECTED_STATUSES
    if not isinstance(value, list) or not value:
        raise AuditRequestError("expected_statuses must be a non-empty array")
    statuses: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            raise AuditRequestError("HTTP statuses must be integers")
        try:
            status = int(item)
        except (TypeError, ValueError) as exc:
            raise AuditRequestError("HTTP statuses must be integers") from exc
        if not 100 <= status <= 599:
            raise AuditRequestError("HTTP statuses must be between 100 and 599")
        statuses.add(status)
    return frozenset(statuses)


def validate_audit_request(
    payload: Any,
    config: AdapterConfig,
) -> SiteAuditRequest:
    if not isinstance(payload, dict):
        raise AuditRequestError("JSON body must be an object")

    check_name_value = payload.get("check_name", "website-availability")
    if not isinstance(check_name_value, str) or not check_name_value.strip():
        raise AuditRequestError("check_name must be a non-empty string")
    check_name = check_name_value.strip()[:160]

    sites_value = payload.get("sites")
    if not isinstance(sites_value, list) or not sites_value:
        raise AuditRequestError("sites must be a non-empty array")
    if len(sites_value) > config.max_sites_per_audit:
        raise AuditRequestError(
            f"sites cannot contain more than {config.max_sites_per_audit} entries"
        )

    targets: list[SiteTarget] = []
    used_slugs: set[str] = set()
    for index, item in enumerate(sites_value, start=1):
        if not isinstance(item, dict):
            raise AuditRequestError("Every sites entry must be an object")
        url = _validate_url(item.get("url"), config)
        snapshot_url = _validate_url(item.get("snapshot_url", url), config)
        name_value = item.get("name") or urlsplit(url).hostname or f"site-{index}"
        if not isinstance(name_value, str) or not name_value.strip():
            raise AuditRequestError("Every site name must be a non-empty string")
        name = name_value.strip()[:160]
        base_slug = slugify(name, fallback=f"site-{index}")
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug[:72]}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        targets.append(
            SiteTarget(
                name=name,
                url=url,
                snapshot_url=snapshot_url,
                slug=slug,
                expected_statuses=_expected_statuses(
                    item.get("expected_statuses")
                ),
            )
        )

    request_id_value = payload.get("request_id")
    if request_id_value is not None and (
        not isinstance(request_id_value, str)
        or not request_id_value.strip()
        or len(request_id_value) > 128
    ):
        raise AuditRequestError(
            "request_id must be a non-empty string of at most 128 characters"
        )

    return SiteAuditRequest(
        check_name=check_name,
        sites=tuple(targets),
        request_id=request_id_value or str(uuid.uuid4()),
    )


def _check_site(site: SiteTarget, config: AdapterConfig) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(
        site.url,
        headers={"User-Agent": "LocalCodexWebsiteAudit/0.1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=config.site_check_timeout_seconds,
        ) as response:
            status = response.status
            final_url = response.geturl()
            response.read(1024)
        error = None
    except urllib.error.HTTPError as exc:
        status = exc.code
        final_url = exc.geturl()
        error = f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        status = None
        final_url = None
        error = f"{type(exc).__name__}: {exc}"

    response_time_ms = round((time.monotonic() - started) * 1000)
    available = status in site.expected_statuses if status is not None else False
    return {
        "name": site.name,
        "url": site.url,
        "final_url": final_url,
        "expected_statuses": sorted(site.expected_statuses),
        "available": available,
        "http_status": status,
        "response_time_ms": response_time_ms,
        "error": None if available else error or f"Unexpected HTTP status {status}",
    }


def _take_snapshot(
    site: SiteTarget,
    destination: Path,
    config: AdapterConfig,
) -> tuple[bool, str | None]:
    with tempfile.TemporaryDirectory(
        prefix=".chrome-profile-",
        dir=destination.parent.parent,
    ) as profile_dir:
        command = [
            str(config.chrome_bin),
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-crash-reporter",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--window-size=1440,900",
            "--virtual-time-budget=5000",
            "--run-all-compositor-stages-before-draw",
            f"--screenshot={destination}",
            site.snapshot_url,
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=config.snapshot_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"{type(exc).__name__}: {exc}"

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return False, message or f"Chrome exited with code {completed.returncode}"
    if not destination.is_file() or destination.stat().st_size == 0:
        return False, "Chrome exited successfully but did not create a PNG"
    return True, None


def _escape_markdown(value: Any) -> str:
    return str(value if value is not None else "—").replace("|", "\\|").replace(
        "\n", " "
    )


def _render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        f"# Website availability report: {result['check_name']}",
        "",
        f"- Created: `{result['created_at']}`",
        f"- Request ID: `{result['request_id']}`",
        f"- Result: `{'PASS' if result['all_ok'] else 'FAIL'}`",
        f"- Sites: `{summary['total']}`",
        f"- Available: `{summary['available']}`",
        f"- Snapshots created: `{summary['snapshots_created']}`",
        "",
        "| Site | URL | HTTP | Response | Available | Snapshot | Error |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for site in result["sites"]:
        snapshot = (
            f"[PNG]({site['snapshot_relative_path']})"
            if site["snapshot_ok"]
            else "FAIL"
        )
        error = site["error"] or site["snapshot_error"] or ""
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_markdown(site["name"]),
                    _escape_markdown(site["url"]),
                    _escape_markdown(site["http_status"]),
                    f"{site['response_time_ms']} ms",
                    "YES" if site["available"] else "NO",
                    snapshot,
                    _escape_markdown(error),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Gate",
            "",
            (
                "All availability checks and snapshots passed. "
                "Functional checks may start."
                if result["all_ok"]
                else "Functional checks are blocked until all failures are resolved."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_site_audit(
    request: SiteAuditRequest,
    config: AdapterConfig,
) -> dict[str, Any]:
    created_at = datetime.now(UTC)
    folder_name = (
        f"{created_at.strftime('%Y%m%d-%H%M%S')}-"
        f"{slugify(request.check_name, fallback='website-audit')}-"
        f"{request.request_id[:8]}"
    )
    run_dir = config.audit_root / folder_name
    snapshots_dir = run_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=False)

    site_results: list[dict[str, Any]] = []
    for site in request.sites:
        site_result = _check_site(site, config)
        snapshot_path = snapshots_dir / f"{site.slug}.png"
        snapshot_ok = False
        snapshot_error = None
        if site_result["available"]:
            snapshot_ok, snapshot_error = _take_snapshot(
                site,
                snapshot_path,
                config,
            )
        else:
            snapshot_error = "Skipped because availability check failed"

        site_result.update(
            {
                "snapshot_url": site.snapshot_url,
                "snapshot_ok": snapshot_ok,
                "snapshot_path": str(snapshot_path) if snapshot_ok else None,
                "snapshot_relative_path": (
                    f"snapshots/{snapshot_path.name}" if snapshot_ok else None
                ),
                "snapshot_error": snapshot_error,
            }
        )
        site_results.append(site_result)

    all_ok = all(
        site["available"] and site["snapshot_ok"] for site in site_results
    )
    result: dict[str, Any] = {
        "ok": True,
        "request_id": request.request_id,
        "check_name": request.check_name,
        "created_at": created_at.isoformat(),
        "all_ok": all_ok,
        "next_stage": "functional_checks" if all_ok else "blocked",
        "run_directory": str(run_dir),
        "report_path": str(run_dir / "report.md"),
        "report_json_path": str(run_dir / "report.json"),
        "snapshots_directory": str(snapshots_dir),
        "summary": {
            "total": len(site_results),
            "available": sum(1 for site in site_results if site["available"]),
            "snapshots_created": sum(
                1 for site in site_results if site["snapshot_ok"]
            ),
            "failed": sum(
                1
                for site in site_results
                if not site["available"] or not site["snapshot_ok"]
            ),
        },
        "sites": site_results,
    }
    (run_dir / "report.md").write_text(
        _render_markdown(result),
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
