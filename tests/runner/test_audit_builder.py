# ruff: noqa: S108
"""Sprint 7 BL-0079: Runner audit event builder tests."""

from __future__ import annotations

import dataclasses

import pytest

from backend.app.services.runner.audit_builder import (
    build_runner_blocked,
    build_runner_completed,
    build_runner_started,
)
from backend.app.services.runner.runner_adapter import (
    RunnerCommandRequest,
    RunnerCommandResult,
    RunnerWorkspace,
)


@pytest.fixture
def workspace() -> RunnerWorkspace:
    return RunnerWorkspace(
        run_id="run-abc",
        workspace_id="0" * 32,
        workdir="/tmp/runner-run-abc-0",
    )


@pytest.fixture
def request_simple() -> RunnerCommandRequest:
    return RunnerCommandRequest(
        argv=("/bin/echo", "hello"),
        cwd="/tmp/runner-run-abc-0",
        env_allowlist=frozenset({"PATH"}),
    )


def test_runner_started_payload_no_raw_argv(
    workspace: RunnerWorkspace,
    request_simple: RunnerCommandRequest,
) -> None:
    payload = build_runner_started(workspace, request_simple)
    assert payload.event_type == "runner_started"
    assert payload.workspace_id == "0" * 32
    assert payload.run_id == "run-abc"
    assert payload.argv_basename == "echo"
    # raw argv ("hello") must not appear in payload
    d = payload.to_dict()
    assert "hello" not in str(d)
    assert "/bin/echo" not in str(d)
    # hash should be 16-char hex
    assert len(payload.argv_hash) == 16
    assert all(c in "0123456789abcdef" for c in payload.argv_hash)


def test_runner_completed_payload_includes_metrics(
    workspace: RunnerWorkspace,
    request_simple: RunnerCommandRequest,
) -> None:
    result = RunnerCommandResult(
        exit_code=0,
        stdout_bytes=6,
        stderr_bytes=0,
        duration_seconds=0.5,
        timeout_reached=False,
        cancelled=False,
        scrubbed_env_keys=("OPENAI_API_KEY",),
    )
    payload = build_runner_completed(workspace, request_simple, result)
    d = payload.to_dict()
    assert payload.event_type == "runner_completed"
    assert d["exit_code"] == 0
    assert d["stdout_bytes"] == 6
    assert d["duration_seconds"] == 0.5
    assert d["scrubbed_env_keys"] == ["OPENAI_API_KEY"]
    assert d["output_cap_exceeded"] is False
    assert d["cancelled"] is False


def test_runner_blocked_payload_records_reason(
    workspace: RunnerWorkspace,
    request_simple: RunnerCommandRequest,
) -> None:
    payload = build_runner_blocked(
        workspace,
        request_simple,
        reason_code="rm_rf",
        deny_category="dangerous_command",
    )
    d = payload.to_dict()
    assert payload.event_type == "runner_blocked"
    assert d["deny_category"] == "dangerous_command"
    assert d["reason_code"] == "rm_rf"


def test_runner_blocked_invalid_category_rejected(
    workspace: RunnerWorkspace,
    request_simple: RunnerCommandRequest,
) -> None:
    with pytest.raises(ValueError, match="deny_category"):
        build_runner_blocked(
            workspace,
            request_simple,
            reason_code="anything",
            deny_category="invalid_category",
        )


def test_runner_audit_payload_is_frozen(
    workspace: RunnerWorkspace,
    request_simple: RunnerCommandRequest,
) -> None:
    payload = build_runner_started(workspace, request_simple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        payload.event_type = "tampered"  # type: ignore[misc]


def test_argv_hash_deterministic() -> None:
    """同 argv は同 hash を返す (audit reproducibility)."""
    ws = RunnerWorkspace(run_id="r", workspace_id="0" * 32, workdir="/tmp")
    req1 = RunnerCommandRequest(argv=("/bin/echo", "a"), cwd="/tmp")
    req2 = RunnerCommandRequest(argv=("/bin/echo", "a"), cwd="/tmp")
    p1 = build_runner_started(ws, req1)
    p2 = build_runner_started(ws, req2)
    assert p1.argv_hash == p2.argv_hash


def test_argv_hash_distinguishes_different_argv() -> None:
    """異なる argv は異なる hash."""
    ws = RunnerWorkspace(run_id="r", workspace_id="0" * 32, workdir="/tmp")
    req1 = RunnerCommandRequest(argv=("/bin/echo", "a"), cwd="/tmp")
    req2 = RunnerCommandRequest(argv=("/bin/echo", "b"), cwd="/tmp")
    p1 = build_runner_started(ws, req1)
    p2 = build_runner_started(ws, req2)
    assert p1.argv_hash != p2.argv_hash


def test_no_raw_secret_in_payload() -> None:
    """AC-HARD-02 invariant: raw token / API key が payload に出現しない。

    scrubbed_env_keys は key 名のみ、value は含まない。
    """
    ws = RunnerWorkspace(run_id="r", workspace_id="0" * 32, workdir="/tmp")
    req = RunnerCommandRequest(
        argv=("/bin/echo", "ok"),
        cwd="/tmp",
        env_allowlist=frozenset({"OPENAI_API_KEY", "GITHUB_TOKEN"}),
    )
    result = RunnerCommandResult(
        exit_code=0,
        stdout_bytes=2,
        stderr_bytes=0,
        duration_seconds=0.1,
        timeout_reached=False,
        cancelled=False,
        scrubbed_env_keys=("OPENAI_API_KEY", "GITHUB_TOKEN"),
    )
    payload = build_runner_completed(ws, req, result)
    s = str(payload.to_dict())
    # Key names must appear (for audit), but no raw values
    assert "OPENAI_API_KEY" in s
    assert "GITHUB_TOKEN" in s
    # Pretend secret values that must NOT be in payload
    assert "sk-" not in s
    assert "ghs_" not in s
    assert "ghp_" not in s
