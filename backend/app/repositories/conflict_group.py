"""SP-032 (ADR-00052): conflict_groups repository。

project-scoped methods のみ (generic CRUD は research_task binding を bypass するため block)。
title / resolution_note は persist 前に secret scan。assign は claim と group が同一 research_task に
属することを verify (4-col FK の DB enforce に加えて明示 404)。
"""

from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.claim import Claim
from backend.app.db.models.conflict_group import ConflictGroup
from backend.app.repositories.base import BaseRepository
from backend.app.services.security.secret_text_scan import assert_no_secret_in_text


class ConflictGroupRepository(BaseRepository[ConflictGroup]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ConflictGroup)

    # --- generic CRUD は research_task binding を bypass するため block ---
    async def get(self, tenant_id: int, id: UUID) -> ConflictGroup | None:
        raise NotImplementedError("Use get_conflict_group(...).")

    async def list(self, tenant_id: int) -> builtins.list[ConflictGroup]:
        raise NotImplementedError("Use list_conflict_groups_by_research_task(...).")

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> ConflictGroup:
        raise NotImplementedError("Use create_conflict_group(...).")

    async def update(
        self, tenant_id: int, id: UUID, payload: dict[str, Any]
    ) -> ConflictGroup | None:
        raise NotImplementedError("Use update_conflict_group(...).")

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("conflict_groups are not hard-deleted (use status='dismissed').")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_update(self, tenant_id: int, id: UUID, payload: dict[str, Any]) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    # --- bespoke project/research_task-scoped methods ---
    async def create_conflict_group(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        title: str,
        created_by_actor_id: UUID,
    ) -> ConflictGroup:
        await self._ensure_tenant_context(tenant_id)
        assert_no_secret_in_text(title, field="title")
        group = ConflictGroup(
            tenant_id=tenant_id,
            project_id=project_id,
            research_task_id=research_task_id,
            title=title,
            status="open",
            resolution_note=None,
            created_by_actor_id=created_by_actor_id,
        )
        self.session.add(group)
        await self.session.flush()
        return group

    async def get_conflict_group(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        group_id: UUID,
    ) -> ConflictGroup | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(ConflictGroup).where(
            ConflictGroup.tenant_id == tenant_id,
            ConflictGroup.project_id == project_id,
            ConflictGroup.research_task_id == research_task_id,
            ConflictGroup.id == group_id,
        )
        return cast("ConflictGroup | None", await self.session.scalar(stmt))

    async def list_conflict_groups_by_research_task(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
    ) -> builtins.list[ConflictGroup]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(ConflictGroup)
            .where(
                ConflictGroup.tenant_id == tenant_id,
                ConflictGroup.project_id == project_id,
                ConflictGroup.research_task_id == research_task_id,
            )
            .order_by(ConflictGroup.created_at, ConflictGroup.id)
        )
        return list(result.scalars().all())

    async def update_conflict_group(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        group_id: UUID,
        values: dict[str, Any],
    ) -> ConflictGroup | None:
        """title / status / resolution_note の部分更新。``values`` は server で組み立てた
        update fields (caller 入力ではない)。"""
        await self._ensure_tenant_context(tenant_id)
        for key in ("title", "resolution_note"):
            value = values.get(key)
            if isinstance(value, str):
                assert_no_secret_in_text(value, field=key)
        if not values:
            return await self.get_conflict_group(
                tenant_id=tenant_id,
                project_id=project_id,
                research_task_id=research_task_id,
                group_id=group_id,
            )
        result = await self.session.execute(
            update(ConflictGroup)
            .where(
                ConflictGroup.tenant_id == tenant_id,
                ConflictGroup.project_id == project_id,
                ConflictGroup.research_task_id == research_task_id,
                ConflictGroup.id == group_id,
            )
            .values(**values)
            .returning(ConflictGroup)
        )
        return result.scalar_one_or_none()

    async def assign_claim(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        group_id: UUID,
        claim_id: UUID,
    ) -> Claim | None:
        """claim を conflict_group に割当 (同一 research_task の claim のみ。4-col FK が DB enforce)。"""
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            update(Claim)
            .where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.research_task_id == research_task_id,
                Claim.id == claim_id,
            )
            .values(conflict_group_id=group_id)
            .returning(Claim)
        )
        return result.scalar_one_or_none()

    async def unassign_claim(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        research_task_id: UUID,
        group_id: UUID,
        claim_id: UUID,
    ) -> Claim | None:
        """claim を conflict_group から外す (現在その group に属している場合のみ)。"""
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            update(Claim)
            .where(
                Claim.tenant_id == tenant_id,
                Claim.project_id == project_id,
                Claim.research_task_id == research_task_id,
                Claim.id == claim_id,
                Claim.conflict_group_id == group_id,
            )
            .values(conflict_group_id=None)
            .returning(Claim)
        )
        return result.scalar_one_or_none()


__all__ = ["ConflictGroupRepository"]
