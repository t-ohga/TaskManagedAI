"""ContextSnapshot の snapshot_kind enum (Sprint 4 BL-0044)。

各 kind の運用意味 (`.claude/rules/agentrun-state-machine.md` §11):
- input: AgentRun 開始時の context (run_queued event 直後、status='gathering_context' or 'queued')
- pre_tool: tool 呼出 / runner 起動の直前 (provider_requested / runner_started event 直前)
- post_tool: tool 結果 / runner 結果 取得直後 (provider_responded / runner_completed event 直後)
- resume: blocked / provider_incomplete / validation_failed からの再開直前
  (retry / repair_retry_scheduled / approval_decided event 直前)
- final: terminal state (completed / failed / cancelled / provider_refused / repair_exhausted) 直前または直後

snapshot_kind は AgentRunEvent と同期する: 各 snapshot は対応する event の前後で
作成され、provider_continuation_ref / repo_state / evidence_set_hash の差分追跡に
使う。
"""

from __future__ import annotations

from typing import Literal

SnapshotKind = Literal["input", "pre_tool", "post_tool", "resume", "final"]

ALL_SNAPSHOT_KINDS: tuple[SnapshotKind, ...] = (
    "input",
    "pre_tool",
    "post_tool",
    "resume",
    "final",
)


__all__ = [
    "ALL_SNAPSHOT_KINDS",
    "SnapshotKind",
]

