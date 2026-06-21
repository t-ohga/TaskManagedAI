"""DB-backed managed-agent registry service (SP-PHASE1 B2、ADR-00048 §F/A-1/A-2/A-3)。

``managed_agents`` を **cross-process kill の正本** とする (in-process dict ではない)。各 host process
(MCP server / worker) が spawn した subprocess を DB に永続登録し、FastAPI process の emergency-stop が
host scope で active 行を列挙して supervisor 経由で kill できるようにする (ADR-00048 §F)。

全 query は ``tenant_id`` 条件を含む (repository contract、core.md §8 / instincts §8)。raw secret / token は
扱わない。pid / pgid は内部 supervision metadata であり audit には redact / hash した形でのみ出す
(本 service は pid を返さず、audit emission は呼出側 service の責務)。

責務分離 (A-3): 本 registry = agent process supervision。``active_registry_worker_gate`` = host-fleet DML
mutation gate (別責務)。混同しない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.managed_agent import ManagedAgentRecord
from backend.app.domain.superintendent.managed_agent_state import (
    ACTIVE_MANAGED_AGENT_STATES,
    TERMINAL_MANAGED_AGENT_STATES,
    ManagedAgentState,
)


@dataclass(frozen=True, slots=True)
class ManagedAgentView:
    """registry 行の読み取り view (kill / 監視に必要な supervision metadata)。"""

    id: UUID
    tenant_id: int
    project_id: UUID
    agent_run_id: UUID | None
    host_id: str
    process_group_id: int | None
    pid: int | None
    supervisor_id: str | None
    state: ManagedAgentState
    boot_id: str | None
    started_at: datetime | None


def _to_view(row: ManagedAgentRecord) -> ManagedAgentView:
    return ManagedAgentView(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        agent_run_id=row.agent_run_id,
        host_id=row.host_id,
        process_group_id=row.process_group_id,
        pid=row.pid,
        supervisor_id=row.supervisor_id,
        state=row.state,
        boot_id=row.boot_id,
        started_at=row.started_at,
    )


class ManagedAgentRegistry:
    """``managed_agents`` への DB-backed lifecycle 操作 (tenant-scoped)。

    transaction 境界は呼出側が制御する (本 service は flush までで commit しない)。spawn ordering A-1
    では caller が advisory lock + 同一 transaction 内で ``register_spawning`` → process 起動 →
    ``mark_running`` → COMMIT を直列化する。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_spawning(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        host_id: str,
        agent_run_id: UUID | None = None,
        supervisor_id: str | None = None,
    ) -> UUID:
        """process 起動前に ``state='spawning'`` 行を pre-register し id を返す (A-1)。

        pid / pgid / boot_id は未確定 (process 起動後に ``mark_running`` で確定する)。
        """
        record = ManagedAgentRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            project_id=project_id,
            agent_run_id=agent_run_id,
            host_id=host_id,
            supervisor_id=supervisor_id,
            state="spawning",
        )
        self._session.add(record)
        await self._session.flush()
        return record.id

    async def mark_running(
        self,
        *,
        tenant_id: int,
        managed_agent_id: UUID,
        pid: int,
        process_group_id: int,
        boot_id: str | None,
    ) -> bool:
        """process 起動成功後、pid/pgid/boot_id を確定し ``state='running'`` へ遷移する (A-1)。

        ``spawning`` 行のみ遷移可 (concurrent terminalize 後の二重遷移を防ぐ)。遷移できたら True。
        """
        result = await self._session.execute(
            sa.update(ManagedAgentRecord)
            .where(
                ManagedAgentRecord.tenant_id == tenant_id,
                ManagedAgentRecord.id == managed_agent_id,
                ManagedAgentRecord.state == "spawning",
            )
            .values(
                state="running",
                pid=pid,
                process_group_id=process_group_id,
                boot_id=boot_id,
                started_at=datetime.now(UTC),
            )
        )
        return (cast("Any", result).rowcount or 0) == 1

    async def mark_terminal(
        self,
        *,
        tenant_id: int,
        managed_agent_id: UUID,
        state: ManagedAgentState,
    ) -> bool:
        """非 terminal 行を terminal (``stopped`` / ``failed``) へ遷移する。

        compensating terminalize (A-1): spawn 起動失敗・例外時に ``failed`` 化して orphan 行を残さない。
        既に terminal な行は遷移しない (二重 terminalize を no-op)。
        """
        if state not in TERMINAL_MANAGED_AGENT_STATES:
            raise ValueError(f"mark_terminal requires a terminal state, got: {state}")
        result = await self._session.execute(
            sa.update(ManagedAgentRecord)
            .where(
                ManagedAgentRecord.tenant_id == tenant_id,
                ManagedAgentRecord.id == managed_agent_id,
                ManagedAgentRecord.state.in_(tuple(ACTIVE_MANAGED_AGENT_STATES)),
            )
            .values(state=state)
        )
        return (cast("Any", result).rowcount or 0) == 1

    async def get(
        self, *, tenant_id: int, managed_agent_id: UUID
    ) -> ManagedAgentView | None:
        row = await self._session.scalar(
            sa.select(ManagedAgentRecord).where(
                ManagedAgentRecord.tenant_id == tenant_id,
                ManagedAgentRecord.id == managed_agent_id,
            )
        )
        return _to_view(row) if row is not None else None

    async def list_active_for_tenant(self, *, tenant_id: int) -> list[ManagedAgentView]:
        """tenant scope の active (spawning / running) 行を列挙する (emergency-stop kill 対象)。"""
        rows = await self._session.scalars(
            sa.select(ManagedAgentRecord).where(
                ManagedAgentRecord.tenant_id == tenant_id,
                ManagedAgentRecord.state.in_(tuple(ACTIVE_MANAGED_AGENT_STATES)),
            )
        )
        return [_to_view(r) for r in rows]

    async def list_active_on_host(
        self, *, host_id: str, tenant_id: int | None = None
    ) -> list[ManagedAgentView]:
        """host scope の active 行を列挙する (supervisor が自 host の subprocess を kill する対象)。

        ``tenant_id`` を渡すと host × tenant に絞る (同 host 上の別 tenant subprocess を巻き込まない、
        A-2 の host scope + tenant scope 二重絞り)。
        """
        conditions = [
            ManagedAgentRecord.host_id == host_id,
            ManagedAgentRecord.state.in_(tuple(ACTIVE_MANAGED_AGENT_STATES)),
        ]
        if tenant_id is not None:
            conditions.append(ManagedAgentRecord.tenant_id == tenant_id)
        rows = await self._session.scalars(
            sa.select(ManagedAgentRecord).where(*conditions)
        )
        return [_to_view(r) for r in rows]


__all__ = ["ManagedAgentRegistry", "ManagedAgentView"]
