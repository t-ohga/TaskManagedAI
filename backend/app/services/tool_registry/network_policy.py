from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.tool_registry import ToolNetworkPolicy, ToolRegistry
from backend.app.domain.tool_registry.network_policy import (
    DATA_CLASS_ORDER,
    NetworkAccessMode,
    PayloadDataClass,
)

ToolNetworkDecisionValue = Literal["allow", "deny"]


@dataclass(frozen=True)
class ToolNetworkDecision:
    tool_key: str
    network_access: NetworkAccessMode | None
    decision: ToolNetworkDecisionValue
    reason_code: str


async def evaluate_tool_network_policy(
    session: AsyncSession,
    *,
    tenant_id: int,
    tool_key: str,
    domain: str,
    payload_data_class: PayloadDataClass,
    provider: str | None = None,
) -> ToolNetworkDecision:
    """Evaluate Tool Registry network access fail-closed.

    P0 seeds `web_fetch` and `docs_search` as `network_access='none'`, so those
    tools are registered but deny-only until a later ADR explicitly switches them
    to allowlist mode.
    """

    await _ensure_tenant_context(session, tenant_id)
    normalized_tool_key = _normalize_required_identifier(tool_key, "tool_key")
    normalized_domain = _normalize_domain(domain)

    tool = await session.scalar(
        sa.select(ToolRegistry).where(
            ToolRegistry.tenant_id == tenant_id,
            ToolRegistry.tool_key == normalized_tool_key,
        )
    )
    if tool is None:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=None,
            decision="deny",
            reason_code="tool_registry_entry_missing_denied",
        )

    if tool.network_access == "none":
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_access_none_denied",
        )
    if tool.network_access == "internet":
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_internet_denied",
        )

    policy = await session.scalar(
        sa.select(ToolNetworkPolicy).where(
            ToolNetworkPolicy.tenant_id == tenant_id,
            ToolNetworkPolicy.tool_id == tool.id,
        )
    )
    if policy is None:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_policy_missing_denied",
        )

    allowlist = _normalize_domain_allowlist(policy.domain_allowlist)
    if allowlist is None:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_allowlist_invalid_denied",
        )
    if normalized_domain not in allowlist:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_domain_not_allowlisted",
        )

    if payload_data_class not in DATA_CLASS_ORDER:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_payload_data_class_invalid_denied",
        )
    if policy.payload_data_class_max not in DATA_CLASS_ORDER:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_policy_payload_data_class_invalid_denied",
        )
    if DATA_CLASS_ORDER[payload_data_class] > DATA_CLASS_ORDER[policy.payload_data_class_max]:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_payload_data_class_exceeded",
        )

    normalized_provider = provider.strip() if provider is not None else None
    if policy.provider_required and not normalized_provider:
        return ToolNetworkDecision(
            tool_key=normalized_tool_key,
            network_access=tool.network_access,
            decision="deny",
            reason_code="tool_network_provider_required",
        )

    return ToolNetworkDecision(
        tool_key=normalized_tool_key,
        network_access=tool.network_access,
        decision="allow",
        reason_code="tool_network_allowlist_allowed",
    )


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")
    current = await get_tenant_context(session)
    if current is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


def _normalize_required_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty.")
    return normalized


def _normalize_domain(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if not normalized or "/" in normalized or ":" in normalized:
        raise ValueError("domain must be a bare DNS name.")
    return normalized


def _normalize_domain_allowlist(value: object) -> set[str] | None:
    if not isinstance(value, list):
        return None

    normalized: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return None
        try:
            normalized.add(_normalize_domain(item))
        except ValueError:
            return None
    return normalized


__all__ = ["ToolNetworkDecision", "evaluate_tool_network_policy"]
