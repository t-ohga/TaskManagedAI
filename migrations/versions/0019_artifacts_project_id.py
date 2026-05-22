"""Materialize artifacts.project_id column + composite FK / unique constraint.

Phase F-0 SP-012-7 must_ship 2 = PE-F-007 strict prerequisite for SP-013
Multi-Agent Orchestration Foundation. artifact が agent_runs 経由ではなく
独立 column として project boundary を持つ必要 (DD-02 invariant + SP-013
artifact_cross_project_negative test の direct query 可能化)。

設計:
1. artifacts.project_id column 追加 (UUID nullable initially、backfill 用)
2. backfill: artifacts.project_id = agent_runs.project_id (run_id 経由 resolve)
3. project_id を NOT NULL 化 + composite FK (tenant_id, project_id) → projects 追加
4. unique constraint (tenant_id, project_id, id) 追加 (artifact_cross_project_negative
   test の cross-project lookup を direct query 化)
5. index (tenant_id, project_id, created_at) 追加 (project boundary lookup 効率化)

既存 artifact 全件で agent_runs FK (tenant_id, run_id) が NOT NULL のため
backfill は必ず resolve 可能 (orphan artifact なし)。backfill 完了直後の sanity
check で NULL=0 を assert。

Revision ID: 0019_artifacts_project_id
Revises: 0018_eval_dataset_versions
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_artifacts_project_id"
down_revision: str | None = "0018_eval_dataset_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Step 1: nullable column 追加 (backfill 用)
    op.add_column(
        "artifacts",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Step 2: backfill artifacts.project_id from agent_runs.project_id
    # artifact は agent_runs に (tenant_id, run_id) FK NOT NULL で参照しているため
    # 必ず resolve 可能 (orphan artifact なし)。
    op.execute(
        sa.text(
            """
            UPDATE artifacts AS a
            SET project_id = ar.project_id
            FROM agent_runs AS ar
            WHERE a.tenant_id = ar.tenant_id
              AND a.run_id = ar.id
              AND a.project_id IS NULL
            """
        )
    )

    # Step 2b: sanity check (backfill NULL 残存 = 0 件) — fail-closed
    connection = op.get_bind()
    null_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM artifacts WHERE project_id IS NULL")
    ).scalar()
    if null_count != 0:
        raise RuntimeError(
            f"artifacts.project_id backfill incomplete: {null_count} rows still NULL. "
            "agent_runs FK orphan の可能性、migration を中断する。"
        )

    # Step 3: NOT NULL 化
    op.alter_column("artifacts", "project_id", nullable=False)

    # Step 4: composite FK (tenant_id, project_id) → projects(tenant_id, id)
    op.create_foreign_key(
        "artifacts_project_fkey",
        "artifacts",
        "projects",
        ["tenant_id", "project_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )

    # Step 4b: agent_runs FK を project_id 込みの strict 版に拡張
    # (既存 FK は (tenant_id, run_id) → agent_runs(tenant_id, id)、これに
    # project_id 整合性を追加する補強 FK を別 name で追加。既存 FK は維持で
    # backward compat、新 FK で SP-013 multi-agent project boundary を strict 化)
    op.create_foreign_key(
        "artifacts_run_project_fkey",
        "artifacts",
        "agent_runs",
        ["tenant_id", "project_id", "run_id"],
        ["tenant_id", "project_id", "id"],
        ondelete="RESTRICT",
    )

    # Step 5: unique constraint (tenant_id, project_id, id) for direct cross-project
    # negative test query (SP-013 artifact_cross_project_negative test prerequisite)
    op.create_unique_constraint(
        "artifacts_uq_tenant_project_id",
        "artifacts",
        ["tenant_id", "project_id", "id"],
    )

    # Step 6: index (tenant_id, project_id, created_at) for project boundary lookup
    op.create_index(
        "artifacts_idx_tenant_project_created",
        "artifacts",
        ["tenant_id", "project_id", "created_at"],
    )


def downgrade() -> None:
    # downgrade は逆順、artifact data を保持しつつ project_id boundary を撤去
    op.drop_index(
        "artifacts_idx_tenant_project_created",
        table_name="artifacts",
    )
    op.drop_constraint(
        "artifacts_uq_tenant_project_id",
        "artifacts",
        type_="unique",
    )
    op.drop_constraint(
        "artifacts_run_project_fkey",
        "artifacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "artifacts_project_fkey",
        "artifacts",
        type_="foreignkey",
    )
    op.drop_column("artifacts", "project_id")
