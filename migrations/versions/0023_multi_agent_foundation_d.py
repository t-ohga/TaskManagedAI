"""Multi-agent orchestration foundation phase D: sanitizer_policy_versions table.

SP-013 batch 0e (ADR-00016 §5 Phase G adversarial 正本 + PH-F-009 fix:
SP-013 で minimal seed table のみ作成、memory_records / memory_retrieval_artifacts の
FK は SP-018 で hermes 取り込み完了後に接続)。

scope:
- `sanitizer_policy_versions` minimal table 作成
- initial seed (`v1.0.0`、config_hash 固定値、ruleset_hash 固定値)

scope 外:
- memory_records / memory_retrieval_artifacts の FK 接続 (SP-018 で hermes 取り込み後)
- canary scan ruleset の実体実装 (P0.1+ memory layer 完成時)

Revision ID: 0023_multi_agent_foundation_d
Revises: 0022_multi_agent_foundation_c
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_multi_agent_foundation_d"
down_revision: str | None = "0022_multi_agent_foundation_c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_DEFAULT = sa.text("1")
NOW_DEFAULT = sa.text("now()")
UUID_V4_DEFAULT = sa.text("uuid_generate_v4()")

# initial seed: v1.0.0、SP-013 着手時点の minimal sanitizer policy。
# config_hash + ruleset_hash は SP-018 で hermes 取り込み完了後に実際の
# canonical config / ruleset の sha256 で update 予定。本 batch では placeholder。
INITIAL_VERSION = "v1.0.0"
INITIAL_CONFIG_HASH = "0" * 64  # SP-018 で実際の sha256 に置換
INITIAL_RULESET_HASH = "0" * 64  # 同上


def upgrade() -> None:
    op.create_table(
        "sanitizer_policy_versions",
        sa.Column("tenant_id", sa.BigInteger(), server_default=TENANT_ID_DEFAULT, nullable=False),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=UUID_V4_DEFAULT,
            nullable=False,
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("ruleset_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=NOW_DEFAULT, nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "config_hash ~ '^[0-9a-f]{64}$'",
            name="sanitizer_policy_versions_ck_config_hash_sha256",
        ),
        sa.CheckConstraint(
            "ruleset_hash ~ '^[0-9a-f]{64}$'",
            name="sanitizer_policy_versions_ck_ruleset_hash_sha256",
        ),
        sa.PrimaryKeyConstraint("id", name="sanitizer_policy_versions_pk"),
        sa.UniqueConstraint(
            "tenant_id", "id",
            name="sanitizer_policy_versions_uq_tenant_id",
        ),
        sa.UniqueConstraint(
            "tenant_id", "version",
            name="sanitizer_policy_versions_uq_tenant_version",
        ),
        sa.UniqueConstraint(
            "tenant_id", "config_hash",
            name="sanitizer_policy_versions_uq_tenant_config_hash",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="sanitizer_policy_versions_tenant_id_fkey",
            ondelete="RESTRICT",
        ),
    )

    # initial seed (v1.0.0、PH-F-009 fix: SP-013 で minimal seed のみ)
    op.execute(
        sa.text(
            """
            insert into sanitizer_policy_versions (
                tenant_id, version, config_hash, ruleset_hash
            )
            select 1, :version, :config_hash, :ruleset_hash
             where exists (select 1 from tenants where id = 1)
            """
        ).bindparams(
            version=INITIAL_VERSION,
            config_hash=INITIAL_CONFIG_HASH,
            ruleset_hash=INITIAL_RULESET_HASH,
        )
    )


def downgrade() -> None:
    op.drop_table("sanitizer_policy_versions")
