"""GitHub webhook event row (ADR-00050 SP-028)。

verification accepted 後の **best-effort read-only enrichment** で保存する、PR / CI イベントの
非機密 field のみを持つ table。既存 webhook ingress security contract (verifier / secret resolver /
replay store) は変更しない (ADR-00050 §前提)。

- ``status='accepted'`` のみ通常 feed (project-scoped read endpoint)。``status='quarantined'`` は
  repository 解決失敗 / parser・header validation 失敗を記録 (repository_id は NULL)。
- 全 string field は DB CHECK length を持ち parser の bound と同一定数で揃える (5+ source 整合、R1 F-010)。
- 複合 FK ``(tenant_id, repository_id) -> repositories(tenant_id, id)`` は migration 側で
  ``ON DELETE SET NULL (repository_id)`` (PostgreSQL 16 column-list、tenant_id は NULL 化しない、R1 F-003)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, CreatedAtMixin, TenantIdMixin

# ADR-00050: 5+ source 整合 (DB CHECK in migrations/versions/0044 / Pydantic / pytest EXPECTED) の
# Python Literal 側。

WebhookEventKind = Literal[
    "pull_request", "check_run", "check_suite", "status", "push"
]
WEBHOOK_EVENT_KINDS: tuple[WebhookEventKind, ...] = (
    "pull_request",
    "check_run",
    "check_suite",
    "status",
    "push",
)

WebhookEventStatus = Literal["accepted", "quarantined"]
WEBHOOK_EVENT_STATUSES: tuple[WebhookEventStatus, ...] = ("accepted", "quarantined")

# ADR-00050 R2 F-004: 全 quarantine 経路を網羅 (repository lookup + parser/header validation)。
# hash mismatch は audit-only で row 非作成のため enum に含めない (R2 F-003)。
WebhookQuarantineReason = Literal[
    "unregistered_repo",
    "repo_lookup_ambiguous",
    "payload_shape_mismatch",
    "header_event_mismatch",
    "parse_validation_failed",
]
WEBHOOK_QUARANTINE_REASONS: tuple[WebhookQuarantineReason, ...] = (
    "unregistered_repo",
    "repo_lookup_ambiguous",
    "payload_shape_mismatch",
    "header_event_mismatch",
    "parse_validation_failed",
)

# parser の bound と DB CHECK length を揃える単一定数 (R1 F-010)。
DELIVERY_ID_MAX_LENGTH = 100
ACTION_MAX_LENGTH = 64
EXTERNAL_REF_MAX_LENGTH = 255
STATE_MAX_LENGTH = 32
TITLE_MAX_LENGTH = 512
SENDER_LOGIN_MAX_LENGTH = 64


class GitHubWebhookEvent(TenantIdMixin, CreatedAtMixin, Base):
    """GitHub webhook event row (ADR-00050 SP-028、best-effort enrichment)。"""

    __tablename__ = "github_webhook_events"
    __table_args__ = (
        # 再配信 dedup (GitHub redelivery 冪等化)。conflict 時は payload_hash 比較 (R2 F-002/F-003)。
        sa.UniqueConstraint(
            "tenant_id",
            "delivery_id",
            name="github_webhook_events_uq_tenant_delivery",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="github_webhook_events_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        # 複合 FK は migration 側で ON DELETE SET NULL (repository_id) を column-list で付与 (R1 F-003)。
        # ORM 側は metadata のみ (alembic upgrade が DDL の正本、create_all は使わない)。
        sa.ForeignKeyConstraint(
            ["tenant_id", "repository_id"],
            ["repositories.tenant_id", "repositories.id"],
            name="github_webhook_events_repository_fkey",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "event_kind IN ('pull_request', 'check_run', 'check_suite', 'status', 'push')",
            name="github_webhook_events_event_kind_check",
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'quarantined')",
            name="github_webhook_events_status_check",
        ),
        # status='quarantined' のときのみ reason NOT NULL かつ enum、accepted は reason NULL (R2 F-004)。
        sa.CheckConstraint(
            "(status = 'accepted' AND quarantine_reason IS NULL) "
            "OR (status = 'quarantined' AND quarantine_reason IN "
            "('unregistered_repo', 'repo_lookup_ambiguous', 'payload_shape_mismatch', "
            "'header_event_mismatch', 'parse_validation_failed'))",
            name="github_webhook_events_quarantine_reason_check",
        ),
        sa.CheckConstraint(
            "length(delivery_id) > 0 AND length(delivery_id) <= 100",
            name="github_webhook_events_delivery_id_length_check",
        ),
        sa.CheckConstraint(
            "action IS NULL OR length(action) <= 64",
            name="github_webhook_events_action_length_check",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(external_ref) <= 255",
            name="github_webhook_events_external_ref_length_check",
        ),
        sa.CheckConstraint(
            "state IS NULL OR length(state) <= 32",
            name="github_webhook_events_state_length_check",
        ),
        sa.CheckConstraint(
            "title IS NULL OR length(title) <= 512",
            name="github_webhook_events_title_length_check",
        ),
        sa.CheckConstraint(
            "sender_login IS NULL OR length(sender_login) <= 64",
            name="github_webhook_events_sender_login_length_check",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="github_webhook_events_uq_tenant_id"
        ),
        # project-scoped read feed query 用 (R1 F-012)。quarantine (repository_id NULL) は join で除外。
        sa.Index(
            "github_webhook_events_ix_feed",
            "tenant_id",
            "status",
            "repository_id",
            sa.text("received_at DESC"),
            sa.text("id DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    repository_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    delivery_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    event_kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    quarantine_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    action: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    state: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    title: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    sender_login: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


__all__ = [
    "ACTION_MAX_LENGTH",
    "DELIVERY_ID_MAX_LENGTH",
    "EXTERNAL_REF_MAX_LENGTH",
    "SENDER_LOGIN_MAX_LENGTH",
    "STATE_MAX_LENGTH",
    "TITLE_MAX_LENGTH",
    "WEBHOOK_EVENT_KINDS",
    "WEBHOOK_EVENT_STATUSES",
    "WEBHOOK_QUARANTINE_REASONS",
    "GitHubWebhookEvent",
    "WebhookEventKind",
    "WebhookEventStatus",
    "WebhookQuarantineReason",
]
