from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.principal import Principal
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        actor_id: UUID | None = None,
        principal_id: UUID | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> AuditEvent:
        assert_no_raw_secret(payload, path="$audit_payload")
        await self._ensure_tenant_context(tenant_id)
        await self._assert_principal_matches_actor(
            tenant_id=tenant_id,
            actor_id=actor_id,
            principal_id=principal_id,
        )

        event = AuditEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            event_payload=payload,
            actor_id=actor_id,
            principal_id=principal_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def _assert_principal_matches_actor(
        self,
        *,
        tenant_id: int,
        actor_id: UUID | None,
        principal_id: UUID | None,
    ) -> None:
        if principal_id is None:
            return

        if actor_id is None:
            raise ValueError("actor_id is required when principal_id is provided.")

        principal_actor_id = await self.session.scalar(
            select(Principal.actor_id).where(
                Principal.tenant_id == tenant_id,
                Principal.id == principal_id,
            )
        )
        if principal_actor_id != actor_id:
            raise ValueError("principal_id must belong to actor_id.")

    async def _ensure_tenant_context(self, tenant_id: int) -> None:
        self._require_tenant_id(tenant_id)
        current_tenant_id = await get_tenant_context(self.session)
        if current_tenant_id is None:
            await set_tenant_context(self.session, tenant_id)
        await assert_tenant_context(self.session, tenant_id)

    @staticmethod
    def _require_tenant_id(tenant_id: int) -> None:
        if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
            raise ValueError("tenant_id must be a positive integer.")


__all__ = ["AuditEventRepository"]

