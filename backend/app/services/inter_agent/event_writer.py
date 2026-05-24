from __future__ import annotations

import hashlib
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.inter_agent_message import InterAgentMessage
from backend.app.repositories.agent_run_event import AgentRunEventRepository
from backend.app.repositories.audit_event import AuditEventRepository

InterAgentAuditEventType = Literal[
    "inter_agent_message_sent",
    "inter_agent_message_consumed",
    "inter_agent_message_denied",
]

_RAW_MESSAGE_BODY_KEYS: frozenset[str] = frozenset(
    {
        "artifact",
        "artifact_body",
        "artifact_content",
        "content",
        "content_jsonb",
        "message",
        "message_body",
        "payload",
        "raw_payload",
        "text",
    }
)


class InterAgentEventPayloadError(ValueError):
    """Raised when an inter-agent audit/timeline payload is not ref-only."""


class InterAgentEventWriter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append_sent(
        self,
        *,
        message: InterAgentMessage,
        actor_id: UUID,
    ) -> tuple[AuditEvent, AgentRunEvent]:
        audit_payload = self._sent_audit_payload(message)
        audit_event = await self._append_audit(
            tenant_id=message.tenant_id,
            event_type="inter_agent_message_sent",
            payload=audit_payload,
            actor_id=actor_id,
            correlation_id=_correlation_id(message.id),
        )
        run_event = await self._append_run_event(
            tenant_id=message.tenant_id,
            run_id=message.sender_run_id,
            event_type="inter_agent_message_sent_ref",
            payload=self._run_ref_payload(message),
            actor_id=actor_id,
            idempotency_key=f"inter-agent:sent:{message.id}",
        )
        return audit_event, run_event

    async def append_consumed(
        self,
        *,
        message: InterAgentMessage,
        consumed_by_run_id: UUID,
        actor_id: UUID,
    ) -> tuple[AuditEvent, AgentRunEvent]:
        audit_payload = {
            "tenant_id": message.tenant_id,
            "project_id": str(message.project_id),
            "parent_run_id": str(message.parent_run_id),
            "consumed_by_run_id": str(consumed_by_run_id),
            "message_id_hash": _hash_uuid(message.id),
            "seq_no": message.seq_no,
            "previous_hash_match": True,
            "payload_hash": message.payload_hash,
            "redaction_status": "ref_only",
        }
        audit_event = await self._append_audit(
            tenant_id=message.tenant_id,
            event_type="inter_agent_message_consumed",
            payload=audit_payload,
            actor_id=actor_id,
            correlation_id=_correlation_id(message.id),
        )
        run_event = await self._append_run_event(
            tenant_id=message.tenant_id,
            run_id=consumed_by_run_id,
            event_type="inter_agent_message_consumed_ref",
            payload=self._run_ref_payload(message, receiver_run_id=consumed_by_run_id),
            actor_id=actor_id,
            idempotency_key=f"inter-agent:consumed:{message.id}:{consumed_by_run_id}",
        )
        return audit_event, run_event

    async def append_denied(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        parent_run_id: UUID,
        attempted_message_id: UUID,
        denial_reason: str,
        actor_id: UUID,
        message: InterAgentMessage | None = None,
    ) -> AuditEvent:
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "project_id": str(project_id),
            "parent_run_id": str(parent_run_id),
            "attempted_message_id_hash": _hash_uuid(attempted_message_id),
            "seq_no": message.seq_no if message is not None else 0,
            "denial_reason": denial_reason,
            "redaction_status": "ref_only",
        }
        if message is not None:
            payload["payload_hash"] = message.payload_hash
        return await self._append_audit(
            tenant_id=tenant_id,
            event_type="inter_agent_message_denied",
            payload=payload,
            actor_id=actor_id,
            correlation_id=_correlation_id(attempted_message_id),
        )

    async def append_publish_denied(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        parent_run_id: UUID,
        idempotency_key: str,
        denial_reason: str,
        actor_id: UUID,
    ) -> AuditEvent:
        attempted_hash = _hash_text(idempotency_key)
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "project_id": str(project_id),
            "parent_run_id": str(parent_run_id),
            "attempted_message_id_hash": attempted_hash,
            "seq_no": 0,
            "denial_reason": denial_reason,
            "redaction_status": "ref_only",
        }
        return await self._append_audit(
            tenant_id=tenant_id,
            event_type="inter_agent_message_denied",
            payload=payload,
            actor_id=actor_id,
            correlation_id=f"inter-agent:{attempted_hash}",
        )

    async def _append_audit(
        self,
        *,
        tenant_id: int,
        event_type: InterAgentAuditEventType,
        payload: dict[str, Any],
        actor_id: UUID,
        correlation_id: str,
    ) -> AuditEvent:
        _assert_ref_only_payload(payload)
        return await AuditEventRepository(self.session).append(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    async def _append_run_event(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        event_type: Literal[
            "inter_agent_message_sent_ref",
            "inter_agent_message_consumed_ref",
        ],
        payload: dict[str, Any],
        actor_id: UUID,
        idempotency_key: str,
    ) -> AgentRunEvent:
        _assert_ref_only_payload(payload)
        return await AgentRunEventRepository(self.session).append_event(
            tenant_id=tenant_id,
            run_id=run_id,
            event_type=event_type,
            event_payload=payload,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _sent_audit_payload(message: InterAgentMessage) -> dict[str, Any]:
        return {
            "tenant_id": message.tenant_id,
            "project_id": str(message.project_id),
            "parent_run_id": str(message.parent_run_id),
            "sender_run_id": str(message.sender_run_id),
            "sender_actor_id": str(message.sender_actor_id),
            "receiver_kind": message.receiver_kind,
            "receiver_ref": message.receiver_ref,
            "seq_no": message.seq_no,
            "payload_hash": message.payload_hash,
            "payload_data_class": message.payload_data_class,
            "trust_level": message.trust_level,
            "schema_version": message.schema_version,
            "redaction_status": "ref_only",
        }

    @staticmethod
    def _run_ref_payload(
        message: InterAgentMessage,
        *,
        receiver_run_id: UUID | None = None,
    ) -> dict[str, Any]:
        return {
            "message_id": str(message.id),
            "payload_hash": message.payload_hash,
            "seq_no": message.seq_no,
            "sender_run_id": str(message.sender_run_id),
            "receiver_run_id": str(receiver_run_id or message.child_run_id)
            if (receiver_run_id or message.child_run_id) is not None
            else None,
            "redaction_status": "ref_only",
        }


def _hash_uuid(value: UUID) -> str:
    return _hash_text(str(value))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _correlation_id(message_id: UUID) -> str:
    return f"inter-agent:{_hash_uuid(message_id)}"


def _assert_ref_only_payload(payload: object, *, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if not isinstance(key, str):
                raise InterAgentEventPayloadError(
                    f"inter-agent event payload contains non-string key at {path}."
                )
            if key in _RAW_MESSAGE_BODY_KEYS:
                raise InterAgentEventPayloadError(
                    f"inter-agent event payload must be ref-only; rejected key {key!r}."
                )
            _assert_ref_only_payload(value, path=f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _assert_ref_only_payload(value, path=f"{path}[{index}]")


__all__ = [
    "InterAgentAuditEventType",
    "InterAgentEventPayloadError",
    "InterAgentEventWriter",
]
