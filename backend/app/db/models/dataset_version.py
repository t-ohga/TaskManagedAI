from __future__ import annotations

from typing import Final, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models.base import (
    Base,
    CreatedAtMixin,
    JsonDict,
    TenantIdMixin,
    rls_ready_metadata,
)

FixtureKind = Literal["public_regression", "private_holdout", "adversarial_new"]
STANDARD_FIXTURE_KIND_VALUES: Final[tuple[FixtureKind, ...]] = (
    "public_regression",
    "private_holdout",
    "adversarial_new",
)
STANDARD_FIXTURE_KINDS: Final[frozenset[FixtureKind]] = frozenset(STANDARD_FIXTURE_KIND_VALUES)


class DatasetVersion(TenantIdMixin, CreatedAtMixin, Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        sa.CheckConstraint(
            "fixture_kind in ('public_regression','private_holdout','adversarial_new')",
            name="dataset_versions_ck_fixture_kind",
        ),
        sa.CheckConstraint(
            "length(dataset_key) between 1 and 200",
            name="dataset_versions_ck_dataset_key_length",
        ),
        sa.CheckConstraint(
            "length(version) between 1 and 100",
            name="dataset_versions_ck_version_length",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[a-f0-9]{64}$'",
            name="dataset_versions_ck_content_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="dataset_versions_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="dataset_versions_uq_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "dataset_key",
            "version",
            name="dataset_versions_uq_tenant_dataset_key_version",
        ),
        sa.Index(
            "dataset_versions_ix_tenant_kind_created",
            "tenant_id",
            "fixture_kind",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=sa.text("uuid_generate_v4()"),
    )
    dataset_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    version: Mapped[str] = mapped_column(sa.Text, nullable=False)
    fixture_kind: Mapped[FixtureKind] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    metadata_: Mapped[JsonDict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=rls_ready_metadata,
        server_default=sa.text("'{}'::jsonb || '{\"rls_ready\": true}'::jsonb"),
    )


__all__ = ["DatasetVersion", "FixtureKind", "STANDARD_FIXTURE_KINDS"]
