"""Sprint 7 BL-0079: Runner audit event builder.

DD-04 §audit + AgentRunEvent contract (Sprint 4 で予約済):

- `runner_started`: run_command 起動時 (workspace, command intent metadata)
- `runner_completed`: 正常終了 (exit_code, duration, output bytes, scrubbed env keys)
- `runner_blocked`: dangerous_command / forbidden_path / resource_cap /
  network_egress で deny された時

raw secret / raw token / file content は payload に含めず、`pattern hit 種別` /
`reason_code` / sha256 hash のみ記録 (AC-HARD-02 secret canary 防御)。

server-owned-boundary §1:
- payload 構築は server (orchestrator) のみが行う。caller (AgentRun service)
  は RunnerCommandResult / 例外 message から build_* で payload を生成。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from backend.app.services.runner.runner_adapter import (
    RunnerCommandRequest,
    RunnerCommandResult,
    RunnerWorkspace,
)


@dataclass(frozen=True, slots=True)
class RunnerAuditPayload:
    """raw secret / raw token を含まない、audit_events に乗せる payload。

    AgentRunEvent.payload (jsonb) に直接 dump 可能な dict 表現を持つ。
    """

    event_type: str  # one of: runner_started / runner_completed / runner_blocked
    workspace_id: str
    run_id: str
    argv_basename: str  # /bin/echo → echo
    argv_hash: str  # sha256(argv) 16-char prefix (audit trail)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event_type": self.event_type,
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "argv_basename": self.argv_basename,
            "argv_hash": self.argv_hash,
        }
        d.update(self.extra)
        return d


def _argv_hash(argv: tuple[str, ...]) -> str:
    """sha256(argv joined) 16-char prefix。raw 値は記録せず audit trail のみ。"""
    joined = "\x00".join(argv)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _argv_basename(argv: tuple[str, ...]) -> str:
    """argv[0] basename only (e.g., /bin/echo → echo)。"""
    import os.path

    if not argv:
        return ""
    return os.path.basename(argv[0])


def build_runner_started(
    workspace: RunnerWorkspace,
    request: RunnerCommandRequest,
) -> RunnerAuditPayload:
    """run_command 起動直前に build。argv raw は含めず basename + hash のみ。"""
    return RunnerAuditPayload(
        event_type="runner_started",
        workspace_id=workspace.workspace_id,
        run_id=workspace.run_id,
        argv_basename=_argv_basename(request.argv),
        argv_hash=_argv_hash(request.argv),
        extra={
            "cwd_inside_workspace": True,  # cwd containment は run_command 内で verify 済前提
            "env_allowlist_count": len(request.env_allowlist),
        },
    )


def build_runner_completed(
    workspace: RunnerWorkspace,
    request: RunnerCommandRequest,
    result: RunnerCommandResult,
) -> RunnerAuditPayload:
    """run_command 正常終了 (terminate / timeout 含む) で build。raw stdout/stderr
    は含めず byte count + scrubbed_env_keys (key 名のみ) を audit。"""
    return RunnerAuditPayload(
        event_type="runner_completed",
        workspace_id=workspace.workspace_id,
        run_id=workspace.run_id,
        argv_basename=_argv_basename(request.argv),
        argv_hash=_argv_hash(request.argv),
        extra={
            "exit_code": result.exit_code,
            "stdout_bytes": result.stdout_bytes,
            "stderr_bytes": result.stderr_bytes,
            "duration_seconds": result.duration_seconds,
            "timeout_reached": result.timeout_reached,
            "cancelled": result.cancelled,
            "output_cap_exceeded": result.output_cap_exceeded,
            "scrubbed_env_keys": list(result.scrubbed_env_keys),
        },
    )


def build_runner_blocked(
    workspace: RunnerWorkspace,
    request: RunnerCommandRequest,
    reason_code: str,
    *,
    deny_category: str,  # one of: dangerous_command / forbidden_path / resource_cap / network_egress
) -> RunnerAuditPayload:
    """run_command が deny で reject された時 build。reason_code は enum 値、
    raw 値 (path / argv contents) は含めない (AC-HARD-02 invariant)。"""
    valid_categories = frozenset(
        {
            "dangerous_command",
            "forbidden_path",
            "resource_cap",
            "network_egress",
            "cwd_outside",
            "empty_argv",
        }
    )
    if deny_category not in valid_categories:
        raise ValueError(
            f"deny_category must be one of {valid_categories}, got {deny_category!r}"
        )

    return RunnerAuditPayload(
        event_type="runner_blocked",
        workspace_id=workspace.workspace_id,
        run_id=workspace.run_id,
        argv_basename=_argv_basename(request.argv),
        argv_hash=_argv_hash(request.argv),
        extra={
            "deny_category": deny_category,
            "reason_code": reason_code,
        },
    )


__all__ = [
    "RunnerAuditPayload",
    "build_runner_blocked",
    "build_runner_completed",
    "build_runner_started",
]
