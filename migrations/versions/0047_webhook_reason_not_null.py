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
    # preflight remediation: 旧 CHECK は NULL semantics で status='quarantined' AND
    # quarantine_reason IS NULL を許していた。新 CHECK (IS NOT NULL) を貼る前にその legacy 状態の
    # row を generic な 'parse_validation_failed' へ coerce する。parser は status='quarantined' の
    # とき必ず reason を設定するため production では 0 件想定だが、直接書込 / 旧 parser バグ経路 /
    # 手動修復 等の anomaly row が 1 件でも残っていると create_check_constraint が失敗して
    # deployment 全体を block するため、それを防ぐ (auditable に最も汎用な失敗理由へ寄せる)。
    op.execute(
        "update github_webhook_events "
        "set quarantine_reason = 'parse_validation_failed' "
        "where status = 'quarantined' and quarantine_reason is null"
    )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _NEW)


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _OLD)
