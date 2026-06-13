from __future__ import annotations

from collections.abc import Mapping

from backend.app.domain.agent_runtime.event_type import AgentRunEventType
from backend.app.domain.agent_runtime.run_mode import RunMode
from backend.app.domain.agent_runtime.status import (
    ALL_AGENT_RUN_STATUSES,
    TERMINAL_STATES,
    AgentRunStatus,
    BlockedReason,
)

# SP-004-5 (ADR-00057 R2-F1/R2-F2/R4-F1): worker driver が queued shadow run を
# end-to-end 駆動するにあたり、不変条件「**driver-reachable な全 non-terminal state は
# `failed` (error 終端) と `cancelled` (cancel 終端) へ exit できる**」を満たすため、
# driver が post-commit で取り得る transient state ``queued`` / ``gathering_context`` /
# ``generated_artifact`` / ``schema_validated`` / ``validation_failed`` から ``failed``
# (R4-F1: error→failed が全 state で終端化可能、driver transient での例外 stuck 防止 +
# R2-F1: enqueue dispatch 失敗の補償 ``queued -> failed``) と ``cancelled`` (R2-F2:
# cancel entrypoint 統一で queued/transient からの cancel が regress しないよう許可) を
# additive 追加する。production-only pipeline state (``policy_linted`` / ``diff_ready`` /
# ``waiting_approval``) は shadow driver が SHADOW_FORBIDDEN により進入しないため本 slice
# では拡張しない (production runtime Sprint で対応)。16 status enum / event exact set は
# 不変 (新 status / 新 event_type なし、``run_failed`` / ``run_cancelled`` は既存)。
ALLOWED_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    "queued": frozenset({"gathering_context", "failed", "cancelled"}),
    "gathering_context": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset(
        {
            "generated_artifact",
            "provider_refused",
            "provider_incomplete",
            "blocked",
            "failed",
            "cancelled",
            "completed",
        }
    ),
    "generated_artifact": frozenset(
        {"schema_validated", "validation_failed", "failed", "cancelled"}
    ),
    "schema_validated": frozenset({"policy_linted", "failed", "cancelled"}),
    "policy_linted": frozenset({"diff_ready", "blocked"}),
    "diff_ready": frozenset({"waiting_approval", "blocked"}),
    "waiting_approval": frozenset({"running", "blocked", "cancelled"}),
    "blocked": frozenset({"waiting_approval", "running", "failed", "cancelled"}),
    "provider_refused": frozenset(),
    "provider_incomplete": frozenset({"running", "failed", "cancelled"}),
    "validation_failed": frozenset({"running", "repair_exhausted", "failed", "cancelled"}),
    "repair_exhausted": frozenset(),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

# SP-029 shadow mode (ADR-00055): run_mode='shadow' のみで許可される追加 edge。
# shadow run は副作用 stage (waiting_approval / runner / repo) を通らないため、
# 非 mutating な schema_validated から直接 completed へ run_completed で遷移できる。
# production はこの edge を使えない (従来の waiting_approval -> running -> completed 必須)。
# 新 status / 新 event_type は増やさない (16 status 不変、run_completed 既存)。
SHADOW_EXTRA_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    "schema_validated": frozenset({"completed"}),
}

# SP-029 (Codex App F-3): shadow run は side-effect pipeline (policy_lint -> diff_ready ->
# approval -> runner/repo) に **進入してはならない**。shadow は base transition を継承しつつ、
# pipeline 進入 edge と running->completed の検証 skip shortcut を **禁止** し、合法 path を
# queued..schema_validated -> completed (+ blocked/cancelled/failed/provider_* exit) に confine
# する。choke point guard (approval/broker/run_cost/run_update) と二重に side-effect 隔離する。
SHADOW_FORBIDDEN_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    "running": frozenset({"completed"}),  # 検証 skip の shortcut 禁止 (validated path 必須)
    "schema_validated": frozenset({"policy_linted"}),  # side-effect pipeline 進入禁止
    "policy_linted": frozenset({"diff_ready"}),
    "diff_ready": frozenset({"waiting_approval"}),
    "waiting_approval": frozenset({"running"}),
}

EVENT_TYPE_FOR_TRANSITION: Mapping[
    tuple[AgentRunStatus | None, AgentRunStatus],
    frozenset[AgentRunEventType],
] = {
    (None, "queued"): frozenset({"run_queued"}),
    ("queued", "gathering_context"): frozenset({"context_gathered"}),
    ("gathering_context", "running"): frozenset({"provider_requested"}),
    ("running", "generated_artifact"): frozenset({"provider_responded", "artifact_generated"}),
    ("generated_artifact", "schema_validated"): frozenset({"schema_validated"}),
    ("generated_artifact", "validation_failed"): frozenset({"validation_failed"}),
    ("schema_validated", "policy_linted"): frozenset({"policy_linted"}),
    # SP-029 shadow mode (ADR-00055): shadow run の合法 terminal (run_mode-gated は
    # validate_transition で enforce、event type は既存 run_completed)。
    ("schema_validated", "completed"): frozenset({"run_completed"}),
    ("policy_linted", "diff_ready"): frozenset({"diff_ready"}),
    ("diff_ready", "waiting_approval"): frozenset({"approval_requested"}),
    ("waiting_approval", "running"): frozenset({"approval_decided"}),
    ("running", "completed"): frozenset({"run_completed"}),
    ("running", "failed"): frozenset({"run_failed"}),
    ("running", "cancelled"): frozenset({"run_cancelled"}),
    ("running", "provider_refused"): frozenset({"provider_responded"}),
    ("running", "provider_incomplete"): frozenset({"provider_responded"}),
    ("running", "blocked"): frozenset(
        {"policy_blocked", "budget_blocked", "runtime_blocked"}
    ),
    ("policy_linted", "blocked"): frozenset({"policy_blocked"}),
    ("diff_ready", "blocked"): frozenset({"policy_blocked", "budget_blocked"}),
    ("waiting_approval", "blocked"): frozenset({"policy_blocked"}),
    ("waiting_approval", "cancelled"): frozenset({"run_cancelled"}),
    ("validation_failed", "running"): frozenset({"repair_retry_scheduled"}),
    # Sprint 5.5 update (SP55-B1-R2-F-001 fix): the terminal repair-exhaustion
    # transition MUST be witnessed by the dedicated ``repair_exhausted`` event
    # introduced in ADR-00004 §Sprint 5.5 update (event #23). Allowing
    # ``validation_failed`` or ``run_failed`` here would hide repair-exhaustion
    # as a generic failure in audit trails.
    ("validation_failed", "repair_exhausted"): frozenset({"repair_exhausted"}),
    ("provider_incomplete", "running"): frozenset({"repair_retry_scheduled"}),
    ("provider_incomplete", "failed"): frozenset({"run_failed"}),
    ("provider_incomplete", "cancelled"): frozenset({"run_cancelled"}),
    ("blocked", "waiting_approval"): frozenset({"approval_requested"}),
    ("blocked", "running"): frozenset({"approval_decided", "repair_retry_scheduled"}),
    ("blocked", "failed"): frozenset({"run_failed"}),
    ("blocked", "cancelled"): frozenset({"run_cancelled"}),
    # SP-004-5 (ADR-00057 R2-F1/R2-F2/R4-F1): driver-reachable transient state からの
    # ``failed`` (error 終端 + enqueue dispatch 補償) / ``cancelled`` (cancel entrypoint
    # 統一) 終端。event type は既存 ``run_failed`` / ``run_cancelled`` (event exact set 不変)。
    ("queued", "failed"): frozenset({"run_failed"}),
    ("queued", "cancelled"): frozenset({"run_cancelled"}),
    ("gathering_context", "failed"): frozenset({"run_failed"}),
    ("gathering_context", "cancelled"): frozenset({"run_cancelled"}),
    ("generated_artifact", "failed"): frozenset({"run_failed"}),
    ("generated_artifact", "cancelled"): frozenset({"run_cancelled"}),
    ("schema_validated", "failed"): frozenset({"run_failed"}),
    ("schema_validated", "cancelled"): frozenset({"run_cancelled"}),
    ("validation_failed", "failed"): frozenset({"run_failed"}),
    ("validation_failed", "cancelled"): frozenset({"run_cancelled"}),
}

BLOCKED_EVENT_TYPE_REASON_MAPPING: Mapping[AgentRunEventType, BlockedReason] = {
    "policy_blocked": "policy_blocked",
    "budget_blocked": "budget_blocked",
    "runtime_blocked": "runtime_blocked",
}


def validate_transition(
    from_state: AgentRunStatus,
    to_state: AgentRunStatus,
    run_mode: RunMode = "production",
) -> AgentRunStatus:
    if from_state not in ALL_AGENT_RUN_STATUSES:
        raise ValueError(f"unknown AgentRun from_state: {from_state!r}")
    if to_state not in ALL_AGENT_RUN_STATUSES:
        raise ValueError(f"unknown AgentRun to_state: {to_state!r}")
    if from_state in TERMINAL_STATES:
        raise ValueError(f"terminal AgentRun state cannot transition: {from_state!r}")

    # SP-029 (ADR-00055): shadow run のみ SHADOW_EXTRA_TRANSITIONS の追加 edge を許可する。
    # production は ALLOWED_TRANSITIONS のみ (shadow 専用 edge を使えない = run_mode-gated)。
    # さらに shadow は SHADOW_FORBIDDEN_TRANSITIONS (side-effect pipeline 進入 + 検証 skip
    # shortcut) を base から **除外** する (Codex App F-3、合法 path を validated terminal に confine)。
    allowed_to_states = ALLOWED_TRANSITIONS[from_state]
    if run_mode == "shadow":
        allowed_to_states = (
            allowed_to_states | SHADOW_EXTRA_TRANSITIONS.get(from_state, frozenset())
        ) - SHADOW_FORBIDDEN_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed_to_states:
        allowed = ", ".join(sorted(allowed_to_states)) or "<none>"
        raise ValueError(
            f"AgentRun transition {from_state!r} -> {to_state!r} is not allowed "
            f"(run_mode={run_mode!r}); allowed to_states: {allowed}"
        )

    return to_state


def validate_event_type_for_transition(
    from_state: AgentRunStatus | None,
    to_state: AgentRunStatus,
    event_type: AgentRunEventType,
) -> None:
    """event_type が transition (from_state, to_state) に対応する許可 mapping か確認。"""

    allowed = EVENT_TYPE_FOR_TRANSITION.get((from_state, to_state))
    if allowed is None:
        raise ValueError(
            f"transition {from_state}->{to_state} not in EVENT_TYPE_FOR_TRANSITION mapping"
        )
    if event_type not in allowed:
        raise ValueError(
            f"event_type {event_type!r} not allowed for transition "
            f"{from_state}->{to_state}; allowed: {sorted(allowed)}"
        )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "BLOCKED_EVENT_TYPE_REASON_MAPPING",
    "EVENT_TYPE_FOR_TRANSITION",
    "SHADOW_EXTRA_TRANSITIONS",
    "SHADOW_FORBIDDEN_TRANSITIONS",
    "validate_event_type_for_transition",
    "validate_transition",
]

