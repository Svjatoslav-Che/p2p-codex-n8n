from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_adapter.config import AdapterConfig, ConfigError, load_config
from codex_adapter.runner import (
    RequestError,
    RunRequest,
    build_command,
    validate_request,
)
from codex_adapter.site_audit import (
    AuditRequestError,
    host_is_allowed,
    run_site_audit,
    validate_audit_request,
)


class AdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.codex_bin = root / "codex"
        self.codex_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.codex_bin.chmod(0o755)
        self.config = AdapterConfig(
            host="127.0.0.1",
            port=8765,
            allowed_repos=(self.repo.resolve(),),
            codex_bin=self.codex_bin.resolve(),
            default_timeout_seconds=30,
            max_timeout_seconds=120,
            max_request_bytes=4096,
            max_concurrent_runs=1,
            bearer_token=None,
            audit_root=root / "audits",
            allowed_site_hosts=("localhost", "*.example.com"),
            chrome_bin=self.codex_bin.resolve(),
            site_check_timeout_seconds=2,
            snapshot_timeout_seconds=5,
            max_sites_per_audit=10,
        )
        self.config.audit_root.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_validate_request_maps_allowlisted_repo(self) -> None:
        request = validate_request(
            {
                "prompt": "Inspect the repository",
                "repo_path": str(self.repo),
                "mode": "workspace_write",
                "request_id": "n8n-1",
            },
            self.config,
        )
        self.assertEqual(request.repo_path, self.repo.resolve())
        self.assertEqual(request.mode, "workspace_write")
        self.assertEqual(request.timeout_seconds, 30)
        self.assertEqual(request.request_id, "n8n-1")

    def test_validate_request_rejects_repo_outside_allowlist(self) -> None:
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        with self.assertRaisesRegex(RequestError, "allowlist"):
            validate_request(
                {"prompt": "test", "repo_path": str(outside)},
                self.config,
            )

    def test_validate_request_rejects_unknown_mode(self) -> None:
        with self.assertRaisesRegex(RequestError, "mode"):
            validate_request(
                {
                    "prompt": "test",
                    "repo_path": str(self.repo),
                    "mode": "danger_full_access",
                },
                self.config,
            )

    def test_command_has_noninteractive_sandbox_controls(self) -> None:
        request = RunRequest(
            prompt="test",
            repo_path=self.repo.resolve(),
            mode="read_only",
            timeout_seconds=30,
            model=None,
            request_id="test-id",
        )
        command = build_command(request, self.config, Path("/tmp/output"))
        self.assertIn("read-only", command)
        self.assertIn("never", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertNotIn("danger-full-access", command)
        self.assertLess(command.index("--ask-for-approval"), command.index("exec"))
        self.assertEqual(command[-1], "-")

    def test_load_config_rejects_non_loopback_bind(self) -> None:
        config_path = Path(self.temp_dir.name) / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "host": "0.0.0.0",
                    "allowed_repos": [str(self.repo)],
                    "codex_bin": str(self.codex_bin),
                }
            ),
            encoding="utf-8",
        )
        previous = os.environ.pop("CODEX_ADAPTER_HOST", None)
        try:
            with self.assertRaisesRegex(ConfigError, "non-loopback"):
                load_config(config_path)
        finally:
            if previous is not None:
                os.environ["CODEX_ADAPTER_HOST"] = previous

    def test_site_allowlist_supports_exact_and_subdomain_entries(self) -> None:
        self.assertTrue(
            host_is_allowed("localhost", self.config.allowed_site_hosts)
        )
        self.assertTrue(
            host_is_allowed("admin.example.com", self.config.allowed_site_hosts)
        )
        self.assertFalse(
            host_is_allowed("example.com", self.config.allowed_site_hosts)
        )
        self.assertFalse(
            host_is_allowed("example.com.attacker.test", self.config.allowed_site_hosts)
        )

    def test_audit_request_rejects_host_outside_allowlist(self) -> None:
        with self.assertRaisesRegex(AuditRequestError, "allowed_site_hosts"):
            validate_audit_request(
                {
                    "check_name": "test",
                    "sites": [{"name": "Blocked", "url": "https://blocked.test"}],
                },
                self.config,
            )

    def test_site_audit_creates_report_and_snapshot_directory(self) -> None:
        request = validate_audit_request(
            {
                "check_name": "Local smoke",
                "request_id": "audit-test",
                "sites": [{"name": "Local", "url": "http://localhost:8000"}],
            },
            self.config,
        )

        def fake_check(site, config):
            return {
                "name": site.name,
                "url": site.url,
                "snapshot_url": site.snapshot_url,
                "final_url": site.url,
                "expected_statuses": [200],
                "available": True,
                "http_status": 200,
                "response_time_ms": 12,
                "error": None,
            }

        def fake_snapshot(site, destination, config):
            destination.write_bytes(b"\x89PNG\r\n\x1a\n")
            return True, None

        with (
            patch("codex_adapter.site_audit._check_site", fake_check),
            patch("codex_adapter.site_audit._take_snapshot", fake_snapshot),
        ):
            result = run_site_audit(request, self.config)

        self.assertTrue(result["all_ok"])
        self.assertEqual(result["next_stage"], "functional_checks")
        self.assertTrue(Path(result["report_path"]).is_file())
        self.assertTrue(Path(result["report_json_path"]).is_file())
        self.assertTrue(Path(result["sites"][0]["snapshot_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
