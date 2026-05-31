"""ADR-00037 R15 (Codex adversarial): AgentRun read-path の soft-deleted ticket active-scope。

soft-delete した ticket に紐づく run を **default read path** (run list / detail / kpi /
cost summary / KPI rollup / workflow summary / MCP run_list / run_show) から除外する共通 predicate。

- ticket-less run (``ticket_id IS NULL``) は削除対象でないため **含める**。
- restore で ticket が active へ戻れば run も再び現れる (dynamic filter)。
- 相関参照は複合 FK ``agent_runs(tenant_id, project_id, ticket_id) -> tickets(...)`` と同じ
  (tenant_id, project_id, id) 境界で行う。
- run-mutation 側の ``_assert_run_ticket_actionable`` (削除/凍結 run の advance 禁止) とは別の
  **read 側** active-scope。両者を揃えて「全 default read path は active-scope」を満たす。
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, select

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.ticket import Ticket


def soft_deleted_ticket_run_exclusion() -> ColumnElement[bool]:
    """AgentRun が soft-deleted ticket に bind されている場合に ``False`` となる述語を返す。

    ``WHERE`` / aggregation 条件に AND 連結して使う。``ticket_id IS NULL`` の run は
    相関サブクエリが空集合となり ``NOT EXISTS`` が真 → 集計/一覧に残る。
    """
    return ~(
        select(1)
        .where(
            Ticket.tenant_id == AgentRun.tenant_id,
            Ticket.project_id == AgentRun.project_id,
            Ticket.id == AgentRun.ticket_id,
            Ticket.deleted_at.is_not(None),
        )
        .exists()
    )


__all__ = ["soft_deleted_ticket_run_exclusion"]
