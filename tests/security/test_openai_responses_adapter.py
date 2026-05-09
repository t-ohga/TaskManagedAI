from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from backend.app.domain.provider.adapter import ProviderAdapter
from backend.app.domain.provider.request import ProviderRequest
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.providers.openai_responses import OpenAIResponsesAdapter

RUN_ID = UUID("00000000-0000-4000-8000-000000005403")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer"],
    "properties": {"answer": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _HTTPClient:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any],
        timeout: float,
    ) -> _Response:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "json": dict(json),
                "timeout": timeout,
            }
        )
        return self.response


def _success_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "resp-test",
        "status": "completed",
        "model": "gpt-5.5",
        "output_text": json.dumps({"answer": "ok"}),
        "usage": {
            "input_tokens": 17,
            "output_tokens": 5,
            "cost_usd": 0.042,
        },
    }
    payload.update(overrides)
    return payload


def _request(
    *,
    provider: str = "openai",
    api_or_feature: str = "responses",
) -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": provider,
            "api_or_feature": api_or_feature,
            "model_resolved": "gpt-5.5",
            "messages": [{"role": "user", "content": "return json"}],
            "structured_output_schema": _SCHEMA,
            "payload_data_class": "internal",
            "provider_compliance_matrix_version": "v2026.05.09-p0-skeleton",
            "max_tokens": 256,
            "temperature": 0,
            "safety_settings": {"mode": "structured"},
            "secret_capability_token": "cap-token-openai-test",
        }
    )


def _resolver(token: str) -> str:
    assert token == "cap-token-openai-test"
    return "broker-resolved-provider-credential"


def test_openai_responses_adapter_satisfies_provider_adapter_protocol() -> None:
    adapter = OpenAIResponsesAdapter(_HTTPClient(_Response(200, _success_payload())), _resolver)

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.provider_name() == "openai"
    assert adapter.api_or_feature() == "responses"


def test_openai_structured_output_schema_is_converted_to_response_format() -> None:
    client = _HTTPClient(_Response(200, _success_payload()))
    adapter = OpenAIResponsesAdapter(client, _resolver)

    result = adapter.execute(_request())

    assert result.status == "success"
    body = client.calls[0]["json"]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "taskmanagedai_structured_output",
            "schema": _SCHEMA,
            "strict": True,
        },
    }


def test_openai_usage_is_deterministic_from_mock_http_response() -> None:
    adapter = OpenAIResponsesAdapter(
        _HTTPClient(_Response(200, _success_payload())),
        _resolver,
    )

    result = adapter.execute(_request())

    assert result.usage is not None
    assert result.usage.tokens_input == 17
    assert result.usage.tokens_output == 5
    assert result.usage.cost_usd == pytest.approx(0.042)


def test_openai_secret_capability_token_resolves_api_key_for_header_only() -> None:
    resolved_tokens: list[str] = []

    def resolver(token: str) -> str:
        resolved_tokens.append(token)
        return "broker-resolved-provider-credential"

    client = _HTTPClient(_Response(200, _success_payload()))
    adapter = OpenAIResponsesAdapter(client, resolver)

    adapter.execute(_request())

    assert resolved_tokens == ["cap-token-openai-test"]
    assert client.calls[0]["headers"]["Authorization"] == (
        "Bearer broker-resolved-provider-credential"
    )


def test_openai_raw_response_is_reduced_to_redacted_summary() -> None:
    payload = _success_payload(api_key="redacted-provider-credential")
    adapter = OpenAIResponsesAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert_no_raw_secret(result.redacted_response_summary, path="$test_openai_summary")
    serialized = json.dumps(result.redacted_response_summary, sort_keys=True)
    assert "api_key" not in serialized
    assert "redacted-provider-credential" not in serialized


def test_openai_raw_secret_in_response_summary_maps_to_incomplete() -> None:
    payload = _success_payload(model="sk-rawsecretpattern1234567890")
    adapter = OpenAIResponsesAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "incomplete"
    assert result.error_code == "raw_secret_in_response"
    assert result.redacted_response_summary["redaction"] == "raw_secret_in_response"


@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_error_code"),
    [
        (200, "success", None),
        (400, "incomplete", "http_400_client_error"),
        (401, "incomplete", "http_401_unauthorized"),
        (403, "incomplete", "http_403_forbidden"),
        (429, "timeout_retryable", "http_429_rate_limit"),
        (500, "incomplete", "http_500_server_error"),
        (503, "incomplete", "http_503_server_error"),
    ],
)
def test_openai_http_status_mapping_to_result_kind(
    status_code: int,
    expected_status: str,
    expected_error_code: str | None,
) -> None:
    payload = (
        _success_payload()
        if status_code == 200
        else {
            "error": {
                "type": "rate_limit" if status_code == 429 else "provider_error",
                "code": "provider_error",
            }
        }
    )
    adapter = OpenAIResponsesAdapter(
        _HTTPClient(_Response(status_code, payload)),
        _resolver,
    )

    result = adapter.execute(_request())

    assert result.status == expected_status
    assert result.error_code == expected_error_code


def test_openai_200_schema_error_signal_maps_to_unsupported_schema() -> None:
    payload = _success_payload(
        status="failed",
        error={
            "type": "invalid_request_error",
            "code": "schema_validation_failed",
            "message": "schema validation failed",
        },
    )
    adapter = OpenAIResponsesAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "unsupported_schema"
    assert result.error_code == "openai_unsupported_schema"


def test_openai_http_schema_error_body_does_not_override_status_mapping() -> None:
    payload = {
        "error": {
            "type": "invalid_request_error",
            "code": "schema_validation_failed",
            "message": "schema validation failed",
        }
    }
    adapter = OpenAIResponsesAdapter(_HTTPClient(_Response(400, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "incomplete"
    assert result.error_code == "http_400_client_error"


@pytest.mark.parametrize("provider", ["anthropic", "gemini"])
def test_openai_rejects_provider_mismatch(provider: str) -> None:
    adapter = OpenAIResponsesAdapter(_HTTPClient(_Response(200, _success_payload())), _resolver)

    with pytest.raises(ValueError, match="provider='openai'"):
        adapter.execute(_request(provider=provider))

