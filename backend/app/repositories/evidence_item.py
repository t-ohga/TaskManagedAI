from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.evidence_item import EvidenceItem
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.base import BaseRepository


def _model_payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump()
    return dict(value)


class EvidenceItemRepository(BaseRepository[EvidenceItem]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EvidenceItem)

    async def get(self, tenant_id: int, id: UUID) -> EvidenceItem | None:
        raise NotImplementedError("Use get_evidence_item_by_id(...).")

    async def list(self, tenant_id: int) -> builtins.list[EvidenceItem]:
        raise NotImplementedError("Use list_evidence_items_by_claim(...).")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("Use delete_evidence_item(...).")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    async def create_evidence_item(
        self,
        tenant_id: int,
        project_id: UUID,
        claim_id: UUID,
        evidence_item_create: BaseModel | dict[str, Any],
    ) -> EvidenceItem:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_with_tenant_id(tenant_id, _model_payload(evidence_item_create))

        if "project_id" in data and data["project_id"] != project_id:
            raise ValueError("payload project_id must match repository project_id.")
        if "claim_id" in data and data["claim_id"] != claim_id:
            raise ValueError("payload claim_id must match repository claim_id.")

        # F-PR19-R2-002 P1 + F-PR19-R1-003 P1 adopt: server-owned UUID 追加前の caller payload に対して
        # secret scan を実行。scan 範囲を minimize し、server-owned UUID (project_id / claim_id) は対象外。
        # caller-supplied UUID (source_id) は scan 対象内、ただし UUID 形式は secret pattern と一致しない設計。
        assert_no_raw_secret(data, path="$evidence_item_create")

        data["project_id"] = project_id
        data["claim_id"] = claim_id

        item = EvidenceItem(**data)
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_evidence_item_by_id(
        self,
        tenant_id: int,
        project_id: UUID,
        evidence_item_id: UUID,
    ) -> EvidenceItem | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(EvidenceItem).where(
            EvidenceItem.tenant_id == tenant_id,
            EvidenceItem.project_id == project_id,
            EvidenceItem.id == evidence_item_id,
        )
        return cast(EvidenceItem | None, await self.session.scalar(stmt))

    async def list_evidence_items_by_claim(
        self,
        tenant_id: int,
        project_id: UUID,
        claim_id: UUID,
    ) -> builtins.list[EvidenceItem]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(EvidenceItem)
            .where(
                EvidenceItem.tenant_id == tenant_id,
                EvidenceItem.project_id == project_id,
                EvidenceItem.claim_id == claim_id,
            )
            .order_by(EvidenceItem.created_at, EvidenceItem.id)
        )
        return list(result.scalars().all())

    async def delete_evidence_item(
        self,
        tenant_id: int,
        project_id: UUID,
        evidence_item_id: UUID,
    ) -> bool:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            delete(EvidenceItem)
            .where(
                EvidenceItem.tenant_id == tenant_id,
                EvidenceItem.project_id == project_id,
                EvidenceItem.id == evidence_item_id,
            )
            .returning(EvidenceItem.id)
        )
        return result.scalar_one_or_none() is not None


async def create_evidence_item(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    claim_id: UUID,
    evidence_item_create: BaseModel | dict[str, Any],
) -> EvidenceItem:
    return await EvidenceItemRepository(session).create_evidence_item(
        tenant_id=tenant_id,
        project_id=project_id,
        claim_id=claim_id,
        evidence_item_create=evidence_item_create,
    )


async def get_evidence_item_by_id(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    evidence_item_id: UUID,
) -> EvidenceItem | None:
    return await EvidenceItemRepository(session).get_evidence_item_by_id(
        tenant_id=tenant_id,
        project_id=project_id,
        evidence_item_id=evidence_item_id,
    )


async def list_evidence_items_by_claim(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    claim_id: UUID,
) -> list[EvidenceItem]:
    return await EvidenceItemRepository(session).list_evidence_items_by_claim(
        tenant_id=tenant_id,
        project_id=project_id,
        claim_id=claim_id,
    )


async def delete_evidence_item(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    evidence_item_id: UUID,
) -> bool:
    return await EvidenceItemRepository(session).delete_evidence_item(
        tenant_id=tenant_id,
        project_id=project_id,
        evidence_item_id=evidence_item_id,
    )


__all__ = [
    "EvidenceItemRepository",
    "create_evidence_item",
    "delete_evidence_item",
    "get_evidence_item_by_id",
    "list_evidence_items_by_claim",
]
