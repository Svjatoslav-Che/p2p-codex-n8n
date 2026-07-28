from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AdapterConfig


MODE_TO_SANDBOX = {
    "read_only": "read-only",
    "workspace_write": "workspace-write",
}


class RequestError(ValueError):
    """Raised when a run request fails validation."""


@dataclass(frozen=True)
class RunRequest:
    prompt: str
    repo_path: Path
    mode: str
    timeout_seconds: int
    model: str | None
    request_id: str


def validate_request(payload: Any, config: AdapterConfig) -> RunRequest:
    if not isinstance(payload, dict):
        raise RequestError("JSON body must be an object")

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RequestError("prompt must be a non-empty string")

    repo_value = payload.get("repo_path")
    if not isinstance(repo_value, str) or not repo_value.strip():
        raise RequestError("repo_path must be a non-empty string")
    repo_path = Path(repo_value).expanduser().resolve()
    if repo_path not in config.allowed_repos:
        raise RequestError("repo_path is not in the adapter allowlist")

    mode = payload.get("mode", "read_only")
    if mode not in MODE_TO_SANDBOX:
        raise RequestError("mode must be read_only or workspace_write")

    timeout_value = payload.get(
        "timeout_seconds",
        config.default_timeout_seconds,
    )
    if isinstance(timeout_value, bool):
        raise RequestError("timeout_seconds must be an integer")
    try:
        timeout_seconds = int(timeout_value)
    except (TypeError, ValueError) as exc:
        raise RequestError("timeout_seconds must be an integer") from exc
    if not 10 <= timeout_seconds <= config.max_timeout_seconds:
        raise RequestError(
            f"timeout_seconds must be between 10 and {config.max_timeout_seconds}"
        )

    model = payload.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise RequestError("model must be a non-empty string when provided")

    supplied_request_id = payload.get("request_id")
    if supplied_request_id is not None and (
        not isinstance(supplied_request_id, str)
        or not supplied_request_id.strip()
        or len(supplied_request_id) > 128
    ):
        raise RequestError(
            "request_id must be a non-empty string of at most 128 characters"
        )

    return RunRequest(
        prompt=prompt,
        repo_path=repo_path,
        mode=mode,
        timeout_seconds=timeout_seconds,
        model=model.strip() if model else None,
        request_id=supplied_request_id or str(uuid.uuid4()),
    )


def build_command(
    request: RunRequest,
    config: AdapterConfig,
    output_file: Path,
) -> list[str]:
    command = [
        str(config.codex_bin),
        "--ask-for-approval",
        "never",
        "exec",
        "--ignore-user-config",
        "--cd",
        str(request.repo_path),
        "--sandbox",
        MODE_TO_SANDBOX[request.mode],
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--output-last-message",
        str(output_file),
    ]
    if request.model:
        command.extend(["--model", request.model])
    command.append("-")
    return command


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _parse_jsonl(stdout: str) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    malformed: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(line)
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            malformed.append(line)
    return events, malformed


def run_codex(request: RunRequest, config: AdapterConfig) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="codex-adapter-") as temp_dir:
        output_file = Path(temp_dir) / "last-message.txt"
        command = build_command(request, config, output_file)
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(
                input=request.prompt,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process)
            stdout, stderr = process.communicate()

        final_output = ""
        if output_file.is_file():
            final_output = output_file.read_text(
                encoding="utf-8",
                errors="replace",
            )

    events, malformed_lines = _parse_jsonl(stdout)
    duration_ms = round((time.monotonic() - started) * 1000)
    exit_code = process.returncode
    return {
        "ok": exit_code == 0 and not timed_out,
        "request_id": request.request_id,
        "repo_path": str(request.repo_path),
        "mode": request.mode,
        "sandbox": MODE_TO_SANDBOX[request.mode],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
        "final_output": final_output,
        "events": events,
        "malformed_stdout_lines": malformed_lines,
        "stderr": stderr,
    }


def codex_version(config: AdapterConfig) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [str(config.codex_bin), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = completed.stdout.strip()
    if completed.returncode != 0:
        output = completed.stderr.strip() or output
    return completed.returncode == 0, output
