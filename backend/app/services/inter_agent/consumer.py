from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.inter_agent_message import InterAgentMessage
from backend.app.schemas.inter_agent import InterAgentConsumeRequest
from backend.app.services.inter_agent.event_writer import InterAgentEventWriter
from backend.app.services.orchestrator._shared import ensure_tenant_context

InterAgentConsumeDenyReason = Literal[
    "not_found",
    "already_consumed",
    "expired",
    "sender_self_consume",
    "previous_hash_mismatch",
    "receiver_ineligible",
]


class InterAgentConsumeDenied(ValueError):
    def __init__(self, reason_code: InterAgentConsumeDenyReason) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class InterAgentConsumeResult:
    message: InterAgentMessage
    artifact_ref: str
    payload_hash: str
    seq_no: int
    previous_hash: str | None


@dataclass(frozen=True)
class _DenialClassification:
    reason_code: InterAgentConsumeDenyReason
    message: InterAgentMessage | None


class InterAgentConsumerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def consume(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        actor_id: UUID,
        request: InterAgentConsumeRequest,
    ) -> InterAgentConsumeResult:
        await ensure_tenant_context(self.session, tenant_id)

        stmt = (
            sa.update(InterAgentMessage)
            .where(
                InterAgentMessage.tenant_id == tenant_id,
                InterAgentMessage.project_id == project_id,
                InterAgentMessage.parent_run_id == request.parent_run_id,
                InterAgentMessage.id == request.message_id,
                InterAgentMessage.consumed_at.is_(None),
                InterAgentMessage.consumed_by_run_id.is_(None),
                InterAgentMessage.expires_at > sa.func.now(),
                InterAgentMessage.sender_run_id != request.consumer_run_id,
                self._receiver_eligibility_clause(request.consumer_run_id),
                self._previous_hash_chain_clause(),
            )
            .values(
                consumed_at=sa.func.now(),
                consumed_by_run_id=request.consumer_run_id,
            )
            .returning(InterAgentMessage)
        )
        message = (await self.session.execute(stmt)).scalar_one_or_none()
        if message is None:
            denial = await self._classify_denial(
                tenant_id=tenant_id,
                project_id=project_id,
                request=request,
            )
            await InterAgentEventWriter(self.session).append_denied(
                tenant_id=tenant_id,
                project_id=project_id,
                parent_run_id=request.parent_run_id,
                attempted_message_id=request.message_id,
                denial_reason=denial.reason_code,
                actor_id=actor_id,
                message=denial.message,
            )
            raise InterAgentConsumeDenied(denial.reason_code)

        await InterAgentEventWriter(self.session).append_consumed(
            message=message,
            consumed_by_run_id=request.consumer_run_id,
            actor_id=actor_id,
        )

        return InterAgentConsumeResult(
            message=message,
            artifact_ref=message.artifact_ref,
            payload_hash=message.payload_hash,
            seq_no=message.seq_no,
            previous_hash=message.previous_hash,
        )

    @staticmethod
    def _receiver_eligibility_clause(consumer_run_id: UUID) -> sa.ColumnElement[bool]:
        direct_child_exists = (
            sa.select(sa.literal(1))
            .select_from(AgentRun)
            .where(
                AgentRun.tenant_id == InterAgentMessage.tenant_id,
                AgentRun.project_id == InterAgentMessage.project_id,
                AgentRun.id == consumer_run_id,
                AgentRun.parent_run_id == InterAgentMessage.parent_run_id,
            )
            .exists()
        )
        role_child_exists = (
            sa.select(sa.literal(1))
            .select_from(AgentRun)
            .where(
                AgentRun.tenant_id == InterAgentMessage.tenant_id,
                AgentRun.project_id == InterAgentMessage.project_id,
                AgentRun.id == consumer_run_id,
                AgentRun.parent_run_id == InterAgentMessage.parent_run_id,
                AgentRun.role_id == InterAgentMessage.receiver_ref,
            )
            .exists()
        )

        return sa.or_(
            sa.and_(
                InterAgentMessage.receiver_kind == "agent_run",
                InterAgentMessage.child_run_id == consumer_run_id,
                direct_child_exists,
            ),
            sa.and_(
                InterAgentMessage.receiver_kind == "role",
                role_child_exists,
            ),
            sa.and_(
                InterAgentMessage.receiver_kind == "broadcast",
                direct_child_exists,
            ),
        )

    @staticmethod
    def _previous_hash_chain_clause() -> sa.ColumnElement[bool]:
        previous = sa.orm.aliased(InterAgentMessage)
        previous_exists = (
            sa.select(sa.literal(1))
            .select_from(previous)
            .where(
                previous.tenant_id == InterAgentMessage.tenant_id,
                previous.project_id == InterAgentMessage.project_id,
                previous.parent_run_id == InterAgentMessage.parent_run_id,
                previous.seq_no == InterAgentMessage.seq_no - 1,
                previous.payload_hash == InterAgentMessage.previous_hash,
            )
            .exists()
        )
        return sa.or_(
            sa.and_(
                InterAgentMessage.seq_no == 1,
                InterAgentMessage.previous_hash.is_(None),
            ),
            previous_exists,
        )

    async def _classify_denial(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        request: InterAgentConsumeRequest,
    ) -> _DenialClassification:
        message = await self.session.scalar(
            sa.select(InterAgentMessage).where(
                InterAgentMessage.tenant_id == tenant_id,
                InterAgentMessage.project_id == project_id,
                InterAgentMessage.parent_run_id == request.parent_run_id,
                InterAgentMessage.id == request.message_id,
            )
        )
        if message is None:
            return _DenialClassification(reason_code="not_found", message=None)
        if message.consumed_at is not None or message.consumed_by_run_id is not None:
            return _DenialClassification(reason_code="already_consumed", message=message)
        if await self._is_expired(message):
            return _DenialClassification(reason_code="expired", message=message)
        if message.sender_run_id == request.consumer_run_id:
            return _DenialClassification(
                reason_code="sender_self_consume",
                message=message,
            )
        if not await self._previous_hash_matches(message):
            return _DenialClassification(
                reason_code="previous_hash_mismatch",
                message=message,
            )
        return _DenialClassification(reason_code="receiver_ineligible", message=message)

    async def _is_expired(self, message: InterAgentMessage) -> bool:
        return bool(
            await self.session.scalar(
                sa.select(sa.literal(True)).where(
                    InterAgentMessage.tenant_id == message.tenant_id,
                    InterAgentMessage.id == message.id,
                    InterAgentMessage.expires_at <= sa.func.now(),
                )
            )
        )

    async def _previous_hash_matches(self, message: InterAgentMessage) -> bool:
        if message.seq_no == 1:
            return message.previous_hash is None
        if message.previous_hash is None:
            return False
        previous_hash = await self.session.scalar(
            sa.select(InterAgentMessage.payload_hash).where(
                InterAgentMessage.tenant_id == message.tenant_id,
                InterAgentMessage.project_id == message.project_id,
                InterAgentMessage.parent_run_id == message.parent_run_id,
                InterAgentMessage.seq_no == message.seq_no - 1,
            )
        )
        return previous_hash == message.previous_hash


__all__ = [
    "InterAgentConsumeDenied",
    "InterAgentConsumeDenyReason",
    "InterAgentConsumeResult",
    "InterAgentConsumerService",
]
