"""SP-014 batch 0a: AgentRunEvent event_type 28 -> 37.

Adds the P0.1 multi-agent orchestration event types required by
ADR-00014 / SP-014 before lease/failover services start appending them.

Revision ID: 0025_sp014_event_type_37
Revises: 0024_multi_agent_foundation_e
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_sp014_event_type_37"
down_revision: str | None = "0024_multi_agent_foundation_e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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

EVENT_TYPE_28_CHECK = (
    "event_type in ("
    "'run_queued','context_gathered','provider_requested','provider_responded',"
    "'artifact_generated','schema_validated','validation_failed',"
    "'repair_retry_scheduled','policy_linted','policy_blocked','budget_blocked',"
    "'runtime_blocked','diff_ready','approval_requested','approval_decided',"
    "'runner_started','runner_completed','runner_blocked','repo_pr_opened',"
    "'run_completed','run_failed','run_cancelled',"
    "'repair_exhausted','trust_level_promoted','trust_level_promotion_denied',"
    "'cli_invocation_started','cli_process_completed','cli_decision_recorded'"
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
        EVENT_TYPE_37_CHECK,
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
        EVENT_TYPE_28_CHECK,
    )
