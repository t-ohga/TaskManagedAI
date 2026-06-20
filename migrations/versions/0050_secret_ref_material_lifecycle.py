"""ADR-00058 finding-2 / ADR-00059: secret_refs material lifecycle 列 (crash-safe source of truth)。

Revision ID: 0050_secret_ref_material_lifecycle
Revises: 0049_secret_uri_local_backend
Create Date: 2026-06-20 00:00:01.000000

broker-owned (local backend) material の create / rotate / revoke を crash-safe に追跡する additive
列を追加する:

- ``material_state`` (``writing`` / ``present`` / ``purging`` / ``purged``): DB が material owner の
  source of truth。**default ``writing``** = store 未完了 row が false-present にならない安全側
  (token issue / redeem は ``material_state='present'`` を必須化、boundary §7/§9)。
- ``material_purged_at`` (timestamptz NULL): 「secret-at-rest 削除済」の durable source of truth。
  non-NULL で初めて purge 完了 (ADR-00059)。
- ``purge_attempts`` (int): gc-orphans reconciliation の再試行回数。

**backfill (ADR-00059 amendment、2026-06-20)**: material lifecycle は broker-owned (local) material
を統治する。sops backend の material は外部 (SOPS file) 管理で本 lifecycle の対象外。よって既存 row は

- 非 revoked → ``present`` (material 存在: active/pending/deprecated)
- revoked    → ``purged`` + ``material_purged_at=COALESCE(revoked_at, now())``

とする。pre-0050 の revoked row は broker-owned local material を持たない (local backend は本 Phase で
新設) ため「既に purge 済 (broker-owned material 無し)」が honest。これにより ``material_purged_at IS
NULL`` を「local revoked + purge 待ち」のみが真とする globally-consistent 不変条件が成立し、downgrade
condition (a) (`revoked AND material_purged_at IS NULL` = 0) が既存 sops revoked row で deadlock しない。

**downgrade は 3 条件 preflight** (full rollback 0050→0049 の skew 防止、ADR-00059 finding R8/R19):
(a) ``status='revoked' AND material_purged_at IS NULL`` 0 件 (gc-orphans 未収束を弾く)
(b) ``material_state IN ('writing','purging')`` 0 件 (in-flight material 操作を弾く)
(c) ``secret_uri LIKE 'secret://local/%'`` 0 件 (local material が残っていない)
いずれか残存で fail-fast。3 条件すべて 0 件確認後にのみ 3 列を削除する。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050_secret_ref_material_lifecycle"
down_revision: str | None = "0049_secret_uri_local_backend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "secret_refs"
_CK_STATE = "secret_refs_ck_material_state"
_CK_ATTEMPTS = "secret_refs_ck_purge_attempts_nonneg"
_CK_PURGED_STATE = "secret_refs_ck_material_purged_at_state"
_CK_PURGE_REVOKED = "secret_refs_ck_material_purge_requires_revoked"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "material_state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'writing'"),
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column("material_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "purge_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    bind = op.get_bind()
    # 非 revoked → present (material 存在)。
    bind.execute(
        sa.text(
            "update secret_refs set material_state = 'present' where status <> 'revoked'"
        )
    )
    # revoked → purged + material_purged_at (pre-0050 revoked は broker-owned local material 無し)。
    bind.execute(
        sa.text(
            "update secret_refs "
            "set material_state = 'purged', "
            "    material_purged_at = coalesce(revoked_at, now()) "
            "where status = 'revoked'"
        )
    )

    op.create_check_constraint(
        _CK_STATE,
        _TABLE,
        "material_state in ('writing','present','purging','purged')",
    )
    op.create_check_constraint(_CK_ATTEMPTS, _TABLE, "purge_attempts >= 0")
    op.create_check_constraint(
        _CK_PURGED_STATE,
        _TABLE,
        "(material_purged_at is null and material_state <> 'purged') "
        "or (material_purged_at is not null and material_state = 'purged')",
    )
    op.create_check_constraint(
        _CK_PURGE_REVOKED,
        _TABLE,
        "material_state not in ('purging','purged') or status = 'revoked'",
    )


def downgrade() -> None:
    bind = op.get_bind()
    revoked_unpurged = bind.execute(
        sa.text(
            "select count(*) from secret_refs "
            "where status = 'revoked' and material_purged_at is null"
        )
    ).scalar_one()
    in_flight = bind.execute(
        sa.text(
            "select count(*) from secret_refs "
            "where material_state in ('writing','purging')"
        )
    ).scalar_one()
    local_rows = bind.execute(
        sa.text(
            "select count(*) from secret_refs where secret_uri like 'secret://local/%'"
        )
    ).scalar_one()

    blockers: list[str] = []
    if revoked_unpurged:
        blockers.append(
            f"{revoked_unpurged} revoked row(s) with material_purged_at IS NULL "
            "(run `taskhub secret gc-orphans` to purge first)"
        )
    if in_flight:
        blockers.append(
            f"{in_flight} row(s) with material_state in (writing,purging) "
            "(let registration/reconciliation settle first)"
        )
    if local_rows:
        blockers.append(
            f"{local_rows} secret://local/% row(s) "
            "(migrate to a sops backend or revoke+purge first)"
        )
    if blockers:
        raise RuntimeError(
            "0050 downgrade blocked (material lifecycle source-of-truth protection): "
            + "; ".join(blockers)
        )

    op.drop_constraint(_CK_PURGE_REVOKED, _TABLE, type_="check")
    op.drop_constraint(_CK_PURGED_STATE, _TABLE, type_="check")
    op.drop_constraint(_CK_ATTEMPTS, _TABLE, type_="check")
    op.drop_constraint(_CK_STATE, _TABLE, type_="check")
    op.drop_column(_TABLE, "purge_attempts")
    op.drop_column(_TABLE, "material_purged_at")
    op.drop_column(_TABLE, "material_state")
