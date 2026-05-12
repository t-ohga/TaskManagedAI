"""Extend agent_run_events.event_type CHECK from 25 to 28 (add 3 cli_* events).

Revision ID: 0013_cli_event_type_28
Revises: 0012_cli_artifact_kind_11
Create Date: 2026-05-13 00:00:00.000000

Sprint 6 BL-0067 (ADR-00003 §A boundary): CLI artifact orchestration の 3 種
event_type を agent_run_events.event_type CHECK 制約に追加する additive
migration.

Added events:
- cli_invocation_started: launcher が subprocess を spawn 直後
- cli_process_completed: exit / timeout / cancelled 後の集約 event
- cli_decision_recorded: adopt / reject / defer 採否判定の audit

Existing 25 events は **不変** (additive only、ADR Gate Criteria #8 非該当)。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_cli_event_type_28"
down_revision: str | None = "0012_cli_artifact_kind_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: SQL CHECK conditions are kept as inline string literals so that test
# helpers can parse them via AST. Adding a new event_type requires updating
# BOTH the literal here AND
# ``backend/app/domain/agent_runtime/event_type.py:AgentRunEventType`` /
# ``ALL_AGENT_RUN_EVENT_TYPES`` (5+ source integrity,
# `.claude/rules/cross-source-enum-integrity.md` §1).

_EVENT_TYPE_28_CHECK_SQL = (
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

_EVENT_TYPE_25_CHECK_SQL = (
    "event_type in ("
    "'run_queued','context_gathered','provider_requested','provider_responded',"
    "'artifact_generated','schema_validated','validation_failed',"
    "'repair_retry_scheduled','policy_linted','policy_blocked','budget_blocked',"
    "'runtime_blocked','diff_ready','approval_requested','approval_decided',"
    "'runner_started','runner_completed','runner_blocked','repo_pr_opened',"
    "'run_completed','run_failed','run_cancelled',"
    "'repair_exhausted','trust_level_promoted','trust_level_promotion_denied'"
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
        _EVENT_TYPE_28_CHECK_SQL,
    )


def downgrade() -> None:
    # cli_* event を持つ既存 row は CHECK violation で downgrade 失敗する。
    # rollback caller は agent_run_events の cli_* row を先に削除または別 table
    # に move してから downgrade する。
    op.drop_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        _EVENT_TYPE_25_CHECK_SQL,
    )
