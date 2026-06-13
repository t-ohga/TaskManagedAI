"""SP-029 shadow mode (ADR-00055): agent_runs.run_mode additive 列。

Revision ID: 0048_agent_run_run_mode
Revises: 0047_webhook_reason_not_null
Create Date: 2026-06-13 00:00:00.000000

shadow run (副作用隔離・production budget 非加算・per-run cap) を表す `run_mode`
(`production` / `shadow`) を additive 追加する。`NOT NULL DEFAULT 'production'` で既存 row は
全て production に backfill され非破壊。16 status / blocked_reason / ContextSnapshot 10 列は不変
(run_mode は直交次元)。

downgrade は **cleanup-only** (ADR-00055 rollback §): 稼働中 app (run_mode 参照コード) に対する
即時 rollback step ではない。production rollback は flag off → run_mode 非参照の互換コードへ戻す →
本 downgrade を cleanup migration として適用、の順を厳守する。CI の down→up は migration 可逆性
検証 (app 非稼働の test DB) であり production 手順ではない。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_agent_run_run_mode"
down_revision: str | None = "0047_webhook_reason_not_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_runs"
_COLUMN = "run_mode"
_CONSTRAINT = "agent_runs_ck_run_mode"


def upgrade() -> None:
    # additive 列。server_default 'production' で既存 row を非破壊に backfill した上で NOT NULL。
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Text(),
            nullable=False,
            server_default=sa.text("'production'"),
        ),
    )
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "run_mode in ('production','shadow')",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)
