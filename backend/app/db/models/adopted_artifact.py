from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    JsonDict,
    TenantIdMixin,
    rls_ready_metadata,
)

AdoptedArtifactState = Literal["draft", "final"]

_PROHIBITED_ADOPTED_ARTIFACT_METADATA_KEYS: tuple[str, ...] = (
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


def _prohibited_adopted_artifact_metadata_keys_jsonpath() -> str:
    disjunction = " || ".join(
        f'@.key == "{key}"' for key in _PROHIBITED_ADOPTED_ARTIFACT_METADATA_KEYS
    )
    return (
        "'strict $.** ? (@.type() == \"object\")."
        f"keyvalue() ? ({disjunction})'"
    )


class AdoptedArtifact(TenantIdMixin, Base):
    """Project-scoped attribution link for final-adopted artifacts."""

    __tablename__ = "adopted_artifacts"
    __table_args__ = (
        sa.CheckConstraint(
            "adoption_state in ('draft','final')",
            name="adopted_artifacts_ck_adoption_state",
        ),
        sa.CheckConstraint(
            "((adoption_state = 'final' and finalized_at is not null "
            "and adoption_event_id is not null) or "
            "(adoption_state = 'draft' and finalized_at is null "
            "and adoption_event_id is null))",
            name="adopted_artifacts_ck_final_event_consistency",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="adopted_artifacts_ck_metadata_object",
        ),
        sa.CheckConstraint(
            "not jsonb_path_exists(metadata, "
            f"{_prohibited_adopted_artifact_metadata_keys_jsonpath()}::jsonpath)",
            name="adopted_artifacts_ck_no_prohibited_metadata_keys",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="adopted_artifacts_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="adopted_artifacts_project_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "run_id"],
            ["agent_runs.tenant_id", "agent_runs.project_id", "agent_runs.id"],
            name="adopted_artifacts_run_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "artifact_id"],
            ["artifacts.tenant_id", "artifacts.project_id", "artifacts.id"],
            name="adopted_artifacts_artifact_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id", "adoption_event_id"],
            ["agent_run_events.tenant_id", "agent_run_events.run_id", "agent_run_events.id"],
            name="adopted_artifacts_adoption_event_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "adopted_by_actor_id"],
            ["actors.tenant_id", "actors.id"],
            name="adopted_artifacts_adopted_by_actor_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="adopted_artifacts_uq_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "id",
            name="adopted_artifacts_uq_tenant_project_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "run_id",
            "artifact_id",
            name="adopted_artifacts_uq_tenant_project_run_artifact",
        ),
        sa.Index(
            "adopted_artifacts_idx_final_project_run",
            "tenant_id",
            "project_id",
            "run_id",
            postgresql_where=sa.text("adoption_state = 'final'"),
        ),
        sa.Index(
            "adopted_artifacts_idx_final_artifact",
            "tenant_id",
            "project_id",
            "artifact_id",
            postgresql_where=sa.text("adoption_state = 'final'"),
        ),
        {
            "comment": (
                "Dedicated final-adopted artifact attribution table. "
                "citation_coverage uses only adoption_state='final' rows."
            )
        },
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    adoption_state: Mapped[AdoptedArtifactState] = mapped_column(
        sa.Text,
        nullable=False,
        default="final",
        server_default=sa.text("'final'"),
    )
    adoption_event_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    adopted_by_actor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    finalized_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    def __repr__(self) -> str:
        return (
            "AdoptedArtifact("
            f"id={self.id!s}, tenant_id={self.tenant_id!r}, "
            f"project_id={self.project_id!s}, adoption_state={self.adoption_state!r})"
        )


__all__ = ["AdoptedArtifact", "AdoptedArtifactState"]
