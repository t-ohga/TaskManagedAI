"""Add temporal order check to approval_requests.

Revision ID: 0007_approval_temporal_check
Revises: 0006_approval_policy_decisions
Create Date: 2026-05-09 00:00:00.000000

F-004 (Sprint 3 Batch 4 R2 fix): decided_at >= requested_at を DB CHECK で強制し、
負値 wait_ms を使った approval_wait_ms KPI gaming を防ぐ。

前提:
  P0 では本 migration 適用時点で approval_requests に既存 row はない (Sprint 3 で
  table 新設)。万が一 staging / dev 環境で既存 row が CHECK 違反した場合、
  upgrade() は IntegrityError で失敗する。その場合は:
    1. 違反 row を SQL で identify: SELECT id, requested_at, decided_at FROM approval_requests
       WHERE decided_at IS NOT NULL AND decided_at < requested_at;
    2. データ修正 (decided_at を requested_at 以後に補正、または該当 approval を
       expired/invalidated に変更)
    3. 再度 alembic upgrade head を実行
  破壊的バックフィルは P0 では行わない (ADR-00008 backup/restore drill 範疇)。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_approval_temporal_check"
down_revision: str | None = "0006_approval_policy_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """F-004: decided_at must be >= requested_at で負値 wait_ms gaming を防ぐ。

    既存違反 row 想定: P0 では table 新設直後で row 0 件、CHECK 違反は発生しない。
    staging / dev で既存 row が違反する場合は module docstring 参照。
    """

    op.create_check_constraint(
        "approval_requests_ck_decided_at_after_requested_at",
        "approval_requests",
        "decided_at IS NULL OR decided_at >= requested_at",
    )


def downgrade() -> None:
    op.drop_constraint(
        "approval_requests_ck_decided_at_after_requested_at",
        "approval_requests",
        type_="check",
    )
