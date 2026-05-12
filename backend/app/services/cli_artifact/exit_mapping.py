"""Sprint 6 BL-0067: exit_code → AgentRun status mapping + cli_process_completed
event payload.

Mapping rule (DD-04 + AgentRun 16 状態 + ADR-00003):

- success (exit_code == 0): status 維持 → 採否判定待ち。event=cli_process_completed
- non-zero exit (timeout=False, cancelled=False): failed terminal。+ run_failed
- timeout_reached=True: blocked + runtime_blocked (resume 可)。event=cli_process_completed
- cancelled=True: cancelled terminal。+ run_cancelled
- registry deny / binary_not_found (LauncherError): caller (orchestrator) 責任

server-owned-boundary §1 不変条件:

- caller は ``LauncherResult`` をそのまま渡す。result 値の上書きは launcher
  境界に閉じる (本 module は読み取り専用)。
- 戻り値の ``ExitMappingDecision`` は frozen で immutable。
- raw stdout / stderr text は payload に含めない。``RedactionResult.summary_payload``
  経由で hash + hit metadata だけを記録する。

cli_process_completed event payload (rules/agentrun-state-machine §6 amendment):

- agent_name (registry agent identifier)
- exit_code (int | None)
- signal (str | None, e.g. "SIGTERM")
- duration_seconds (float)
- timeout_reached (bool)
- cancelled (bool)
- stdout_bytes (int, RedactionResult.raw_bytes_length)
- stderr_bytes (int, RedactionResult.raw_bytes_length)
- stdout_redacted_hash (sha256 hex)
- stderr_redacted_hash (sha256 hex)
- redaction_hit_count (sum of pattern hits across stdout + stderr)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

from backend.app.services.cli_artifact.launcher import LauncherResult
from backend.app.services.cli_artifact.redaction import RedactionResult


class CliExitOutcome(StrEnum):
    SUCCESS = "success"  # exit_code == 0, status は変更しない (採否判定待ち)
    FAILED = "failed"  # exit_code != 0 で terminal `failed` に
    TIMEOUT = "timeout"  # `blocked` + `runtime_blocked` (非 terminal、resume 可)
    CANCELLED = "cancelled"  # `cancelled` terminal


@dataclass(frozen=True, slots=True)
class ExitMappingDecision:
    outcome: CliExitOutcome
    next_status: str  # AgentRun status value (literal `running` / `failed` / `blocked` / `cancelled`)
    blocked_reason: str | None  # `runtime_blocked` (timeout 時) or None
    is_terminal: bool


class CliProcessCompletedPayload(TypedDict):
    """``cli_process_completed`` event の必須 payload。raw 値 非含。"""

    agent_name: str
    exit_code: int | None
    signal: str | None
    duration_seconds: float
    timeout_reached: bool
    cancelled: bool
    stdout_bytes: int
    stderr_bytes: int
    stdout_redacted_hash: str
    stderr_redacted_hash: str
    redaction_hit_count: int
    outcome: str


def map_launcher_result(result: LauncherResult) -> ExitMappingDecision:
    """LauncherResult を AgentRun status へ mapping する。

    Priority: cancelled > timeout > non-zero exit > success。
    """

    if result.cancelled:
        return ExitMappingDecision(
            outcome=CliExitOutcome.CANCELLED,
            next_status="cancelled",
            blocked_reason=None,
            is_terminal=True,
        )
    if result.timeout_reached:
        return ExitMappingDecision(
            outcome=CliExitOutcome.TIMEOUT,
            next_status="blocked",
            blocked_reason="runtime_blocked",
            is_terminal=False,
        )
    if result.exit_code is not None and result.exit_code != 0:
        return ExitMappingDecision(
            outcome=CliExitOutcome.FAILED,
            next_status="failed",
            blocked_reason=None,
            is_terminal=True,
        )
    # success: status は呼び元 (orchestrator) が保持。採否判定 (BL-0068) で
    # 次状態が決まるまで `running` のまま。
    return ExitMappingDecision(
        outcome=CliExitOutcome.SUCCESS,
        next_status="running",
        blocked_reason=None,
        is_terminal=False,
    )


def build_cli_process_completed_payload(
    *,
    result: LauncherResult,
    stdout_redaction: RedactionResult,
    stderr_redaction: RedactionResult,
    outcome: CliExitOutcome,
) -> CliProcessCompletedPayload:
    """cli_process_completed event の payload を組み立てる (raw 値非含)。"""

    redaction_hit_count = sum(h.match_count for h in stdout_redaction.hits) + sum(
        h.match_count for h in stderr_redaction.hits
    )
    return CliProcessCompletedPayload(
        agent_name=result.agent_name,
        exit_code=result.exit_code,
        signal=result.signal,
        duration_seconds=result.duration_seconds,
        timeout_reached=result.timeout_reached,
        cancelled=result.cancelled,
        stdout_bytes=stdout_redaction.raw_bytes_length,
        stderr_bytes=stderr_redaction.raw_bytes_length,
        stdout_redacted_hash=stdout_redaction.redacted_content_hash,
        stderr_redacted_hash=stderr_redaction.redacted_content_hash,
        redaction_hit_count=redaction_hit_count,
        outcome=outcome.value,
    )


__all__ = [
    "CliExitOutcome",
    "CliProcessCompletedPayload",
    "ExitMappingDecision",
    "build_cli_process_completed_payload",
    "map_launcher_result",
]
