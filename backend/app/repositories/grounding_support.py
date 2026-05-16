"""GroundingSupport repository (Sprint 10 BL-0119).

server-owned-boundary §1 invariants:
- ``id`` / ``tenant_id`` / ``project_id`` / ``run_id`` / ``created_at`` /
  ``updated_at`` are NOT caller-supplied. The repository strips any
  value the caller smuggles through.
- ``run_id`` is derived from ``agent_run_id`` (the
  ``run_id = agent_run_id`` CHECK enforces this at the DB layer).
- generic ``BaseRepository`` mutators are overridden with
  ``NotImplementedError`` so cross-project mutate bypass routes are
  blocked.
"""

from __future__ import annotations

import builtins
from typing import Any, NoReturn, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.grounding_support import GroundingSupport
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.base import BaseRepository

_SERVER_OWNED_FIELDS: frozenset[str] = frozenset(
    # F-PR25-R1-002 fix (Codex R1 P1): ``tenant_id`` is server-owned but
    # MUST NOT be popped here — ``_payload_with_tenant_id`` just injected
    # the authenticated value above, and popping would fall through to
    # the DB column default (``1``), corrupting non-default tenants.
    # Strip ``id`` / ``project_id`` / ``run_id`` / timestamps (the
    # repository derives ``project_id`` + ``run_id`` from the path and
    # the ``agent_run_id``); keep ``tenant_id`` so the trusted injected
    # value reaches the INSERT.
    {"id", "project_id", "run_id", "created_at", "updated_at"}
)


def _model_payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump()
    return dict(value)


class GroundingSupportRepository(BaseRepository[GroundingSupport]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GroundingSupport)

    async def get(self, tenant_id: int, id: UUID) -> GroundingSupport | None:
        raise NotImplementedError("Use get_grounding_support_by_id(...).")

    async def list(self, tenant_id: int) -> builtins.list[GroundingSupport]:
        raise NotImplementedError("Use list_grounding_supports_by_agent_run(...).")

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> GroundingSupport | None:
        # GroundingSupport rows are append-only audit-style records of
        # the citation graph at artifact-generation time. Updates would
        # silently re-target an existing row to a different claim /
        # source / item, which is exactly the cross-project bypass
        # route we are blocking. F-R4-002 mirror of claims/evidence_items.
        raise NotImplementedError(
            "grounding_supports are immutable in P0; delete + recreate instead."
        )

    async def delete(self, tenant_id: int, id: UUID) -> int:
        raise NotImplementedError("Use delete_grounding_support(...).")

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> GroundingSupport:
        raise NotImplementedError("Use create_grounding_support(...).")

    def statement_for_get(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_list(self, tenant_id: int) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("grounding_supports are immutable in P0.")

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("Use project-scoped methods.")

    async def create_grounding_support(
        self,
        tenant_id: int,
        project_id: UUID,
        grounding_support_create: BaseModel | dict[str, Any],
    ) -> GroundingSupport:
        await self._ensure_tenant_context(tenant_id)
        data = self._payload_with_tenant_id(
            tenant_id, _model_payload(grounding_support_create)
        )

        # server-owned-boundary §1: strip caller-supplied server-owned
        # fields before constructing the ORM row.
        for forbidden in _SERVER_OWNED_FIELDS:
            data.pop(forbidden, None)

        # F-PR19-R10-002 mirror: enforce rls_ready: true at the DB column
        # name level (``metadata_``) so dict callers that bypass the
        # Pydantic schema's validator cannot turn it off.
        for key in ("metadata", "metadata_"):
            metadata = data.get(key)
            if isinstance(metadata, dict):
                metadata["rls_ready"] = True
                break
        else:
            data["metadata_"] = {"rls_ready": True}

        # Secret scan on the caller-supplied subset. UUID-typed FK
        # columns are not JSON-serialisable so we strip them before
        # scanning (mirror evidence_item.create_evidence_item).
        scan_data = {k: v for k, v in data.items() if not isinstance(v, UUID)}
        assert_no_raw_secret(scan_data, path="$grounding_support_create")

        agent_run_id = data.get("agent_run_id")
        if not isinstance(agent_run_id, UUID):
            raise ValueError("agent_run_id must be a UUID.")
        # Server derives run_id from agent_run_id — the equality CHECK
        # constraint in migration 0018 then makes the two columns
        # logically identical without exposing a caller-controlled
        # ``run_id`` parameter.
        data["run_id"] = agent_run_id
        data["project_id"] = project_id

        support = GroundingSupport(**data)
        self.session.add(support)
        await self.session.flush()
        return support

    async def get_grounding_support_by_id(
        self,
        tenant_id: int,
        project_id: UUID,
        grounding_support_id: UUID,
    ) -> GroundingSupport | None:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(GroundingSupport).where(
            GroundingSupport.tenant_id == tenant_id,
            GroundingSupport.project_id == project_id,
            GroundingSupport.id == grounding_support_id,
        )
        return cast(GroundingSupport | None, await self.session.scalar(stmt))

    async def list_grounding_supports_by_agent_run(
        self,
        tenant_id: int,
        project_id: UUID,
        agent_run_id: UUID,
    ) -> builtins.list[GroundingSupport]:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            select(GroundingSupport)
            .where(
                GroundingSupport.tenant_id == tenant_id,
                GroundingSupport.project_id == project_id,
                GroundingSupport.agent_run_id == agent_run_id,
            )
            .order_by(
                GroundingSupport.claim_id,
                GroundingSupport.evidence_item_id,
                GroundingSupport.id,
            )
        )
        return list(result.scalars().all())

    async def delete_grounding_support(
        self,
        tenant_id: int,
        project_id: UUID,
        grounding_support_id: UUID,
    ) -> bool:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.execute(
            delete(GroundingSupport)
            .where(
                GroundingSupport.tenant_id == tenant_id,
                GroundingSupport.project_id == project_id,
                GroundingSupport.id == grounding_support_id,
            )
            .returning(GroundingSupport.id)
        )
        return result.scalar_one_or_none() is not None


async def create_grounding_support(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    grounding_support_create: BaseModel | dict[str, Any],
) -> GroundingSupport:
    return await GroundingSupportRepository(session).create_grounding_support(
        tenant_id=tenant_id,
        project_id=project_id,
        grounding_support_create=grounding_support_create,
    )


async def get_grounding_support_by_id(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    grounding_support_id: UUID,
) -> GroundingSupport | None:
    return await GroundingSupportRepository(session).get_grounding_support_by_id(
        tenant_id=tenant_id,
        project_id=project_id,
        grounding_support_id=grounding_support_id,
    )


async def list_grounding_supports_by_agent_run(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    agent_run_id: UUID,
) -> list[GroundingSupport]:
    return await GroundingSupportRepository(session).list_grounding_supports_by_agent_run(
        tenant_id=tenant_id,
        project_id=project_id,
        agent_run_id=agent_run_id,
    )


async def delete_grounding_support(
    session: AsyncSession,
    tenant_id: int,
    project_id: UUID,
    grounding_support_id: UUID,
) -> bool:
    return await GroundingSupportRepository(session).delete_grounding_support(
        tenant_id=tenant_id,
        project_id=project_id,
        grounding_support_id=grounding_support_id,
    )


__all__ = [
    "GroundingSupportRepository",
    "create_grounding_support",
    "delete_grounding_support",
    "get_grounding_support_by_id",
    "list_grounding_supports_by_agent_run",
]
