from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class ConfigError(ValueError):
    """Raised when adapter configuration is missing or unsafe."""


@dataclass(frozen=True)
class AdapterConfig:
    host: str
    port: int
    allowed_repos: tuple[Path, ...]
    codex_bin: Path
    default_timeout_seconds: int
    max_timeout_seconds: int
    max_request_bytes: int
    max_concurrent_runs: int
    bearer_token: str | None
    audit_root: Path
    allowed_site_hosts: tuple[str, ...]
    chrome_bin: Path
    site_check_timeout_seconds: int
    snapshot_timeout_seconds: int
    max_sites_per_audit: int


def _as_int(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return result


def _resolve_existing_file(value: str | os.PathLike[str], name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ConfigError(f"{name} is not a file: {path}")
    if not os.access(path, os.X_OK):
        raise ConfigError(f"{name} is not executable: {path}")
    return path


def _discover_codex_binary(explicit: str | None) -> Path:
    if explicit:
        return _resolve_existing_file(explicit, "codex_bin")

    candidates = (
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
        Path("/Applications/Codex.app/Contents/Resources/codex"),
        Path("/usr/local/bin/codex"),
        Path("/opt/homebrew/bin/codex"),
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise ConfigError(
        "No Codex executable found. Set codex_bin in config.json or CODEX_BIN."
    )


def _discover_chrome_binary(explicit: str | None) -> Path:
    if explicit:
        return _resolve_existing_file(explicit, "chrome_bin")

    candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise ConfigError(
        "No Chrome/Chromium executable found. Set chrome_bin in config.json."
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Config file not found: {path}. Copy config.example.json to config.json."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("The config root must be a JSON object")
    return value


def load_config(path: str | os.PathLike[str] | None = None) -> AdapterConfig:
    config_path = Path(
        path
        or os.environ.get("CODEX_ADAPTER_CONFIG")
        or Path.cwd() / "config.json"
    ).expanduser()
    config_dir = config_path.resolve().parent
    raw = _load_json(config_path)

    host = str(os.environ.get("CODEX_ADAPTER_HOST", raw.get("host", "127.0.0.1")))
    if host not in LOOPBACK_HOSTS:
        raise ConfigError(
            f"Refusing non-loopback host {host!r}; use 127.0.0.1, ::1, or localhost"
        )

    repos_value = raw.get("allowed_repos")
    if not isinstance(repos_value, list) or not repos_value:
        raise ConfigError("allowed_repos must be a non-empty JSON array")

    allowed_repos: list[Path] = []
    for item in repos_value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError("Every allowed_repos entry must be a non-empty string")
        repo = Path(item).expanduser()
        if not repo.is_absolute():
            repo = config_dir / repo
        repo = repo.resolve()
        if not repo.is_dir():
            raise ConfigError(f"Allowlisted repository is not a directory: {repo}")
        allowed_repos.append(repo)

    codex_bin_value = os.environ.get("CODEX_BIN") or raw.get("codex_bin")
    codex_bin = _discover_codex_binary(
        str(codex_bin_value) if codex_bin_value else None
    )

    max_timeout = _as_int(
        raw.get("max_timeout_seconds", 3600),
        "max_timeout_seconds",
        minimum=10,
        maximum=7200,
    )
    default_timeout = _as_int(
        raw.get("default_timeout_seconds", 900),
        "default_timeout_seconds",
        minimum=10,
        maximum=max_timeout,
    )

    token = os.environ.get("CODEX_ADAPTER_TOKEN") or raw.get("bearer_token")
    if token is not None:
        if not isinstance(token, str) or len(token) < 16:
            raise ConfigError("bearer_token must contain at least 16 characters")

    audit_root = Path(
        os.environ.get("CODEX_AUDIT_ROOT")
        or raw.get("audit_root")
        or config_path.parent / "site-audits"
    ).expanduser()
    if not audit_root.is_absolute():
        audit_root = config_dir / audit_root
    audit_root = audit_root.resolve()
    audit_root.mkdir(parents=True, exist_ok=True)
    if not audit_root.is_dir():
        raise ConfigError(f"audit_root is not a directory: {audit_root}")

    allowed_hosts_value = raw.get("allowed_site_hosts", ["127.0.0.1", "localhost"])
    if not isinstance(allowed_hosts_value, list) or not allowed_hosts_value:
        raise ConfigError("allowed_site_hosts must be a non-empty JSON array")
    allowed_site_hosts: list[str] = []
    for item in allowed_hosts_value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(
                "Every allowed_site_hosts entry must be a non-empty string"
            )
        host = item.strip().lower().rstrip(".")
        if "/" in host or ":" in host:
            raise ConfigError(
                f"allowed_site_hosts must contain hostnames without scheme/port: {item}"
            )
        allowed_site_hosts.append(host)

    chrome_bin_value = os.environ.get("CHROME_BIN") or raw.get("chrome_bin")
    chrome_bin = _discover_chrome_binary(
        str(chrome_bin_value) if chrome_bin_value else None
    )

    return AdapterConfig(
        host=host,
        port=_as_int(
            os.environ.get("CODEX_ADAPTER_PORT", raw.get("port", 8765)),
            "port",
            minimum=1,
            maximum=65535,
        ),
        allowed_repos=tuple(dict.fromkeys(allowed_repos)),
        codex_bin=codex_bin,
        default_timeout_seconds=default_timeout,
        max_timeout_seconds=max_timeout,
        max_request_bytes=_as_int(
            raw.get("max_request_bytes", 131_072),
            "max_request_bytes",
            minimum=1024,
            maximum=10_485_760,
        ),
        max_concurrent_runs=_as_int(
            raw.get("max_concurrent_runs", 1),
            "max_concurrent_runs",
            minimum=1,
            maximum=8,
        ),
        bearer_token=token,
        audit_root=audit_root,
        allowed_site_hosts=tuple(dict.fromkeys(allowed_site_hosts)),
        chrome_bin=chrome_bin,
        site_check_timeout_seconds=_as_int(
            raw.get("site_check_timeout_seconds", 20),
            "site_check_timeout_seconds",
            minimum=1,
            maximum=120,
        ),
        snapshot_timeout_seconds=_as_int(
            raw.get("snapshot_timeout_seconds", 45),
            "snapshot_timeout_seconds",
            minimum=5,
            maximum=180,
        ),
        max_sites_per_audit=_as_int(
            raw.get("max_sites_per_audit", 50),
            "max_sites_per_audit",
            minimum=1,
            maximum=200,
        ),
    )
