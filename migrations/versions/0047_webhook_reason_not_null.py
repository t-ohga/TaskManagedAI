"""github_webhook_events quarantine_reason CHECK tightening: quarantined → reason NOT NULL.

Revision ID: 0047_webhook_reason_not_null
Revises: 0046_sp027_source_trust
Create Date: 2026-06-12 00:00:00.000000

旧 CHECK は `(status='quarantined' AND quarantine_reason IN (...))` で、PostgreSQL の NULL=非違反
semantics により quarantined + reason NULL を素通りさせていた (model intent「quarantined のとき
reason NOT NULL」と不一致、直接 INSERT で実証)。`quarantine_reason IS NOT NULL` を追加して tightening
(constraint のみの enforce 強化、data migration なし)。parser は status='quarantined' のとき必ず
quarantine_reason を設定するため、production の既存 row は本制約を満たし影響なし。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047_webhook_reason_not_null"
down_revision: str | None = "0046_sp027_source_trust"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "github_webhook_events_quarantine_reason_check"
_TABLE = "github_webhook_events"

_OLD = (
    "(status = 'accepted' AND quarantine_reason IS NULL) "
    "OR (status = 'quarantined' AND quarantine_reason IN "
    "('unregistered_repo', 'repo_lookup_ambiguous', 'payload_shape_mismatch', "
    "'header_event_mismatch', 'parse_validation_failed'))"
)
_NEW = (
    "(status = 'accepted' AND quarantine_reason IS NULL) "
    "OR (status = 'quarantined' AND quarantine_reason IS NOT NULL "
    "AND quarantine_reason IN "
    "('unregistered_repo', 'repo_lookup_ambiguous', 'payload_shape_mismatch', "
    "'header_event_mismatch', 'parse_validation_failed'))"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _NEW)


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _OLD)
