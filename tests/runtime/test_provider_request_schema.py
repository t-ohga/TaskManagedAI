from __future__ import annotations

from uuid import UUID

import pytest
from jsonschema.validators import validator_for
from pydantic import ValidationError

from backend.app.domain.provider.request import ProviderRequest

RUN_ID = UUID("00000000-0000-4000-8000-000000005201")


def _request_payload() -> dict[str, object]:
    return {
        "tenant_id": 1,
        "run_id": RUN_ID,
        "provider": "mock",
        "api_or_feature": "mock",
        "model_resolved": "mock-model",
        "messages": [{"role": "user", "content": "hello"}],
        "structured_output_schema": {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": False,
        },
        "payload_data_class": "internal",
        "provider_compliance_matrix_version": "pcm-v1",
        "max_tokens": 256,
        "temperature": 0.2,
        "safety_settings": {"level": "standard"},
    }


def test_provider_request_requires_payload_data_class() -> None:
    payload = _request_payload()
    payload.pop("payload_data_class")

    with pytest.raises(ValidationError):
        ProviderRequest.model_validate(payload)


def test_provider_request_requires_provider_compliance_matrix_version() -> None:
    payload = _request_payload()
    payload.pop("provider_compliance_matrix_version")

    with pytest.raises(ValidationError):
        ProviderRequest.model_validate(payload)


def test_provider_request_rejects_caller_supplied_allowed_data_class() -> None:
    payload = _request_payload()
    payload["allowed_data_class"] = "internal"

    with pytest.raises(ValidationError):
        ProviderRequest.model_validate(payload)

    assert "allowed_data_class" not in ProviderRequest.model_fields


def test_structured_output_schema_must_be_valid_json_schema() -> None:
    request = ProviderRequest.model_validate(_request_payload())

    validator_for(request.structured_output_schema).check_schema(
        request.structured_output_schema
    )

    payload = _request_payload()
    payload["structured_output_schema"] = {"type": "not-a-json-schema-type"}
    with pytest.raises(ValidationError):
        ProviderRequest.model_validate(payload)


def test_secret_capability_token_is_optional_string() -> None:
    without_token = ProviderRequest.model_validate(_request_payload())
    assert without_token.secret_capability_token is None

    payload = _request_payload()
    payload["secret_capability_token"] = "broker-mediated-test-token"
    with_token = ProviderRequest.model_validate(payload)

    assert with_token.secret_capability_token == "broker-mediated-test-token"


@pytest.mark.parametrize("role", ["system", "user", "assistant", "tool"])
def test_provider_message_accepts_known_roles(role: str) -> None:
    payload = _request_payload()
    payload["messages"] = [{"role": role, "content": "hello"}]

    request = ProviderRequest.model_validate(payload)

    assert request.messages[0].role == role


@pytest.mark.parametrize(
    "block",
    [
        {"type": "text", "text": "hello"},
        {"type": "image_ref", "image_ref": "artifact://image-1"},
        {"type": "tool_result", "tool_call_id": "call-1", "output": "ok"},
        {"type": "tool_use", "tool_call_id": "call-1", "tool_name": "search"},
    ],
)
def test_provider_message_accepts_structured_content_blocks(
    block: dict[str, str],
) -> None:
    payload = _request_payload()
    payload["messages"] = [{"role": "user", "content": [block]}]

    request = ProviderRequest.model_validate(payload)

    content = request.messages[0].content
    assert isinstance(content, list)
    assert content[0].type == block["type"]


@pytest.mark.parametrize(
    "message",
    [
        {"role": "developer", "content": "hello"},
        {"role": "user", "content": {"text": "hello"}},
        {"role": "user", "content": [{"type": "text", "image_ref": "artifact://image-1"}]},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_ref",
                    "image_ref": "artifact://image-1",
                    "text": "hello",
                }
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_call_id": "call-1"}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_use", "tool_call_id": "call-1", "output": "ok"}],
        },
    ],
)
def test_provider_message_rejects_invalid_role_or_content(
    message: dict[str, object],
) -> None:
    payload = _request_payload()
    payload["messages"] = [message]

    with pytest.raises(ValidationError):
        ProviderRequest.model_validate(payload)

