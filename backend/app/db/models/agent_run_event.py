from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import Base, TenantIdMixin
from backend.app.domain.agent_runtime.event_type import AgentRunEventType

JsonDict = dict[str, Any]

# Codex SP6B2 R1 F-007 (MEDIUM) adopt: repository scanner の
# ``_PROHIBITED_PAYLOAD_KEYS`` と完全一致する 21 keys を DB CHECK で防御。
# Sprint 6 batch 2 で 18 -> 21 へ拡張 (`secret_capability_token`,
# `raw_token`, `session_token` を追加)。
_PROHIBITED_EVENT_PAYLOAD_KEYS: tuple[str, ...] = (
    "api_key",
    "api_token",
    "raw_secret",
    "secret",
    "secret_value",
    "private_key",
    "auth_token",
    "bearer_token",
    "capability_token",
    "capability_token_value",
    "provider_key",
    "github_installation_token",
    "github_app_private_key",
    "tailscale_auth_key",
    "sops_age_key",
    "age_private_key",
    "canary_value",
    "raw_canary",
    "secret_capability_token",
    "raw_token",
    "session_token",
)


def _prohibited_event_payload_keys_jsonpath() -> str:
    disjunction = " || ".join(
        f'@.key == "{key}"' for key in _PROHIBITED_EVENT_PAYLOAD_KEYS
    )
    return (
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'"
    )


class AgentRunEvent(TenantIdMixin, Base):
    """AgentRun lifecycle event (append-only).

    event_payload は acyclic JSON-serializable な dict / list / str / int / float / bool / null
    のみを受け付ける。循環参照や深さ 32 以上のネストは ValueError で reject される
    (詳細は backend/app/repositories/agent_run_event.py の _assert_no_raw_secret_value)。

    raw secret / provider key / capability token / canary 生値 (key, value どちらも) は
    repository 層で 21 種 prohibited key + 8 regex pattern により reject される
    (defense-in-depth として migration 0008 + 0014 の DB CHECK でも nested 含む全 path で同一 key set を reject)。
    Sprint 6 batch 2 で 18 -> 21 へ拡張 (Codex SP6B2 R1 F-007)。
    """

    __tablename__ = "agent_run_events"
    __table_args__ = (
        sa.CheckConstraint(
            "event_type in "
            "('run_queued','context_gathered','provider_requested','provider_responded',"
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
            "'emergency_stop_resumed')",
            name="agent_run_events_ck_event_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(event_payload) = 'object'",
            name="agent_run_events_ck_event_payload_object",
        ),
        sa.CheckConstraint(
            "not jsonb_path_exists(event_payload, "
            f"{_prohibited_event_payload_keys_jsonpath()}::jsonpath)",
            name="agent_run_events_ck_no_prohibited_payload_keys",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="agent_run_events_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.id"],
            name="agent_run_events_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="agent_run_events_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="agent_run_events_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "seq_no",
            name="agent_run_events_uq_tenant_run_seq_no",
        ),
        sa.Index(
            "agent_run_events_uq_tenant_run_idempotency_key",
            "tenant_id",
            "run_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text("idempotency_key is not null"),
        ),
        sa.Index("agent_run_events_idx_tenant_run_created", "tenant_id", "run_id", "created_at"),
        {
            "comment": (
                "AgentRunEvent payload contract: no raw secret, provider key, "
                "capability token, or canary raw values. Repository append enforces "
                "recursive prohibited-key scan plus raw secret/token pattern checks."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    seq_no: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    event_type: Mapped[AgentRunEventType] = mapped_column(sa.Text, nullable=False)
    event_payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


__all__ = ["AgentRunEvent"]

