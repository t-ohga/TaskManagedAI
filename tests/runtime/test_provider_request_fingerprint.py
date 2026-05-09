from __future__ import annotations

import re
from uuid import UUID

from backend.app.domain.provider.fingerprint import (
    compute_provider_request_fingerprint,
    provider_request_fingerprint_payload,
)
from backend.app.domain.provider.request import ProviderRequest

RUN_ID = UUID("00000000-0000-4000-8000-000000005901")


def _request(
    *,
    model_resolved: str = "mock-model",
    temperature: float | None = 0.2,
    safety_settings: dict[str, object] | None = None,
    matrix_version: str = "pcm-v1",
) -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": "mock",
            "api_or_feature": "mock",
            "model_resolved": model_resolved,
            "messages": [{"role": "user", "content": "hello"}],
            "structured_output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
            "payload_data_class": "internal",
            "provider_compliance_matrix_version": matrix_version,
            "temperature": temperature,
            "safety_settings": safety_settings if safety_settings is not None else {"b": 2, "a": 1},
        }
    )


def _fingerprint(
    request: ProviderRequest,
    *,
    api_version: str = "mock-v1",
    sdk_version: str = "mock-1.0",
) -> str:
    return compute_provider_request_fingerprint(
        request,
        matrix_version=request.provider_compliance_matrix_version,
        api_version=api_version,
        sdk_version=sdk_version,
    )


def test_compute_provider_request_fingerprint_is_deterministic() -> None:
    request = _request()

    first = _fingerprint(request)
    second = _fingerprint(request)

    assert first == second


def test_same_request_returns_same_fingerprint() -> None:
    assert _fingerprint(_request()) == _fingerprint(_request())


def test_model_api_version_and_temperature_change_fingerprint() -> None:
    baseline = _fingerprint(_request())

    assert baseline != _fingerprint(_request(model_resolved="mock-model-v2"))
    assert baseline != _fingerprint(_request(), api_version="mock-v2")
    assert baseline != _fingerprint(_request(temperature=0.7))


def test_provider_request_fingerprint_is_sha256_hex() -> None:
    fingerprint = _fingerprint(_request())

    assert re.fullmatch(r"[a-f0-9]{64}", fingerprint)


def test_safety_settings_hash_absorbs_key_order() -> None:
    left = _request(safety_settings={"a": 1, "b": 2})
    right = _request(safety_settings={"b": 2, "a": 1})

    assert provider_request_fingerprint_payload(
        left,
        matrix_version=left.provider_compliance_matrix_version,
        api_version="mock-v1",
        sdk_version="mock-1.0",
    )["safety_settings_hash"] == provider_request_fingerprint_payload(
        right,
        matrix_version=right.provider_compliance_matrix_version,
        api_version="mock-v1",
        sdk_version="mock-1.0",
    )["safety_settings_hash"]
    assert _fingerprint(left) == _fingerprint(right)


def test_fingerprint_includes_matrix_version() -> None:
    left = _request(matrix_version="pcm-v1")
    right = _request(matrix_version="pcm-v2")

    assert _fingerprint(left) != _fingerprint(right)
    assert (
        provider_request_fingerprint_payload(
            left,
            matrix_version=left.provider_compliance_matrix_version,
            api_version="mock-v1",
            sdk_version="mock-1.0",
        )["provider_compliance_matrix_version"]
        == "pcm-v1"
    )


def test_fingerprint_deterministic_with_matrix_version() -> None:
    request = _request(matrix_version="pcm-v3")

    first = compute_provider_request_fingerprint(
        request,
        matrix_version="pcm-v3",
        api_version="mock-v1",
        sdk_version="mock-1.0",
    )
    second = compute_provider_request_fingerprint(
        request,
        matrix_version="pcm-v3",
        api_version="mock-v1",
        sdk_version="mock-1.0",
    )

    assert first == second

