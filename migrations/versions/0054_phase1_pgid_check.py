"""SP-PHASE1 B4 (adversarial HIGH-2): managed_agents.process_group_id > 0 CHECK。

``os.killpg(0, SIGKILL)`` は **呼び出し元 (supervisor) 自身の process group 全体に SIGKILL** を送り
self-kill + 巻き添えになる。負 pgid も POSIX kill の特殊指定。corrupted/zero/負 pgid を構造的に排除する
ため ``process_group_id IS NULL OR process_group_id > 0`` の DB CHECK を追加する (supervisor 側の
``_killpg`` guard + ORM CheckConstraint と合わせ 4-layer 防御)。

additive のみ、downgrade は lossless (CHECK drop)。

**lossless 安全**: 正規経路 (``mark_running``) は ``os.getpgid()`` の結果 (常に > 0) のみ書くため
legal row は CHECK を満たす。万一 corrupted な 0/負 pgid 行が存在した場合、CHECK 追加が失敗しないよう
**preflight で当該 pgid を NULL 化** (= unkillable safe state、supervisor は NULL を skip)。NULL 化は
pgid 列のみに限定し他列は不変 (lossless: kill 不能化はするが row は消さない)。

Revision ID: 0054_phase1_pgid_check
Revises: 0053_phase1_emergency_stop
Create Date: 2026-06-22 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0054_phase1_pgid_check"
down_revision: str | None = "0053_phase1_emergency_stop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "managed_agents_ck_pgid_positive"


def upgrade() -> None:
    # preflight: corrupted な 0/負 pgid を NULL 化 (CHECK 追加を lossless に通す。kill 不能 safe state)。
    op.execute(
        "update managed_agents set process_group_id = null "
        "where process_group_id is not null and process_group_id <= 0"
    )
    op.create_check_constraint(
        _CHECK_NAME,
        "managed_agents",
        "process_group_id IS NULL OR process_group_id > 0",
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "managed_agents", type_="check")
