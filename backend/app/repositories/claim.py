from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.claim import Claim
from backend.app.repositories.base import BaseRepository


def _model_payload(value: BaseModel | dict[str, Any], *, exclude_unset: bool = False) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_unset=exclude_unset)
    return dict(value)


class ClaimRepository(BaseRepository[Claim]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Claim)

    async def get(self, tenant_id: int, id: UUID) -> Claim | None:
        raise NotImplementedError("Use get_claim_by_id(...).")

    async def list(self, tenant_id: int) -> builtins.list[Claim]:
        raise NotImplementedError("Use list_claims_by_research_task(...).")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> Claim | None:
        raise NotImplementedError("Use update_claim(...).")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("Use delete_claim(...).")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    async def create_claim(
        self,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        claim_create: BaseModel | dict[str, Any],
    ) -> Claim:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_with_tenant_id(tenant_id, _model_payload(claim_create))

        if "project_id" in data and data["project_id"] != project_id:
            raise ValueError("payload project_id must match repository project_id.")
        if "research_task_id" in data and data["research_task_id"] != research_task_id:
            raise ValueError("payload research_task_id must match repository research_task_id.")

        data["project_id"] = project_id
        data["research_task_id"] = research_task_id
        claim = Claim(**data)
        self.session.add(claim)
        await self.session.flush()
        return claim

    async def get_claim_by_id(
        self,
        tenant_id: int,
        project_id: UUID,
        claim_id: UUID,
    ) -> Claim | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(Claim).where(
            Claim.tenant_id == tenant_id,
            Claim.project_id == project_id,
            Claim.id == claim_id,
        )
        return cast(Claim | None, await self.session.scalar(stmt))

    async def list_claims_by_research_task(
        self,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
    ) -> builtins.list[Claim]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(Claim)
            .where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.research_task_id == research_task_id,
            )
            .order_by(Claim.created_at, Claim.id)
        )
        return list(result.scalars().all())

    async def update_claim(
        self,
        tenant_id: int,
        project_id: UUID,
        claim_id: UUID,
        claim_update: BaseModel | dict[str, Any],
    ) -> Claim | None:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_for_update(
            tenant_id,
            claim_id,
            _model_payload(claim_update, exclude_unset=True),
        )

        if "project_id" in data:
            if data["project_id"] != project_id:
                raise ValueError("payload project_id must match repository project_id.")
            data.pop("project_id")
        data.pop("research_task_id", None)

        if not data:
            return await self.get_claim_by_id(tenant_id, project_id, claim_id)

        result = await self.session.execute(
            update(Claim)
            .where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.id == claim_id,
            )
            .values(**data)
            .returning(Claim)
        )
        return result.scalar_one_or_none()

    async def delete_claim(
        self,
        tenant_id: int,
        project_id: UUID,
        claim_id: UUID,
    ) -> bool:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            delete(Claim)
            .where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.id == claim_id,
            )
            .returning(Claim.id)
        )
        return result.scalar_one_or_none() is not None


async def create_claim(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
    claim_create: BaseModel | dict[str, Any],
) -> Claim:
    return await ClaimRepository(session).create_claim(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
        claim_create=claim_create,
    )


async def get_claim_by_id(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    claim_id: UUID,
) -> Claim | None:
    return await ClaimRepository(session).get_claim_by_id(
        tenant_id=tenant_id,
        project_id=project_id,
        claim_id=claim_id,
    )


async def list_claims_by_research_task(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    research_task_id: UUID,
) -> list[Claim]:
    return await ClaimRepository(session).list_claims_by_research_task(
        tenant_id=tenant_id,
        project_id=project_id,
        research_task_id=research_task_id,
    )


async def update_claim(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    claim_id: UUID,
    claim_update: BaseModel | dict[str, Any],
) -> Claim | None:
    return await ClaimRepository(session).update_claim(
        tenant_id=tenant_id,
        project_id=project_id,
        claim_id=claim_id,
        claim_update=claim_update,
    )


async def delete_claim(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    claim_id: UUID,
) -> bool:
    return await ClaimRepository(session).delete_claim(
        tenant_id=tenant_id,
        project_id=project_id,
        claim_id=claim_id,
    )


__all__ = [
    "ClaimRepository",
    "create_claim",
    "delete_claim",
    "get_claim_by_id",
    "list_claims_by_research_task",
    "update_claim",
]
