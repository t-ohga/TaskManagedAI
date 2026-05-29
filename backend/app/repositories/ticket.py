from __future__ import annotations

import builtins
from datetime import UTC, datetime
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.project import Project
from backend.app.db.models.ticket import Ticket
from backend.app.repositories.base import BaseRepository


class ProjectArchivedError(Exception):
    """Q-4 (ADR-00037): archived project への child write (ticket create/update/import 等) は
    fail-closed。endpoint だけでなく全 ticket mutation が通る repository 境界で raise し、
    HTTP / MCP bridge / research-to-ticket promotion の全経路を凍結する (Codex plan R5)。
    """

    def __init__(self, *, project_id: UUID) -> None:
        super().__init__(
            f"project {project_id} is archived; unarchive it before mutating its tickets."
        )
        self.project_id = project_id


class TicketRepository(BaseRepository[Ticket]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Ticket)

    async def get(self, tenant_id: int, id: UUID) -> Ticket | None:
        raise NotImplementedError("Use get_in_project(...)")

    async def list(self, tenant_id: int) -> builtins.list[Ticket]:
        raise NotImplementedError("Use list_in_project(...)")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> Ticket | None:
        raise NotImplementedError("Use update_in_project(...)")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("Use delete_in_project(...)")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_project / *_in_project.")

    async def _assert_project_active(self, tenant_id: int, project_id: UUID) -> None:
        """Q-4 (ADR-00037): archived project への child write を fail-closed で拒否する。

        全 ticket mutation (create/update/import/restore) が本 helper を通るため、HTTP endpoint
        だけでなく MCP bridge / research-to-ticket promotion 等の直接 repository 呼び出しも凍結される。
        """
        project_status = await self.session.scalar(
            select(Project.status).where(
                Project.tenant_id == tenant_id,
                Project.id == project_id,
            )
        )
        if project_status is not None and project_status != "active":
            raise ProjectArchivedError(project_id=project_id)

    async def get_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> Ticket | None:
        await self._ensure_tenant_context(tenant_id)
        conditions = [
            Ticket.tenant_id == tenant_id,
            Ticket.project_id == project_id,
            Ticket.id == ticket_id,
        ]
        # Q-3 (ADR-00037): default は active scope (soft-deleted を全 read path で除外)。
        if not include_deleted:
            conditions.append(Ticket.deleted_at.is_(None))
        return cast(Ticket | None, await self.session.scalar(select(Ticket).where(*conditions)))

    async def list_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> builtins.list[Ticket]:
        await self._ensure_tenant_context(tenant_id)
        conditions = [
            Ticket.tenant_id == tenant_id,
            Ticket.project_id == project_id,
        ]
        if not include_deleted:
            conditions.append(Ticket.deleted_at.is_(None))
        result = await self.session.execute(
            select(Ticket).where(*conditions).order_by(Ticket.created_at, Ticket.slug)
        )
        return list(result.scalars().all())

    async def count_active_in_project(self, tenant_id: int, project_id: UUID) -> int:
        await self._ensure_tenant_context(tenant_id)
        count = await self.session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.deleted_at.is_(None),
            )
        )
        return int(count or 0)

    async def create_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        payload: dict[str, Any],
    ) -> Ticket:
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)
        data = self._payload_with_tenant_id(tenant_id, payload)

        if "project_id" in data and data["project_id"] != project_id:
            raise ValueError("payload project_id must match repository project_id.")

        data["project_id"] = project_id
        ticket = Ticket(**data)
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def update_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        payload: dict[str, Any],
    ) -> Ticket | None:
        await self._ensure_tenant_context(tenant_id)
        await self._assert_project_active(tenant_id, project_id)
        data = dict(payload)

        if "tenant_id" in data:
            if data["tenant_id"] != tenant_id:
                raise ValueError("payload tenant_id must match repository tenant_id.")
            data.pop("tenant_id")

        data = self._payload_for_update(tenant_id, ticket_id, data)

        if "project_id" in data:
            if data["project_id"] != project_id:
                raise ValueError("payload project_id must match repository project_id.")
            data.pop("project_id")

        # active scope: soft-deleted ticket は update 対象にしない。
        result = await self.session.execute(
            update(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.id == ticket_id,
                Ticket.deleted_at.is_(None),
            )
            .values(**data)
            .returning(Ticket)
        )
        return result.scalar_one_or_none()

    async def bulk_soft_delete_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        *,
        deleted_by_actor_id: UUID,
    ) -> tuple[UUID, int]:
        """Q-3 (ADR-00037): project 内 active 全 ticket を新 deletion batch で soft-delete。

        新 batch id (run id) を発行し、active (deleted_at IS NULL) のみ deleted_at/batch/by を set。
        (batch_id, soft_deleted_count) を返す。caller (endpoint) が CAS / 確認 / audit / commit を担う。
        """
        await self._ensure_tenant_context(tenant_id)
        batch_id = uuid4()
        result = await self.session.execute(
            update(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.deleted_at.is_(None),
            )
            .values(
                deleted_at=datetime.now(tz=UTC),
                deleted_batch_id=batch_id,
                deleted_by_actor_id=deleted_by_actor_id,
            )
            .returning(Ticket.id)
        )
        return batch_id, len(result.scalars().all())

    async def restore_batch_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        batch_id: UUID,
    ) -> int:
        """Q-3 (ADR-00037): 特定 deletion batch のみ復元 (Codex plan R2)。

        UPDATE は tenant + project + batch + deleted_at IS NOT NULL で限定 (越境復活防止)。
        restored_count を返す。再 restore / 別 project / 空 batch は 0 (idempotent)。
        """
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            update(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.deleted_batch_id == batch_id,
                Ticket.deleted_at.is_not(None),
            )
            .values(deleted_at=None, deleted_batch_id=None, deleted_by_actor_id=None)
            .returning(Ticket.id)
        )
        return len(result.scalars().all())

    async def delete_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
    ) -> int:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            delete(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.id == ticket_id,
            )
            .returning(Ticket.id)
        )
        deleted_id = result.scalar_one_or_none()
        return 0 if deleted_id is None else 1


__all__ = ["ProjectArchivedError", "TicketRepository"]

