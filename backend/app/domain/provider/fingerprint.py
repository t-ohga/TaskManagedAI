from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.agent_runtime.operation_context import (
    canonical_json_dumps,
    compute_payload_hash,
)
from backend.app.domain.provider.request import ProviderRequest

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


class ProviderRequestFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_resolved: str = Field(..., min_length=1, max_length=256)
    api_version: str = Field(..., min_length=1, max_length=128)
    sdk_version: str = Field(..., min_length=1, max_length=128)
    temperature: float | None = None
    safety_settings_hash: str | None = None
    request_payload_hash: str
    provider_compliance_matrix_version: str = Field(..., min_length=1, max_length=128)

    @field_validator("safety_settings_hash", "request_payload_hash")
    @classmethod
    def _hash_fields_must_be_sha256_hex_or_none(cls, value: str | None) -> str | None:
        if value is not None and _SHA256_HEX_RE.fullmatch(value) is None:
            raise ValueError("hash fields must be SHA-256 lowercase 64 hex.")
        return value


def build_provider_request_fingerprint(
    req: ProviderRequest,
    *,
    matrix_version: str,
    api_version: str = "unknown",
    sdk_version: str = "unknown",
) -> ProviderRequestFingerprint:
    _require_matching_matrix_version(req, matrix_version)

    safety_settings_hash = (
        None if req.safety_settings is None else compute_payload_hash(req.safety_settings)
    )
    request_payload = req.model_dump(mode="json", exclude={"secret_capability_token"})
    request_payload_hash = compute_payload_hash(request_payload)

    return ProviderRequestFingerprint(
        model_resolved=req.model_resolved,
        api_version=api_version,
        sdk_version=sdk_version,
        temperature=req.temperature,
        safety_settings_hash=safety_settings_hash,
        request_payload_hash=request_payload_hash,
        provider_compliance_matrix_version=matrix_version,
    )


def provider_request_fingerprint_payload(
    req: ProviderRequest,
    *,
    matrix_version: str,
    api_version: str = "unknown",
    sdk_version: str = "unknown",
) -> dict[str, Any]:
    return build_provider_request_fingerprint(
        req,
        matrix_version=matrix_version,
        api_version=api_version,
        sdk_version=sdk_version,
    ).model_dump(mode="json")


def compute_provider_request_fingerprint(
    req: ProviderRequest,
    *,
    matrix_version: str,
    api_version: str = "unknown",
    sdk_version: str = "unknown",
) -> str:
    payload = provider_request_fingerprint_payload(
        req,
        matrix_version=matrix_version,
        api_version=api_version,
        sdk_version=sdk_version,
    )
    canonical_json = canonical_json_dumps(payload)
    normalized = unicodedata.normalize("NFC", canonical_json)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _require_matching_matrix_version(req: ProviderRequest, matrix_version: str) -> None:
    if not isinstance(matrix_version, str) or not matrix_version:
        raise ValueError("matrix_version must be a non-empty string.")
    if matrix_version != req.provider_compliance_matrix_version:
        raise ValueError(
            "matrix_version must match req.provider_compliance_matrix_version."
        )


__all__ = [
    "ProviderRequestFingerprint",
    "build_provider_request_fingerprint",
    "compute_provider_request_fingerprint",
    "provider_request_fingerprint_payload",
]

