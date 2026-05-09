from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from backend.app.domain.provider.result import ProviderResult, ProviderUsage
from backend.app.services.agent_runtime.provider_result_mapping import (
    ALL_PROVIDER_RESULT_KINDS,
)


def _result_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "success",
        "artifact_ref": "artifact-1",
        "usage": {
            "tokens_input": 10,
            "tokens_output": 5,
            "cost_usd": 0.0015,
        },
        "model_resolved": "mock-model",
        "api_version": "mock-v1",
        "sdk_version": "mock-1.0",
        "provider_request_fingerprint": "a" * 64,
        "error_code": None,
        "error_summary": None,
        "redacted_response_summary": {"answer": "ok"},
        "continuation_ref": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("status", ALL_PROVIDER_RESULT_KINDS)
def test_provider_result_status_accepts_only_provider_result_kind_values(status: str) -> None:
    result = ProviderResult.model_validate(_result_payload(status=status))

    assert result.status == status

    with pytest.raises(ValidationError):
        ProviderResult.model_validate(_result_payload(status="unknown_kind"))


def test_provider_usage_cost_must_be_non_negative() -> None:
    ProviderUsage(tokens_input=0, tokens_output=0, cost_usd=0)

    with pytest.raises(ValidationError):
        ProviderUsage(tokens_input=0, tokens_output=0, cost_usd=-0.01)


def test_provider_request_fingerprint_must_be_sha256_hex() -> None:
    result = ProviderResult.model_validate(_result_payload())
    assert re.fullmatch(r"[a-f0-9]{64}", result.provider_request_fingerprint)

    with pytest.raises(ValidationError):
        ProviderResult.model_validate(
            _result_payload(provider_request_fingerprint="not-a-sha256")
        )


def test_error_summary_rejects_raw_secret_patterns() -> None:
    with pytest.raises(ValidationError):
        ProviderResult.model_validate(
            _result_payload(error_summary="provider returned -----BEGIN PRIVATE KEY-----")
        )


def test_redacted_response_summary_rejects_prohibited_secret_keys() -> None:
    with pytest.raises(ValidationError):
        ProviderResult.model_validate(
            _result_payload(redacted_response_summary={"raw_secret": "redacted"})
        )


def test_continuation_ref_forces_exportable_false() -> None:
    result = ProviderResult.model_validate(
        _result_payload(continuation_ref={"provider": "mock", "kind": "continuation"})
    )

    assert result.continuation_ref is not None
    assert result.continuation_ref["exportable"] is False

    with pytest.raises(ValidationError):
        ProviderResult.model_validate(_result_payload(continuation_ref={"exportable": True}))

