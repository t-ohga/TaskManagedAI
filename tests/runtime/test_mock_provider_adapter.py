from __future__ import annotations

from uuid import UUID

import pytest
from jsonschema.validators import validator_for

from backend.app.domain.agent_runtime.operation_context import canonical_json_dumps
from backend.app.domain.provider.request import ProviderRequest
from backend.app.services.providers.mock import MockProviderAdapter

RUN_ID = UUID("00000000-0000-4000-8000-000000005301")

_SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}


def _request(
    message: str = "hello",
    *,
    provider: str = "mock",
    api_or_feature: str = "mock",
    model_resolved: str = "mock-model",
) -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": provider,
            "api_or_feature": api_or_feature,
            "model_resolved": model_resolved,
            "messages": [{"role": "user", "content": message}],
            "structured_output_schema": _SCHEMA,
            "payload_data_class": "internal",
            "provider_compliance_matrix_version": "pcm-v1",
            "max_tokens": 256,
            "temperature": 0,
            "safety_settings": {"mode": "deterministic"},
        }
    )


@pytest.mark.parametrize(
    ("marker", "status"),
    [
        ("", "success"),
        ("__mock_force_refusal__", "refusal"),
        ("__mock_force_incomplete__", "incomplete"),
        ("__mock_force_unsupported_schema__", "unsupported_schema"),
        ("__mock_force_max_token__", "max_token"),
        ("__mock_force_budget_exceeded__", "budget_exceeded"),
    ],
)
def test_mock_provider_deterministic_cases(marker: str, status: str) -> None:
    result = MockProviderAdapter().execute(_request(marker or "hello"))

    assert result.status == status


@pytest.mark.parametrize(
    ("marker", "expected_status"),
    [
        ("__mock_force_safety_refusal__", "safety_refusal"),
        ("__mock_force_timeout_retryable__", "timeout_retryable"),
        ("__mock_force_schema_mismatch__", "schema_mismatch"),
    ],
)
def test_mock_provider_handles_extended_markers(
    marker: str,
    expected_status: str,
) -> None:
    request = _request(marker)
    result = MockProviderAdapter().execute(request)
    result2 = MockProviderAdapter().execute(request)

    assert result.status == expected_status
    assert result.provider_request_fingerprint == result2.provider_request_fingerprint


def test_mock_provider_same_request_same_result() -> None:
    adapter = MockProviderAdapter()
    request = _request("same input")

    first = adapter.execute(request)
    second = adapter.execute(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_mock_provider_usage_is_based_on_message_and_response_characters() -> None:
    result = MockProviderAdapter().execute(_request("hello"))

    assert result.usage is not None
    assert result.usage.tokens_input == len("hello")
    assert result.usage.tokens_output == len(
        canonical_json_dumps(result.redacted_response_summary)
    )
    assert result.usage.cost_usd == pytest.approx(
        (result.usage.tokens_input + result.usage.tokens_output) * 0.0001
    )


def test_mock_provider_success_structured_output_satisfies_schema() -> None:
    result = MockProviderAdapter().execute(_request("hello"))

    validator_cls = validator_for(_SCHEMA)
    validator_cls.check_schema(_SCHEMA)
    validator_cls(_SCHEMA).validate(result.redacted_response_summary)

    assert result.status == "success"
    assert result.artifact_ref == "mock-artifact"


def test_mock_rejects_non_mock_provider() -> None:
    with pytest.raises(ValueError, match="provider='mock'"):
        MockProviderAdapter().execute(_request(provider="openai"))


def test_mock_rejects_unknown_model() -> None:
    with pytest.raises(ValueError, match="non-mock model"):
        MockProviderAdapter().execute(_request(model_resolved="gpt-5.5"))


def test_mock_rejects_non_mock_api_or_feature() -> None:
    with pytest.raises(ValueError, match="api_or_feature='mock'"):
        MockProviderAdapter().execute(_request(api_or_feature="responses"))


@pytest.mark.parametrize(
    "model_resolved",
    ["mock-model", "mock-model-v1", "mock-success", "mock-fast"],
)
def test_mock_accepts_known_mock_models(model_resolved: str) -> None:
    result = MockProviderAdapter().execute(_request(model_resolved=model_resolved))

    assert result.status == "success"
    assert result.model_resolved == model_resolved

