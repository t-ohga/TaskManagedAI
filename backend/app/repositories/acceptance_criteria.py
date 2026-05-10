from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.acceptance_criteria import AcceptanceCriteria
from backend.app.repositories.base import BaseRepository


class AcceptanceCriteriaRepository(BaseRepository[AcceptanceCriteria]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AcceptanceCriteria)

    async def get(self, tenant_id: int, id: UUID) -> AcceptanceCriteria | None:
        raise NotImplementedError("Use get_in_ticket(...)")

    async def list(self, tenant_id: int) -> builtins.list[AcceptanceCriteria]:
        raise NotImplementedError("Use list_in_ticket(...)")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> AcceptanceCriteria | None:
        raise NotImplementedError("Use update_in_ticket(...)")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("Use delete_in_ticket(...)")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_ticket / *_in_ticket.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_ticket / *_in_ticket.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_ticket / *_in_ticket.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use statement_for_*_in_ticket / *_in_ticket.")

    async def get_in_ticket(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        ac_id: UUID,
    ) -> AcceptanceCriteria | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(AcceptanceCriteria).where(
            AcceptanceCriteria.tenant_id == tenant_id,
            AcceptanceCriteria.project_id == project_id,
            AcceptanceCriteria.ticket_id == ticket_id,
            AcceptanceCriteria.id == ac_id,
        )
        return cast(AcceptanceCriteria | None, await self.session.scalar(stmt))

    async def list_in_ticket(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
    ) -> builtins.list[AcceptanceCriteria]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(AcceptanceCriteria)
            .where(
                AcceptanceCriteria.tenant_id == tenant_id,
                AcceptanceCriteria.project_id == project_id,
                AcceptanceCriteria.ticket_id == ticket_id,
            )
            .order_by(AcceptanceCriteria.created_at, AcceptanceCriteria.id)
        )
        return list(result.scalars().all())

    async def create_in_ticket(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        payload: dict[str, Any],
    ) -> AcceptanceCriteria:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_with_tenant_id(tenant_id, payload)

        if "project_id" in data and data["project_id"] != project_id:
            raise ValueError("payload project_id must match repository project_id.")
        if "ticket_id" in data and data["ticket_id"] != ticket_id:
            raise ValueError("payload ticket_id must match repository ticket_id.")

        data["project_id"] = project_id
        data["ticket_id"] = ticket_id
        acceptance_criteria = AcceptanceCriteria(**data)
        self.session.add(acceptance_criteria)
        await self.session.flush()
        return acceptance_criteria

    async def update_in_ticket(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        ac_id: UUID,
        payload: dict[str, Any],
    ) -> AcceptanceCriteria | None:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_for_update(tenant_id, ac_id, payload)

        if "project_id" in data:
            if data["project_id"] != project_id:
                raise ValueError("payload project_id must match repository project_id.")
            data.pop("project_id")

        if "ticket_id" in data:
            if data["ticket_id"] != ticket_id:
                raise ValueError("payload ticket_id must match repository ticket_id.")
            data.pop("ticket_id")

        result = await self.session.execute(
            update(AcceptanceCriteria)
            .where(
                AcceptanceCriteria.tenant_id == tenant_id,
                AcceptanceCriteria.project_id == project_id,
                AcceptanceCriteria.ticket_id == ticket_id,
                AcceptanceCriteria.id == ac_id,
            )
            .values(**data)
            .returning(AcceptanceCriteria)
        )
        return result.scalar_one_or_none()

    async def delete_in_ticket(
        self,
        tenant_id: int,
        project_id: UUID,
        ticket_id: UUID,
        ac_id: UUID,
    ) -> int:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            delete(AcceptanceCriteria)
            .where(
                AcceptanceCriteria.tenant_id == tenant_id,
                AcceptanceCriteria.project_id == project_id,
                AcceptanceCriteria.ticket_id == ticket_id,
                AcceptanceCriteria.id == ac_id,
            )
            .returning(AcceptanceCriteria.id)
        )
        deleted_id = result.scalar_one_or_none()
        return 0 if deleted_id is None else 1


__all__ = ["AcceptanceCriteriaRepository"]

