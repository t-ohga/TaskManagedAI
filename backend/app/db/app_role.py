from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _require_positive_tenant_id(tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")


async def set_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    """Set the PostgreSQL transaction-local tenant context for repository calls.

    Sprint 2 Batch 1 keeps this as a skeleton over app.tenant_id. Batch 4 will
    connect this contract to PostgreSQL ROLE separation and RLS policies.
    """

    _require_positive_tenant_id(tenant_id)
    await session.execute(
        text("select set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def get_tenant_context(session: AsyncSession) -> int | None:
    value = await session.scalar(
        text("select nullif(current_setting('app.tenant_id', true), '')")
    )
    if value is None:
        return None

    try:
        tenant_id = int(str(value))
    except ValueError as exc:
        raise ValueError("app.tenant_id must be a positive integer when set.") from exc

    _require_positive_tenant_id(tenant_id)
    return tenant_id


async def assert_tenant_context(session: AsyncSession, expected_tenant_id: int) -> None:
    _require_positive_tenant_id(expected_tenant_id)
    current_tenant_id = await get_tenant_context(session)

    if current_tenant_id != expected_tenant_id:
        raise ValueError(
            "tenant context mismatch: "
            f"expected {expected_tenant_id}, current {current_tenant_id}."
        )


__all__ = ["assert_tenant_context", "get_tenant_context", "set_tenant_context"]

