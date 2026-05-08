from __future__ import annotations

from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.ticket import Ticket
from backend.app.repositories.base import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Ticket)

    async def get(self, tenant_id: int, id: UUID) -> Ticket | None:
        raise NotImplementedError("Use get_in_project(...)")

    async def list(self, tenant_id: int) -> list[Ticket]:
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

    async def get_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
    ) -> Ticket | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(Ticket).where(
            Ticket.tenant_id == tenant_id,
            Ticket.project_id == project_id,
            Ticket.id == ticket_id,
        )
        return await self.session.scalar(stmt)

    async def list_in_project(self, tenant_id: int, project_id: UUID) -> list[Ticket]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
            )
            .order_by(Ticket.created_at, Ticket.slug)
        )
        return list(result.scalars().all())

    async def create_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        payload: dict[str, Any],
    ) -> Ticket:
        await self._ensure_tenant_context(tenant_id)
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

        result = await self.session.execute(
            update(Ticket)
            .where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.id == ticket_id,
            )
            .values(**data)
            .returning(Ticket)
        )
        return cast(Ticket | None, result.scalar_one_or_none())

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


__all__ = ["TicketRepository"]

