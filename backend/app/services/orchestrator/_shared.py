from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.domain.agent_runtime.status import TERMINAL_STATES

ORCHESTRATOR_ROLE_ID = "orchestrator"
TERMINAL_STATUS_VALUES = tuple(sorted(TERMINAL_STATES))


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def lease_token_hash(token: UUID | None) -> str | None:
    if token is None:
        return None
    return sha256(token.bytes).hexdigest()


def require_positive_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")


async def ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    require_positive_tenant_id(tenant_id)
    current = await get_tenant_context(session)
    if current is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


__all__ = [
    "ORCHESTRATOR_ROLE_ID",
    "TERMINAL_STATUS_VALUES",
    "ensure_tenant_context",
    "lease_token_hash",
    "require_positive_tenant_id",
    "utc_now",
]
