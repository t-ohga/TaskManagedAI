"""Add artifacts.trust_level column and extend agent_run_events.event_type to 25.

Revision ID: 0011_trust_level_event_25
Revises: 0010_budget_secret_runtime
Create Date: 2026-05-12 00:00:00.000000

Sprint 5.5 (Output Validator + Input Trust Layer) additive migration:
- artifacts.trust_level: NOT NULL DEFAULT 'untrusted_content' + CHECK
  ('untrusted_content','validated_artifact','trusted_instruction')
- agent_run_events.event_type CHECK: 22 -> 25 values (add 'repair_exhausted',
  'trust_level_promoted', 'trust_level_promotion_denied')

ADR-00004 / ADR-00009 Sprint 5.5 update (accepted 2026-05-12). Existing rows
backfill via DEFAULT, no destructive changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_trust_level_event_25"
down_revision: str | None = "0010_budget_secret_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: SQL CHECK conditions are kept as inline string literals so that test
# helpers (tests/runtime/test_agent_run_events.py and Sprint 5.5 batch 1
# additions) can parse them via AST without needing to evaluate Python code.
# Adding a new event_type requires updating both the literal here AND
# ``backend/app/domain/agent_runtime/event_type.py`` (5+ source integrity,
# `.claude/rules/cross-source-enum-integrity.md` §1).

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

_EVENT_TYPE_22_CHECK_SQL = (
    "event_type in ("
    "'run_queued','context_gathered','provider_requested','provider_responded',"
    "'artifact_generated','schema_validated','validation_failed',"
    "'repair_retry_scheduled','policy_linted','policy_blocked','budget_blocked',"
    "'runtime_blocked','diff_ready','approval_requested','approval_decided',"
    "'runner_started','runner_completed','runner_blocked','repo_pr_opened',"
    "'run_completed','run_failed','run_cancelled'"
    ")"
)

_TRUST_LEVEL_CHECK_SQL = (
    "trust_level in ('untrusted_content','validated_artifact','trusted_instruction')"
)


def upgrade() -> None:
    # 1) Extend agent_run_events.event_type CHECK 22 -> 25
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

    # 2) Add artifacts.trust_level (additive, DEFAULT backfills existing rows)
    op.add_column(
        "artifacts",
        sa.Column(
            "trust_level",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'untrusted_content'"),
        ),
    )
    op.create_check_constraint(
        "artifacts_ck_trust_level",
        "artifacts",
        _TRUST_LEVEL_CHECK_SQL,
    )


def downgrade() -> None:
    # 1) Drop artifacts.trust_level (column drop is the rollback shape; existing
    #    rows are lossless because all values were DEFAULT-backfilled).
    op.drop_constraint(
        "artifacts_ck_trust_level",
        "artifacts",
        type_="check",
    )
    op.drop_column("artifacts", "trust_level")

    # 2) Shrink event_type CHECK back to 22. Any rows already written with the
    #    new 3 enum values would violate the shrunken constraint; downgrade
    #    callers are expected to quarantine or reclassify per ADR-00004 rollback.
    op.drop_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        type_="check",
    )
    op.create_check_constraint(
        "agent_run_events_ck_event_type",
        "agent_run_events",
        _EVENT_TYPE_22_CHECK_SQL,
    )
