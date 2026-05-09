from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.agent_runtime.provider_result_mapping import (
    ALL_PROVIDER_RESULT_KINDS,
    ProviderResultKind,
)

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    tokens_input: int = Field(..., ge=0)
    tokens_output: int = Field(..., ge=0)
    cost_usd: float = Field(..., ge=0)


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    status: ProviderResultKind
    artifact_ref: str | None = None
    usage: ProviderUsage | None = None
    model_resolved: str = Field(..., min_length=1, max_length=256)
    api_version: str = Field(..., min_length=1, max_length=128)
    sdk_version: str = Field(..., min_length=1, max_length=128)
    provider_request_fingerprint: str
    error_code: str | None = None
    error_summary: str | None = None
    redacted_response_summary: dict[str, Any]
    continuation_ref: dict[str, Any] | None = None

    @field_validator("status")
    @classmethod
    def _status_must_match_provider_result_kind(
        cls,
        value: ProviderResultKind,
    ) -> ProviderResultKind:
        if value not in ALL_PROVIDER_RESULT_KINDS:
            raise ValueError(f"unknown provider result kind: {value!r}")
        return value

    @field_validator("provider_request_fingerprint")
    @classmethod
    def _fingerprint_must_be_sha256_hex(cls, value: str) -> str:
        if _SHA256_HEX_RE.fullmatch(value) is None:
            raise ValueError("provider_request_fingerprint must be SHA-256 64 hex.")
        return value

    @field_validator("error_summary")
    @classmethod
    def _error_summary_must_be_redacted(cls, value: str | None) -> str | None:
        if value is not None:
            assert_no_raw_secret({"error_summary": value}, path="$provider_result")
        return value

    @field_validator("redacted_response_summary")
    @classmethod
    def _redacted_response_summary_must_be_json_safe_without_raw_secret(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        assert_no_raw_secret(value, path="$provider_result.redacted_response_summary")
        return value

    @field_validator("continuation_ref", mode="before")
    @classmethod
    def _continuation_ref_must_be_non_exportable(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("continuation_ref must be a JSON object or None.")

        normalized = dict(value)
        if normalized.get("exportable") not in (None, False):
            raise ValueError("continuation_ref.exportable must be false.")
        normalized["exportable"] = False
        return normalized

    @field_validator("continuation_ref")
    @classmethod
    def _continuation_ref_must_be_json_safe_without_raw_secret(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is not None:
            assert_no_raw_secret(value, path="$provider_result.continuation_ref")
        return value


__all__ = ["ProviderResult", "ProviderUsage"]

