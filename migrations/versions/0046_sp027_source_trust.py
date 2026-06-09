"""SP-027 source trust: evidence_sources.trust_level + trust_score (per-source manual trust).

Revision ID: 0046_sp027_source_trust
Revises: 0045_sp032_research_advanced
Create Date: 2026-06-09 00:00:00.000000

ADR-00053. SP-010 BL-0121 placeholder (source trust registry) の P1 activation。
evidence_sources に nullable な manual trust 列を 2 件追加 (additive のみ)。trust_level は SP-032
の TrustTier (low/medium/high) を reuse。manual override は trust_level 必須、trust_score 任意、両 null =
未設定、score 単独は禁止 (R1 F-004)。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_sp027_source_trust"
down_revision: str | None = "0045_sp032_research_advanced"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ADR-00053: SP-032 TrustTier を reuse (5+ source integrity の DB CHECK 側)
TRUST_TIERS = ("low", "medium", "high")


def upgrade() -> None:
    op.add_column("evidence_sources", sa.Column("trust_level", sa.Text(), nullable=True))
    op.add_column(
        "evidence_sources", sa.Column("trust_score", sa.Double(), nullable=True)
    )
    op.create_check_constraint(
        "evidence_sources_ck_trust_level",
        "evidence_sources",
        "trust_level is null or trust_level in ("
        + ", ".join(f"'{t}'" for t in TRUST_TIERS)
        + ")",
    )
    op.create_check_constraint(
        "evidence_sources_ck_trust_score_range",
        "evidence_sources",
        "trust_score is null or (trust_score >= 0.0 and trust_score <= 1.0)",
    )
    # R1 F-004: trust_score 単独 (level null + score 非 null) を禁止。manual override は level 必須。
    op.create_check_constraint(
        "evidence_sources_ck_trust_score_requires_level",
        "evidence_sources",
        "trust_level is not null or trust_score is null",
    )


def downgrade() -> None:
    op.drop_constraint(
        "evidence_sources_ck_trust_score_requires_level", "evidence_sources", type_="check"
    )
    op.drop_constraint(
        "evidence_sources_ck_trust_score_range", "evidence_sources", type_="check"
    )
    op.drop_constraint("evidence_sources_ck_trust_level", "evidence_sources", type_="check")
    op.drop_column("evidence_sources", "trust_score")
    op.drop_column("evidence_sources", "trust_level")
