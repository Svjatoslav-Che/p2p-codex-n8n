from __future__ import annotations

import argparse
import hmac
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from . import __version__
from .config import AdapterConfig, ConfigError, load_config
from .runner import RequestError, codex_version, run_codex, validate_request
from .site_audit import (
    AuditRequestError,
    run_site_audit,
    validate_audit_request,
)


LOGGER = logging.getLogger("codex-adapter")


class AdapterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: AdapterConfig):
        super().__init__((config.host, config.port), AdapterRequestHandler)
        self.config = config
        self.run_slots = threading.BoundedSemaphore(config.max_concurrent_runs)


class AdapterRequestHandler(BaseHTTPRequestHandler):
    server: AdapterHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, message: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.client_address[0], message % args)

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    def _authorized(self) -> bool:
        expected = self.server.config.bearer_token
        if not expected:
            return True
        provided = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not provided.startswith(prefix):
            return False
        return hmac.compare_digest(provided[len(prefix) :], expected)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._send_json(
            HTTPStatus.UNAUTHORIZED,
            {"ok": False, "error": "missing or invalid bearer token"},
        )
        return False

    def do_GET(self) -> None:
        if self._path() != "/health":
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": "not found"},
            )
            return
        if not self._require_auth():
            return

        codex_ok, version = codex_version(self.server.config)
        self._send_json(
            HTTPStatus.OK if codex_ok else HTTPStatus.SERVICE_UNAVAILABLE,
            {
                "ok": codex_ok,
                "service": "codex-adapter",
                "adapter_version": __version__,
                "codex_version": version,
                "codex_bin": str(self.server.config.codex_bin),
                "allowed_repos": [
                    str(path) for path in self.server.config.allowed_repos
                ],
                "max_concurrent_runs": self.server.config.max_concurrent_runs,
                "audit_root": str(self.server.config.audit_root),
                "allowed_site_hosts": list(
                    self.server.config.allowed_site_hosts
                ),
                "snapshot_backend": str(self.server.config.chrome_bin),
            },
        )

    def do_POST(self) -> None:
        route = self._path()
        if route not in {"/codex/run", "/sites/audit"}:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": "not found"},
            )
            return
        if not self._require_auth():
            return

        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"ok": False, "error": "Content-Type must be application/json"},
            )
            return

        content_length_value = self.headers.get("Content-Length")
        try:
            content_length = int(content_length_value or "")
        except ValueError:
            self._send_json(
                HTTPStatus.LENGTH_REQUIRED,
                {"ok": False, "error": "valid Content-Length is required"},
            )
            return
        if content_length < 0 or content_length > self.server.config.max_request_bytes:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"ok": False, "error": "request body is too large"},
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "request body is not valid JSON"},
            )
            return

        if route == "/sites/audit":
            self._handle_site_audit(payload)
            return
        self._handle_codex_run(payload)

    def _handle_site_audit(self, payload: Any) -> None:
        try:
            request = validate_audit_request(payload, self.server.config)
        except AuditRequestError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": str(exc)},
            )
            return

        if not self.server.run_slots.acquire(blocking=False):
            self._send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"ok": False, "error": "all Codex run slots are busy"},
            )
            return

        LOGGER.info(
            "site audit started request_id=%s name=%s sites=%s",
            request.request_id,
            request.check_name,
            len(request.sites),
        )
        try:
            result = run_site_audit(request, self.server.config)
        except Exception as exc:
            LOGGER.exception("Site audit failed")
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "ok": False,
                    "request_id": request.request_id,
                    "error": f"Site audit failed: {type(exc).__name__}: {exc}",
                },
            )
            return
        finally:
            self.server.run_slots.release()

        LOGGER.info(
            "site audit finished request_id=%s all_ok=%s directory=%s",
            request.request_id,
            result["all_ok"],
            result["run_directory"],
        )
        self._send_json(HTTPStatus.OK, result)

    def _handle_codex_run(self, payload: Any) -> None:
        try:
            request = validate_request(payload, self.server.config)
        except RequestError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": str(exc)},
            )
            return

        if not self.server.run_slots.acquire(blocking=False):
            self._send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"ok": False, "error": "all Codex run slots are busy"},
            )
            return

        LOGGER.info(
            "run started request_id=%s mode=%s repo=%s",
            request.request_id,
            request.mode,
            request.repo_path,
        )
        try:
            result = run_codex(request, self.server.config)
        except OSError as exc:
            LOGGER.exception("Codex process failed to start")
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "ok": False,
                    "request_id": request.request_id,
                    "error": f"Codex process failed to start: {exc}",
                },
            )
            return
        finally:
            self.server.run_slots.release()

        LOGGER.info(
            "run finished request_id=%s ok=%s exit_code=%s duration_ms=%s",
            request.request_id,
            result["ok"],
            result["exit_code"],
            result["duration_ms"],
        )
        status = HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_GATEWAY
        self._send_json(status, result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local HTTP adapter for Codex")
    parser.add_argument(
        "--config",
        help="Path to config JSON (default: ./config.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    codex_ok, version = codex_version(config)
    if not codex_ok:
        raise SystemExit(f"Codex readiness check failed: {version}")

    server = AdapterHTTPServer(config)
    LOGGER.info(
        "listening on http://%s:%s (Codex %s)",
        config.host,
        config.port,
        version,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
