from __future__ import annotations

from typing import Any

from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for

from backend.app.domain.agent_runtime.operation_context import canonical_json_dumps
from backend.app.domain.provider.fingerprint import compute_provider_request_fingerprint
from backend.app.domain.provider.request import (
    ProviderMessage,
    ProviderMessageContentBlock,
    ProviderRequest,
)
from backend.app.domain.provider.result import ProviderResult, ProviderUsage
from backend.app.services.agent_runtime.provider_result_mapping import ProviderResultKind

_MOCK_API_VERSION = "mock-v1"
_MOCK_SDK_VERSION = "mock-1.0"
_MOCK_ALLOWED_MODELS: frozenset[str] = frozenset(
    {
        "mock-model",
        "mock-model-v1",
        "mock-success",
        "mock-fast",
    }
)

_FORCED_MARKERS: tuple[tuple[str, ProviderResultKind], ...] = (
    ("__mock_force_refusal__", "refusal"),
    ("__mock_force_safety_refusal__", "safety_refusal"),
    ("__mock_force_max_token__", "max_token"),
    ("__mock_force_incomplete__", "incomplete"),
    ("__mock_force_timeout_retryable__", "timeout_retryable"),
    ("__mock_force_unsupported_schema__", "unsupported_schema"),
    ("__mock_force_schema_mismatch__", "schema_mismatch"),
    ("__mock_force_budget_exceeded__", "budget_exceeded"),
)


class MockProviderAdapter:
    def provider_name(self) -> str:
        return "mock"

    def api_or_feature(self) -> str:
        return "mock"

    def execute(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "mock":
            raise ValueError(
                f"MockProviderAdapter only handles provider='mock', got {request.provider!r}"
            )
        if request.model_resolved not in _MOCK_ALLOWED_MODELS:
            raise ValueError(
                f"MockProviderAdapter rejects non-mock model: {request.model_resolved!r}; "
                f"allowed: {sorted(_MOCK_ALLOWED_MODELS)}"
            )
        if request.api_or_feature != "mock":
            raise ValueError("MockProviderAdapter only handles api_or_feature='mock'")

        forced_status = _forced_status(request)
        schema_error = _schema_validation_error(request.structured_output_schema)
        if schema_error is not None:
            return self._result(
                request=request,
                status="unsupported_schema",
                response_summary={"reason_code": "unsupported_schema"},
                error_code="mock_unsupported_schema",
                error_summary=schema_error,
            )

        if forced_status == "unsupported_schema":
            return self._result(
                request=request,
                status="unsupported_schema",
                response_summary={"reason_code": "unsupported_schema"},
                error_code="mock_unsupported_schema",
                error_summary="Mock forced unsupported schema.",
            )

        if forced_status == "schema_mismatch":
            return self._result(
                request=request,
                status="schema_mismatch",
                response_summary={"mock_status": "schema_mismatch"},
                error_code="mock_schema_mismatch",
                error_summary="Mock forced schema mismatch.",
            )

        if forced_status != "success":
            return self._result(
                request=request,
                status=forced_status,
                response_summary={"mock_status": forced_status},
                error_code=f"mock_{forced_status}",
                error_summary=f"Mock forced {forced_status}.",
            )

        response_summary = _synthesize_schema_value(request.structured_output_schema)
        validation_error = _response_validation_error(
            request.structured_output_schema,
            response_summary,
        )
        if validation_error is not None:
            return self._result(
                request=request,
                status="schema_mismatch",
                response_summary={"reason_code": "schema_mismatch"},
                error_code="mock_schema_mismatch",
                error_summary=validation_error,
            )

        return self._result(
            request=request,
            status="success",
            response_summary=response_summary,
            artifact_ref="mock-artifact",
        )

    def _result(
        self,
        *,
        request: ProviderRequest,
        status: ProviderResultKind,
        response_summary: dict[str, Any],
        artifact_ref: str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> ProviderResult:
        return ProviderResult(
            status=status,
            artifact_ref=artifact_ref,
            usage=_usage_for(request.messages, response_summary),
            model_resolved=request.model_resolved,
            api_version=_MOCK_API_VERSION,
            sdk_version=_MOCK_SDK_VERSION,
            provider_request_fingerprint=compute_provider_request_fingerprint(
                request,
                matrix_version=request.provider_compliance_matrix_version,
                api_version=_MOCK_API_VERSION,
                sdk_version=_MOCK_SDK_VERSION,
            ),
            error_code=error_code,
            error_summary=error_summary,
            redacted_response_summary=response_summary,
            continuation_ref=None,
        )


def _forced_status(request: ProviderRequest) -> ProviderResultKind:
    text = "\n".join(_content_to_text(message.content) for message in request.messages)
    for marker, status in _FORCED_MARKERS:
        if marker in text:
            return status
    return "success"


def _schema_validation_error(schema: dict[str, Any]) -> str | None:
    try:
        validator_for(schema).check_schema(schema)
    except SchemaError as exc:
        return f"Invalid structured output schema: {exc.message}"
    return None


def _response_validation_error(schema: dict[str, Any], value: dict[str, Any]) -> str | None:
    try:
        validator_cls = validator_for(schema)
        validator_cls.check_schema(schema)
        validator_cls(schema).validate(value)
    except (SchemaError, JsonSchemaValidationError) as exc:
        return f"Mock structured output did not satisfy schema: {exc.message}"
    return None


def _synthesize_schema_value(schema: dict[str, Any]) -> dict[str, Any]:
    value = _synthesize_value(schema)
    if isinstance(value, dict):
        return value
    return {"value": value}


def _synthesize_value(schema: dict[str, Any]) -> object:
    if "const" in schema:
        return schema["const"]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]

    schema_type = _schema_type(schema)

    if schema_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required")
        required_keys = set(required) if isinstance(required, list) else set()
        keys = sorted(set(properties) | {key for key in required_keys if isinstance(key, str)})
        return {
            key: _synthesize_value(properties.get(key, {}))
            for key in keys
        }

    if schema_type == "array":
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            item_schema = {}
        min_items = schema.get("minItems", 1)
        count = min_items if isinstance(min_items, int) and min_items > 0 else 1
        return [_synthesize_value(item_schema) for _ in range(count)]

    if schema_type == "integer":
        minimum = schema.get("minimum", 0)
        return int(minimum) if isinstance(minimum, int | float) else 0

    if schema_type == "number":
        minimum = schema.get("minimum", 0)
        return float(minimum) if isinstance(minimum, int | float) else 0.0

    if schema_type == "boolean":
        return True

    if schema_type == "null":
        return None

    min_length = schema.get("minLength", 0)
    value = "mock-value"
    if isinstance(min_length, int) and min_length > len(value):
        value = value + ("x" * (min_length - len(value)))
    return value


def _schema_type(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type
    if isinstance(schema_type, list):
        for item in schema_type:
            if isinstance(item, str) and item != "null":
                return item
        if schema_type and isinstance(schema_type[0], str):
            return schema_type[0]

    if "properties" in schema or "required" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return "object"


def _usage_for(messages: list[ProviderMessage], response_summary: dict[str, Any]) -> ProviderUsage:
    tokens_input = sum(len(_content_to_text(message.content)) for message in messages)
    tokens_output = len(_content_to_text(response_summary))
    total_tokens = tokens_input + tokens_output
    return ProviderUsage(
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        cost_usd=round(total_tokens * 0.0001, 6),
    )


def _content_to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, ProviderMessageContentBlock):
        return canonical_json_dumps(value.model_dump(mode="json"))
    if isinstance(value, list):
        return canonical_json_dumps(
            [
                item.model_dump(mode="json")
                if isinstance(item, ProviderMessageContentBlock)
                else item
                for item in value
            ]
        )
    return canonical_json_dumps(value)


__all__ = ["MockProviderAdapter"]

