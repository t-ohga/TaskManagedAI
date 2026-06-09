"""SP-032 (ADR-00052): domain_trust_registry の API schema。

body の `tenant_id` / `metadata` / `created_by_actor_id` は extra="forbid" + 非掲載で reject
(server-owned boundary)。domain の厳密正規化は service 層の ``normalize_domain`` で行う
(Pydantic では非空 + 長さのみ)。PATCH は domain 変更不可 (R1 F-013)、trust_tier / rationale のみ。
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.db.models.domain_trust import TrustTier


def _normalize_rationale(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ValueError("rationale は空白のみにできません。")
    return normalized


class DomainTrustRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tenant_id: int
    domain: str
    trust_tier: TrustTier
    rationale: str | None
    created_by_actor_id: UUID
    created_at: datetime
    updated_at: datetime


class DomainTrustListResponse(BaseModel):
    items: list[DomainTrustRead]


class DomainTrustCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 厳密正規化は service の normalize_domain (raise → 400)。ここでは粗い長さ防御のみ。
    domain: str = Field(min_length=1, max_length=253)
    trust_tier: TrustTier
    rationale: str | None = Field(default=None, max_length=1000)

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_rationale(value)
        if len(normalized) > 1000:
            raise ValueError("rationale は 1000 文字以内です。")
        return normalized


class DomainTrustUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # R1 F-013: domain は immutable (PATCH で受け付けない)。
    trust_tier: TrustTier | None = None
    rationale: str | None = Field(default=None, max_length=1000)

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _normalize_rationale(value)
        if len(normalized) > 1000:
            raise ValueError("rationale は 1000 文字以内です。")
        return normalized


__all__ = [
    "DomainTrustCreate",
    "DomainTrustListResponse",
    "DomainTrustRead",
    "DomainTrustUpdate",
]
