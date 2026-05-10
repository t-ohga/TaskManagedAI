from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.domain.agent_runtime.event_type import AgentRunEventType
from backend.app.repositories._payload_secret_scan import (
    _PROHIBITED_PAYLOAD_KEYS,
    _RAW_SECRET_PATTERNS,
    assert_no_raw_secret,
)
from backend.app.repositories.base import BaseRepository


class AgentRunEventRepository(BaseRepository[AgentRunEvent]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, AgentRunEvent, tenant_id=tenant_id)

    async def create(self, tenant_id: int, payload: dict[str, Any]) -> NoReturn:
        raise NotImplementedError(
            "AgentRunEvent は append-only。append_event 以外の create は禁止。"
        )

    async def update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError("AgentRunEvent は append-only。update は禁止。")

    async def delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError("AgentRunEvent は append-only。delete は禁止。")

    def statement_for_update(
        self,
        tenant_id: int,
        id: UUID,
        payload: dict[str, Any],
    ) -> NoReturn:
        raise NotImplementedError(
            "AgentRunEvent は append-only。statement_for_update は禁止。"
        )

    def statement_for_delete(self, tenant_id: int, id: UUID) -> NoReturn:
        raise NotImplementedError(
            "AgentRunEvent は append-only。statement_for_delete は禁止。"
        )

    async def current_last_seq_no(self, *, tenant_id: int, run_id: UUID) -> int:
        await self._ensure_tenant_context(tenant_id)
        result = await self.session.scalar(
            sa.select(sa.func.coalesce(sa.func.max(AgentRunEvent.seq_no), 0)).where(
                AgentRunEvent.tenant_id == tenant_id,
                AgentRunEvent.run_id == run_id,
            )
        )
        return int(result or 0)

    async def append_event(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        event_type: AgentRunEventType,
        event_payload: dict[str, Any],
        actor_id: UUID,
        idempotency_key: str | None = None,
        expected_previous_seq_no: int | None = None,
    ) -> AgentRunEvent:
        await self._ensure_tenant_context(tenant_id)
        self._assert_event_payload_contract(event_payload)

        previous_seq_no = (
            await self.current_last_seq_no(tenant_id=tenant_id, run_id=run_id)
            if expected_previous_seq_no is None
            else expected_previous_seq_no
        )
        if previous_seq_no < 0:
            raise ValueError("expected_previous_seq_no must be zero or greater.")

        next_seq_no = sa.func.coalesce(sa.func.max(AgentRunEvent.seq_no), 0) + 1
        source_select = (
            sa.select(
                sa.literal(uuid4(), type_=PG_UUID(as_uuid=True)),
                sa.literal(tenant_id, type_=sa.BigInteger()),
                sa.literal(run_id, type_=PG_UUID(as_uuid=True)),
                next_seq_no,
                sa.literal(event_type, type_=sa.Text()),
                sa.literal(event_payload, type_=JSONB),
                sa.literal(actor_id, type_=PG_UUID(as_uuid=True)),
                sa.literal(idempotency_key, type_=sa.Text()),
            )
            .select_from(AgentRunEvent)
            .where(
                AgentRunEvent.tenant_id == tenant_id,
                AgentRunEvent.run_id == run_id,
            )
            .having(
                sa.func.coalesce(sa.func.max(AgentRunEvent.seq_no), 0)
                == sa.literal(previous_seq_no, type_=sa.BigInteger())
            )
        )

        stmt = (
            postgresql_insert(AgentRunEvent)
            .from_select(
                [
                    "id",
                    "tenant_id",
                    "run_id",
                    "seq_no",
                    "event_type",
                    "event_payload",
                    "actor_id",
                    "idempotency_key",
                ],
                source_select,
            )
            .returning(AgentRunEvent)
        )
        result = await self.session.execute(stmt)
        event = result.scalar_one_or_none()
        if event is None:
            raise ValueError(
                "AgentRunEvent append requires retry: expected_previous_seq_no "
                f"{previous_seq_no} no longer matches current run event tail."
            )
        return event

    @classmethod
    def _assert_event_payload_contract(cls, event_payload: dict[str, Any]) -> None:
        if not isinstance(event_payload, dict):
            raise ValueError("AgentRunEvent event_payload must be a JSON object.")

        assert_no_raw_secret(event_payload, path="$payload")


async def append_event(
    session: AsyncSession,
    *,
    tenant_id: int,
    run_id: UUID,
    event_type: AgentRunEventType,
    actor_id: UUID,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    expected_previous_seq_no: int | None = None,
) -> AgentRunEvent:
    return await AgentRunEventRepository(session).append_event(
        tenant_id=tenant_id,
        run_id=run_id,
        event_type=event_type,
        event_payload=payload,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        expected_previous_seq_no=expected_previous_seq_no,
    )


__all__ = [
    "AgentRunEventRepository",
    "_PROHIBITED_PAYLOAD_KEYS",
    "_RAW_SECRET_PATTERNS",
    "append_event",
    "assert_no_raw_secret",
]

