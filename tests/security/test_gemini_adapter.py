from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from backend.app.domain.provider.adapter import ProviderAdapter
from backend.app.domain.provider.request import ProviderRequest
from backend.app.services.providers.gemini import GeminiAdapter, _unsupported_schema_reason

RUN_ID = UUID("00000000-0000-4000-8000-000000005603")

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


def _payload(finish_reason: str = "STOP") -> dict[str, Any]:
    content = {"parts": [{"text": json.dumps({"answer": "ok"})}]}
    return {
        "modelVersion": "gemini-2.5",
        "candidates": [
            {
                "finishReason": finish_reason,
                "content": content,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 11,
            "candidatesTokenCount": 4,
            "cost_usd": 0.014,
        },
    }


def _request(
    *,
    structured_output_schema: dict[str, Any] | None = None,
) -> ProviderRequest:
    return ProviderRequest.model_validate(
        {
            "tenant_id": 1,
            "run_id": RUN_ID,
            "provider": "gemini",
            "api_or_feature": "generate_content",
            "model_resolved": "gemini-2.5",
            "messages": [{"role": "user", "content": "return json"}],
            "structured_output_schema": structured_output_schema or _SCHEMA,
            "payload_data_class": "public",
            "provider_compliance_matrix_version": "v2026.05.09-p0-skeleton",
            "max_tokens": 256,
            "temperature": 0,
            "secret_capability_token": "cap-token-gemini-test",
        }
    )


def _resolver(token: str) -> str:
    assert token == "cap-token-gemini-test"
    return "broker-resolved-provider-credential"


def test_gemini_adapter_satisfies_provider_adapter_protocol() -> None:
    adapter = GeminiAdapter(_HTTPClient(_Response(200, _payload())), _resolver)

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.provider_name() == "gemini"
    assert adapter.api_or_feature() == "generate_content"


def test_gemini_response_schema_conversion() -> None:
    client = _HTTPClient(_Response(200, _payload()))
    adapter = GeminiAdapter(client, _resolver)

    result = adapter.execute(_request())

    assert result.status == "success"
    body = client.calls[0]["json"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"] == _SCHEMA


def test_gemini_usage_is_deterministic() -> None:
    adapter = GeminiAdapter(_HTTPClient(_Response(200, _payload())), _resolver)

    result = adapter.execute(_request())

    assert result.usage is not None
    assert result.usage.tokens_input == 11
    assert result.usage.tokens_output == 4
    assert result.usage.cost_usd == pytest.approx(0.014)


def test_gemini_extracts_structured_output_from_candidates_content_parts() -> None:
    payload = _payload()
    payload["candidates"][0]["content"] = {
        "parts": [{"text": json.dumps({"answer": "test"})}]
    }
    adapter = GeminiAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "success"
    assert result.artifact_ref is not None
    assert result.redacted_response_summary["structured_output_top_level_keys"] == ["answer"]


def test_gemini_unsupported_type_list_does_not_crash() -> None:
    reason = _unsupported_schema_reason({"type": ["string", "null"]})

    assert reason is not None
    assert "type array" in reason


def test_gemini_unsupported_schema_precheck_rejects_nested_depth_over_five() -> None:
    too_deep_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "a": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "b": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "c": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"answer": {"type": "string"}},
                                        },
                                    }
                                },
                            },
                        }
                    },
                },
            }
        },
    }
    client = _HTTPClient(_Response(200, _payload()))
    resolved_tokens: list[str] = []

    def resolver(token: str) -> str:
        resolved_tokens.append(token)
        return "broker-resolved-provider-credential"

    adapter = GeminiAdapter(client, resolver)

    result = adapter.execute(_request(structured_output_schema=too_deep_schema))

    assert result.status == "unsupported_schema"
    assert client.calls == []
    assert resolved_tokens == []


@pytest.mark.parametrize(
    "unsupported_schema",
    [
        {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
                {
                    "type": "object",
                    "properties": {"answer": {"type": "number"}},
                    "required": ["answer"],
                },
            ]
        },
        {
            "type": "object",
            "properties": {
                "answer": {
                    "type": ["string", "null"],
                }
            },
        },
        {
            "type": "object",
            "properties": {
                "matrix": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                        },
                    },
                }
            },
        },
        {
            "type": "object",
            "properties": {
                f"field_{index}": {"type": "string"}
                for index in range(101)
            },
        },
    ],
)
def test_gemini_unsupported_schema_precheck_rejects_unsupported_types_and_shapes(
    unsupported_schema: dict[str, Any],
) -> None:
    client = _HTTPClient(_Response(200, _payload()))
    adapter = GeminiAdapter(client, _resolver)

    result = adapter.execute(_request(structured_output_schema=unsupported_schema))

    assert result.status == "unsupported_schema"
    assert result.error_code == "gemini_unsupported_schema"
    assert client.calls == []


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
def test_gemini_http_status_mapping_to_result_kind(
    status_code: int,
    expected_status: str,
    expected_error_code: str | None,
) -> None:
    payload = (
        _payload()
        if status_code == 200
        else {
            "error": {
                "status": "RESOURCE_EXHAUSTED" if status_code == 429 else "PROVIDER_ERROR",
                "code": status_code,
            }
        }
    )
    adapter = GeminiAdapter(
        _HTTPClient(_Response(status_code, payload)),
        _resolver,
    )

    result = adapter.execute(_request())

    assert result.status == expected_status
    assert result.error_code == expected_error_code


@pytest.mark.parametrize(
    ("finish_reason", "expected_status"),
    [
        ("STOP", "success"),
        ("MAX_TOKENS", "max_token"),
        ("SAFETY", "safety_refusal"),
        ("RECITATION", "refusal"),
        ("OTHER", "incomplete"),
    ],
)
def test_gemini_finish_reason_mapping(finish_reason: str, expected_status: str) -> None:
    adapter = GeminiAdapter(_HTTPClient(_Response(200, _payload(finish_reason))), _resolver)

    result = adapter.execute(_request())

    assert result.status == expected_status


def test_gemini_200_schema_error_signal_maps_to_unsupported_schema() -> None:
    payload = {
        "finishReason": "SCHEMA_VALIDATION_FAILED",
        "error": {
            "status": "INVALID_ARGUMENT",
            "code": 400,
            "message": "schema validation failed",
        },
    }
    adapter = GeminiAdapter(_HTTPClient(_Response(200, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "unsupported_schema"
    assert result.error_code == "gemini_unsupported_schema"


def test_gemini_http_schema_error_body_does_not_override_status_mapping() -> None:
    payload = {
        "error": {
            "status": "INVALID_ARGUMENT",
            "code": 400,
            "message": "schema validation failed",
        }
    }
    adapter = GeminiAdapter(_HTTPClient(_Response(400, payload)), _resolver)

    result = adapter.execute(_request())

    assert result.status == "incomplete"
    assert result.error_code == "http_400_client_error"


def test_gemini_rejects_provider_mismatch() -> None:
    request = _request().model_copy(update={"provider": "openai"})
    adapter = GeminiAdapter(_HTTPClient(_Response(200, _payload())), _resolver)

    with pytest.raises(ValueError, match="provider='gemini'"):
        adapter.execute(request)

