"""ADR-00037 R12 (Codex adversarial): agent_runs.ticket_id (run→ticket binding の server-owned 化)。

Revision ID: 0040_agent_run_ticket_id
Revises: 0039_ticket_soft_delete
Create Date: 2026-05-31 00:00:00.000000

run→ticket binding を ``run_queued`` event payload から server-owned column へ昇格する。これにより
(1) run-transition guard (R6/R11) が event-payload 依存の fail-open を排し column 直読みで fail-closed 化、
(2) KPI/cost READ が soft-deleted ticket bound の run を active-scope で除外できる (R12)。
nullable 追加 (既存行無影響)。既存 run は canonical run_queued event (seq_no 最小) の ticket_id から
backfill する。不正/欠損 payload は NULL のまま (guard は project active を fail-closed で適用)。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0040_agent_run_ticket_id"
down_revision: str | None = "0039_ticket_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("ticket_id", PG_UUID(as_uuid=True), nullable=True),
    )
    # 既存 run を canonical run_queued event payload (seq_no 最小) の ticket_id から backfill。
    # R13 (Codex adversarial): event payload は **untrusted** なので、run と同一
    # (tenant_id, project_id) の tickets 行に **実在一致** する場合のみ ticket_id を設定する。
    # cross-project / cross-tenant / 存在しない / 不正 UUID の binding は NULL のまま残し
    # (guard は assert_project_active を fail-closed で適用)、下記複合 FK 作成を破綻させない。
    # soft-deleted ticket も行自体は残る (deleted_at セットのみ) ため join 可能。
    op.execute(
        sa.text(
            """
            UPDATE agent_runs ar
               SET ticket_id = t.id
              FROM (
                SELECT DISTINCT ON (e.tenant_id, e.run_id)
                       e.tenant_id,
                       e.run_id,
                       (e.event_payload->>'ticket_id')::uuid AS ticket_uuid
                  FROM agent_run_events e
                 WHERE e.event_type = 'run_queued'
                   AND e.event_payload->>'ticket_id' ~
                       '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                 ORDER BY e.tenant_id, e.run_id, e.seq_no ASC
              ) sub
              JOIN tickets t
                ON t.tenant_id = sub.tenant_id
               AND t.id = sub.ticket_uuid
             WHERE ar.tenant_id = sub.tenant_id
               AND ar.id = sub.run_id
               AND t.project_id = ar.project_id
            """
        )
    )
    op.create_index(
        "agent_runs_idx_tenant_ticket",
        "agent_runs",
        ["tenant_id", "ticket_id"],
        postgresql_where=sa.text("ticket_id IS NOT NULL"),
    )
    # R13 (Codex adversarial): server-owned 権威列が cross-project/cross-tenant/存在しない ticket を
    # 指さないことを DB で強制する複合 FK (core.md §8「親子参照は tenant_id を含む複合 FK で閉じる」
    # +「project 境界をまたぐ参照禁止」)。ticket_id IS NULL は MATCH SIMPLE で未強制 (ticket-less run)。
    # 一致先は tickets_uq_tenant_project_id (tenant_id, project_id, id)。
    op.create_foreign_key(
        "agent_runs_ticket_fkey",
        "agent_runs",
        "tickets",
        ["tenant_id", "project_id", "ticket_id"],
        ["tenant_id", "project_id", "id"],
        ondelete="RESTRICT",
    )
    # R21 (Codex adversarial): backfill 後 fail-closed postcheck。run_queued event が ticket binding を
    # **主張する** (canonical event payload の ticket_id が UUID 形式) のに、cross-project / 不在 / hard-delete
    # 等で同一 project ticket に解決できず ticket_id=NULL のまま残った run は、active-scope guard が
    # ticket-less (可視・進行可) と誤認し soft-delete を migration 時点で迂回する fail-open になる。
    # downgrade fail-closed (lossless 一致検査) と対称に、upgrade も「binding を主張するが復元不能」な run が
    # 1 件でもあれば中断し、operator に reconcile / export を要求する (genuinely ticket-less = payload に
    # ticket_id を持たない run は対象外で migration を妨げない)。
    bind = op.get_bind()
    unresolved = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM agent_runs ar
             WHERE ar.ticket_id IS NULL
               AND (
                 SELECT (e.event_payload->>'ticket_id') ~
                        '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                   FROM agent_run_events e
                  WHERE e.tenant_id = ar.tenant_id
                    AND e.run_id = ar.id
                    AND e.event_type = 'run_queued'
                  ORDER BY e.seq_no ASC
                  LIMIT 1
               ) IS TRUE
            """
        )
    ).scalar_one()
    if unresolved and int(unresolved) > 0:
        raise RuntimeError(
            "Refusing to complete 0040_agent_run_ticket_id upgrade: "
            f"{unresolved} agent_run(s) declare a ticket binding in their canonical run_queued event "
            "but could not be backfilled (cross-project / missing / hard-deleted ticket). These would be "
            "treated as ticket-less (visible / advanceable) and bypass soft-delete active-scope at "
            "migration time. Reconcile the bindings (or export and remove the orphan runs) before upgrading."
        )


def downgrade() -> None:
    # R14 (Codex adversarial): server-owned agent_runs.ticket_id は run_queued event payload と
    # 乖離し得る (column が正本、event payload は untrusted)。無条件 drop すると rollback→re-upgrade で
    # payload 欠落/改ざん/cross-project だった run が ticket-less 化し、soft-deleted ticket bound run が
    # 集計・操作対象へ復活する silent resurrection になり得る。よって 0039 downgrade と同じ fail-closed
    # 思想で、ACCESS EXCLUSIVE lock を取得してから (TOCTOU 排除) 全 non-NULL ticket_id が canonical
    # run_queued event payload (seq_no 最小, UUID 形式) と lossless 一致することを検査し、1 件でも
    # 不一致/欠損があれば中断する (drop すると再 upgrade で復元不能なため)。
    bind = op.get_bind()
    # R15 (Codex adversarial): preflight が読む agent_run_events も同一 transaction 内で排他ロックする。
    # agent_runs だけのロックでは preflight 通過〜drop_column の間に event_payload を差し替え/欠落でき
    # TOCTOU が残る (column 喪失 + 改変後 payload からの誤復元)。両 table をロックし競合更新を止める。
    bind.execute(sa.text("LOCK TABLE agent_runs, agent_run_events IN ACCESS EXCLUSIVE MODE"))
    mismatched = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM agent_runs ar
             WHERE ar.ticket_id IS NOT NULL
               AND ar.ticket_id IS DISTINCT FROM (
                 SELECT (e.event_payload->>'ticket_id')::uuid
                   FROM agent_run_events e
                  WHERE e.tenant_id = ar.tenant_id
                    AND e.run_id = ar.id
                    AND e.event_type = 'run_queued'
                    AND e.event_payload->>'ticket_id' ~
                        '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                  ORDER BY e.seq_no ASC
                  LIMIT 1
               )
            """
        )
    ).scalar_one()
    if mismatched and int(mismatched) > 0:
        raise RuntimeError(
            "Refusing to downgrade 0040_agent_run_ticket_id: "
            f"{mismatched} agent_run(s) have a server-owned ticket_id that does not losslessly "
            "match the canonical run_queued event payload. Dropping the column would cause silent "
            "resurrection on re-upgrade (event payload is untrusted and may diverge). Reconcile or "
            "export agent_runs.ticket_id before downgrading."
        )
    op.drop_constraint("agent_runs_ticket_fkey", "agent_runs", type_="foreignkey")
    op.drop_index("agent_runs_idx_tenant_ticket", table_name="agent_runs")
    op.drop_column("agent_runs", "ticket_id")
