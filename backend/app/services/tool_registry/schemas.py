from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.tool_registry.enums import (
    DATA_CLASS_ORDER,
    NetworkAccessMode,
    PayloadDataClass,
    ToolAllowedAction,
    ToolAuthMode,
    ToolTransport,
    ToolTrustTier,
)

_TOOL_KEY_RE = re.compile(r"^[a-z][a-z0-9_:-]{1,127}$")


class ToolRegistryMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(..., min_length=1, max_length=128)
    last_updated_at: str
    description: str = Field(..., min_length=1)

    @field_validator("last_updated_at")
    @classmethod
    def _last_updated_at_must_be_iso_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("last_updated_at must be an ISO calendar date.") from exc
        return value


class ToolRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_key: str = Field(..., min_length=2, max_length=128)
    transport: ToolTransport
    auth_mode: ToolAuthMode
    network_access: NetworkAccessMode = "none"
    allowed_actions: tuple[ToolAllowedAction, ...] = Field(..., min_length=1)
    trust_tier: ToolTrustTier
    max_outgoing_data_class: PayloadDataClass
    mcp_endpoint: str | None = None
    domain_allowlist: tuple[str, ...] = ()
    provider_required: bool = False
    notes: str = ""

    @field_validator("tool_key")
    @classmethod
    def _tool_key_must_be_canonical(cls, value: str) -> str:
        if not _TOOL_KEY_RE.fullmatch(value):
            raise ValueError(
                "tool_key must be lowercase and contain only a-z, 0-9, _, :, or -."
            )
        return value

    @field_validator("allowed_actions")
    @classmethod
    def _allowed_actions_must_be_unique(
        cls,
        value: tuple[ToolAllowedAction, ...],
    ) -> tuple[ToolAllowedAction, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_actions must not contain duplicates.")
        return value

    @field_validator("domain_allowlist")
    @classmethod
    def _domain_allowlist_must_be_canonical(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(_normalize_domain(domain) for domain in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("domain_allowlist must not contain duplicates.")
        return normalized

    @model_validator(mode="after")
    def _validate_boundary_combination(self) -> ToolRegistryEntry:
        if self.network_access == "allowlist" and not self.domain_allowlist:
            raise ValueError("network_access='allowlist' requires domain_allowlist.")
        if self.network_access != "allowlist" and self.domain_allowlist:
            raise ValueError("domain_allowlist is only valid with allowlist mode.")
        if (
            self.trust_tier == "experimental"
            and DATA_CLASS_ORDER[self.max_outgoing_data_class]
            > DATA_CLASS_ORDER["public"]
        ):
            raise ValueError(
                "experimental tools may only use max_outgoing_data_class='public'."
            )
        return self


class ToolRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    meta: ToolRegistryMeta
    tools: tuple[ToolRegistryEntry, ...] = Field(..., min_length=1)

    @property
    def registry_version(self) -> str:
        return self.meta.version


def _normalize_domain(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if not normalized or "/" in normalized or ":" in normalized:
        raise ValueError("domain_allowlist entries must be bare DNS names.")
    return normalized


__all__ = [
    "ToolRegistryDocument",
    "ToolRegistryEntry",
    "ToolRegistryMeta",
]
