from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from backend.app.domain.provider.adapter import ProviderAdapter
from backend.app.domain.provider.request import ProviderRequest
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.providers.anthropic_messages import AnthropicMessagesAdapter

RUN_ID = UUID("00000000-0000-4000-8000-000000005503")

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
        "id": "msg-test",
        "model": "claude-opus-4-7",
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu-test",
                "name": "taskmanagedai_structured_output",
                "input": {"answer": "ok"},
            }
        ],
        "usage": {
            "input_tokens": 13,
            "output_tokens": 6,
            "cost_usd": 0.031,
        },
    }
    payload.update(overrides)
    return payload


def _request() -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": "anthropic",
            "api_or_feature": "messages",
            "model_resolved": "claude-opus-4-7",
            "messages": [
                {"role": "system", "content": "You return strict JSON."},
                {"role": "user", "content": "return json"},
            ],
            "structured_output_schema": _SCHEMA,
            "payload_data_class": "internal",
            "provider_compliance_matrix_version": "v2026.05.09-p0-skeleton",
            "max_tokens": 256,
            "temperature": 0,
            "secret_capability_token": "cap-token-anthropic-test",
        }
    )


def _resolver(token: str) -> str:
    assert token == "cap-token-anthropic-test"
    return "broker-resolved-provider-credential"


def test_anthropic_messages_adapter_satisfies_provider_adapter_protocol() -> None:
    adapter = AnthropicMessagesAdapter(_HTTPClient(_Response(200, _success_payload())), _resolver)

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.provider_name() == "anthropic"
    assert adapter.api_or_feature() == "messages"


def test_anthropic_system_message_is_separated_from_messages() -> None:
    client = _HTTPClient(_Response(200, _success_payload()))
    adapter = AnthropicMessagesAdapter(client, _resolver)

    result = adapter.execute(_request())

    assert result.status == "success"
    body = client.calls[0]["json"]
    assert body["system"] == "You return strict JSON."
    assert [message["role"] for message in body["messages"]] == ["user"]


def test_anthropic_tool_use_schema_conversion() -> None:
    client = _HTTPClient(_Response(200, _success_payload()))
    adapter = AnthropicMessagesAdapter(client, _resolver)

    adapter.execute(_request())

    body = client.calls[0]["json"]
    assert body["tools"] == [
        {
            "name": "taskmanagedai_structured_output",
            "description": "Return the task result as JSON matching the provided schema.",
            "input_schema": _SCHEMA,
        }
    ]
    assert body["tool_choice"] == {
        "type": "tool",
        "name": "taskmanagedai_structured_output",
    }


def test_anthropic_usage_and_redacted_summary() -> None:
    payload = _success_payload(api_key="redacted-provider-credential")
    adapter = AnthropicMessagesAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.usage is not None
    assert result.usage.tokens_input == 13
    assert result.usage.tokens_output == 6
    assert result.usage.cost_usd == pytest.approx(0.031)
    assert_no_raw_secret(result.redacted_response_summary, path="$test_anthropic_summary")
    assert "api_key" not in json.dumps(result.redacted_response_summary, sort_keys=True)


def test_anthropic_raw_secret_in_response_summary_maps_to_incomplete() -> None:
    payload = _success_payload(model="sk-ant-rawsecretpattern1234567890")
    adapter = AnthropicMessagesAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "incomplete"
    assert result.error_code == "raw_secret_in_response"
    assert result.redacted_response_summary["redaction"] == "raw_secret_in_response"


def test_anthropic_provider_continuation_ref_forces_exportable_false() -> None:
    adapter = AnthropicMessagesAdapter(
        _HTTPClient(
            _Response(
                200,
                _success_payload(
                    stop_reason="max_tokens",
                    content=[],
                ),
            )
        ),
        _resolver,
    )

    result = adapter.execute(_request())

    assert result.status == "max_token"
    assert result.continuation_ref is not None
    assert result.continuation_ref["exportable"] is False
    assert result.continuation_ref["artifact_ref"].startswith(
        "provider-continuation:anthropic:"
    )


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
def test_anthropic_http_status_mapping_to_result_kind(
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
    adapter = AnthropicMessagesAdapter(
        _HTTPClient(_Response(status_code, payload)),
        _resolver,
    )

    result = adapter.execute(_request())

    assert result.status == expected_status
    assert result.error_code == expected_error_code


def test_anthropic_200_schema_error_signal_maps_to_unsupported_schema() -> None:
    payload = _success_payload(stop_reason="schema_validation_failed", content=[])
    adapter = AnthropicMessagesAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "unsupported_schema"
    assert result.error_code == "anthropic_unsupported_schema"


def test_anthropic_http_schema_error_body_does_not_override_status_mapping() -> None:
    payload = {
        "error": {
            "type": "invalid_request_error",
            "code": "schema_validation_failed",
            "message": "schema validation failed",
        }
    }
    adapter = AnthropicMessagesAdapter(_HTTPClient(_Response(400, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "incomplete"
    assert result.error_code == "http_400_client_error"


def test_anthropic_rejects_provider_mismatch() -> None:
    request = _request().model_copy(update={"provider": "openai"})
    adapter = AnthropicMessagesAdapter(_HTTPClient(_Response(200, _success_payload())), _resolver)

    with pytest.raises(ValueError, match="provider='anthropic'"):
        adapter.execute(request)
