"""SP-PHASE1 B1: AgentRunEvent event_type 37 -> 39 (emergency-stop witnessing).

Adds the two dedicated emergency-stop witnessing event types required by
ADR-00048 §Amendment A-5 (SP-PHASE1 kill switch, user 承認 2026-06-22):

- ``emergency_stop_engaged``: emergency-stop block transition
  (running / policy_linted / diff_ready / waiting_approval -> blocked,
  blocked_reason=runtime_blocked) を witness する。
- ``emergency_stop_resumed``: clear / resume transition
  (blocked -> pre_stop_status: running / policy_linted / diff_ready /
  waiting_approval) を witness する。

これらは **P0 event** として追加する (P0.1 sealed extension 29-37 とは別位置、
P0 sealed CI guard の `*event_type_37*` path に抵触しない)。additive のみ、
downgrade は lossless (37-list CHECK へ戻すだけ、新 event を使う行が無いこと前提)。

NOTE: 本 migration の event_type literal は **hardcode** している。Python Literal /
ORM CheckConstraint からの import に置き換えてはならない (cross-source-enum-integrity §1
の drift guard が「migration と他 source が独立に同じ enum を宣言する」ことで成立する)。

Revision ID: 0051_phase1_event_type_39
Revises: 0050_secret_material_lifecycle
Create Date: 2026-06-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0051_phase1_event_type_39"
down_revision: str | None = "0050_secret_material_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_TYPE_39_CHECK = (
    "event_type in ("
    "'run_queued','context_gathered','provider_requested','provider_responded',"
    "'artifact_generated','schema_validated','validation_failed',"
    "'repair_retry_scheduled','policy_linted','policy_blocked','budget_blocked',"
    "'runtime_blocked','diff_ready','approval_requested','approval_decided',"
    "'runner_started','runner_completed','runner_blocked','repo_pr_opened',"
    "'run_completed','run_failed','run_cancelled',"
    "'repair_exhausted','trust_level_promoted','trust_level_promotion_denied',"
    "'cli_invocation_started','cli_process_completed','cli_decision_recorded',"
    "'orchestrator_dispatched','orchestrator_lease_renewed',"
    "'orchestrator_lease_expired','orchestrator_failover_triggered',"
    "'orchestrator_kill_engaged','inter_agent_message_sent_ref',"
    "'inter_agent_message_consumed_ref','tool_web_fetch_executed',"
    "'tool_docs_search_executed','emergency_stop_engaged',"
    "'emergency_stop_resumed'"
    ")"
)

EVENT_TYPE_37_CHECK = (
    "event_type in ("
    "'run_queued','context_gathered','provider_requested','provider_responded',"
    "'artifact_generated','schema_validated','validation_failed',"
    "'repair_retry_scheduled','policy_linted','policy_blocked','budget_blocked',"
    "'runtime_blocked','diff_ready','approval_requested','approval_decided',"
    "'runner_started','runner_completed','runner_blocked','repo_pr_opened',"
    "'run_completed','run_failed','run_cancelled',"
    "'repair_exhausted','trust_level_promoted','trust_level_promotion_denied',"
    "'cli_invocation_started','cli_process_completed','cli_decision_recorded',"
    "'orchestrator_dispatched','orchestrator_lease_renewed',"
    "'orchestrator_lease_expired','orchestrator_failover_triggered',"
    "'orchestrator_kill_engaged','inter_agent_message_sent_ref',"
    "'inter_agent_message_consumed_ref','tool_web_fetch_executed',"
    "'tool_docs_search_executed'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        EVENT_TYPE_39_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        EVENT_TYPE_37_CHECK,
    )
