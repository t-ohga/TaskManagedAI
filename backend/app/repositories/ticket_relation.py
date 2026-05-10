from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.ticket import Ticket
from backend.app.db.models.ticket_relation import TicketRelation
from backend.app.repositories.base import BaseRepository


class TicketRelationRepository(BaseRepository[TicketRelation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TicketRelation)

    async def get(self, tenant_id: int, id: UUID) -> TicketRelation | None:
        raise NotImplementedError("Use get_in_project(...)")

    async def list(self, tenant_id: int) -> builtins.list[TicketRelation]:
        raise NotImplementedError("Use list_in_project(...)")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> TicketRelation | None:
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
        relation_id: UUID,
    ) -> TicketRelation | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(TicketRelation).where(
            TicketRelation.tenant_id == tenant_id,
            TicketRelation.project_id == project_id,
            TicketRelation.id == relation_id,
        )
        return cast(TicketRelation | None, await self.session.scalar(stmt))

    async def list_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
    ) -> builtins.list[TicketRelation]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(TicketRelation)
            .where(
                TicketRelation.tenant_id == tenant_id,
                TicketRelation.project_id == project_id,
            )
            .order_by(TicketRelation.created_at, TicketRelation.id)
        )
        return list(result.scalars().all())

    async def create_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        source_id: UUID,
        target_id: UUID,
        relation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> TicketRelation:
        await self._ensure_tenant_context(tenant_id)

        if source_id == target_id:
            raise ValueError("ticket relation source and target must differ.")

        ticket_count = await self.session.scalar(
            select(sa.func.count(Ticket.id)).where(
                Ticket.tenant_id == tenant_id,
                Ticket.project_id == project_id,
                Ticket.id.in_([source_id, target_id]),
            )
        )
        if ticket_count != 2:
            raise ValueError("ticket relation source and target must be in the same project.")

        relation = TicketRelation(
            tenant_id=tenant_id,
            project_id=project_id,
            source_ticket_id=source_id,
            target_ticket_id=target_id,
            relation_type=relation_type,
            metadata_=metadata or {"rls_ready": True},
        )
        self.session.add(relation)
        await self.session.flush()
        return relation

    async def update_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        relation_id: UUID,
        payload: dict[str, Any],
    ) -> TicketRelation | None:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_for_update(tenant_id, relation_id, payload)

        if "project_id" in data:
            if data["project_id"] != project_id:
                raise ValueError("payload project_id must match repository project_id.")
            data.pop("project_id")

        if (
            "source_ticket_id" in data
            and "target_ticket_id" in data
            and data["source_ticket_id"] == data["target_ticket_id"]
        ):
            raise ValueError("ticket relation source and target must differ.")

        result = await self.session.execute(
            update(TicketRelation)
            .where(
                TicketRelation.tenant_id == tenant_id,
                TicketRelation.project_id == project_id,
                TicketRelation.id == relation_id,
            )
            .values(**data)
            .returning(TicketRelation)
        )
        return result.scalar_one_or_none()

    async def delete_in_project(
        self,
        tenant_id: int,
        project_id: UUID,
        relation_id: UUID,
    ) -> int:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            delete(TicketRelation)
            .where(
                TicketRelation.tenant_id == tenant_id,
                TicketRelation.project_id == project_id,
                TicketRelation.id == relation_id,
            )
            .returning(TicketRelation.id)
        )
        deleted_id = result.scalar_one_or_none()
        return 0 if deleted_id is None else 1


__all__ = ["TicketRelationRepository"]

