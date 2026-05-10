from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.app.domain.provider.fingerprint import compute_provider_request_fingerprint
from backend.app.domain.provider.request import ProviderMessage, ProviderRequest
from backend.app.domain.provider.result import ProviderResult, ProviderUsage
from backend.app.services.agent_runtime.provider_result_mapping import ProviderResultKind
from backend.app.services.providers._http_helpers import (
    attach_structured_output_metadata,
    build_non_exportable_continuation_ref,
    build_structured_artifact_ref,
    extract_structured_output,
    http_error_code_from_status,
    map_http_status_to_result_kind,
    post_json,
    provider_message_content_to_text,
    provider_usage_from_response,
    raw_secret_response_summary,
    redact_response_summary,
    redacted_error_summary,
    resolve_maybe_awaitable,
)

_GEMINI_GENERATE_CONTENT_URL = (
    "https://generativelanguage.googleapis.com/v1/models/{model}:generateContent"
)
_GEMINI_API_VERSION = "v1"
_GEMINI_SDK_VERSION = "google-genai-0.x"
_HTTP_TIMEOUT_SECONDS = 30.0
_MAX_RESPONSE_SCHEMA_CONTAINER_DEPTH = 5
_MAX_RESPONSE_SCHEMA_PROPERTIES = 100
_GEMINI_SUPPORTED_SCHEMA_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_UNSUPPORTED_GEMINI_SCHEMA_FEATURES = ("anyOf", "oneOf", "$ref")
_UNSUPPORTED_GEMINI_SCHEMA_TYPE_VALUES = frozenset({"any"})

SecretTokenResolver = Callable[[str], str | Awaitable[str]]


class GeminiAdapter:
    def __init__(self, http_client: object, secret_token_resolver: SecretTokenResolver) -> None:
        self._http_client = http_client
        self._secret_token_resolver = secret_token_resolver

    def provider_name(self) -> str:
        return "gemini"

    def api_or_feature(self) -> str:
        return "generate_content"

    def execute(self, request: ProviderRequest) -> ProviderResult:
        _validate_request(request)

        unsupported_reason = _unsupported_schema_reason(request.structured_output_schema)
        if unsupported_reason is not None:
            return _build_result(
                request=request,
                status="unsupported_schema",
                response={
                    "status": "unsupported_schema",
                    "finishReason": "UNSUPPORTED_SCHEMA",
                },
                error_code="gemini_unsupported_schema",
                error_summary=redacted_error_summary(unsupported_reason),
            )

        api_key = _resolve_api_key(request, self._secret_token_resolver)
        body = _build_generate_content_body(request)
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        try:
            status_code, response_payload = post_json(
                self._http_client,
                _GEMINI_GENERATE_CONTENT_URL.format(model=request.model_resolved),
                headers=headers,
                body=body,
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            status: ProviderResultKind = (
                "timeout_retryable" if _is_timeout_exception(exc) else "incomplete"
            )
            return _build_result(
                request=request,
                status=status,
                response={"status": status, "transport_error": type(exc).__name__},
                error_code="gemini_timeout" if status == "timeout_retryable" else "gemini_transport_error",
                error_summary=redacted_error_summary("Gemini transport error"),
            )

        response = dict(response_payload)
        response["_http_status_code"] = status_code

        if not 200 <= status_code < 300:
            status = map_http_status_to_result_kind(status_code)
            return _build_result(
                request=request,
                status=status,
                response=response,
                error_code=http_error_code_from_status(status_code),
                error_summary=redacted_error_summary(
                    "Gemini HTTP error",
                    f"status={status_code}",
                ),
            )

        provider_status = _map_gemini_response_status(response)
        if provider_status != "success":
            return _build_result(
                request=request,
                status=provider_status,
                response=response,
                error_code=f"gemini_{provider_status}",
                error_summary=redacted_error_summary(
                    "Gemini returned non-success finish reason",
                    provider_status,
                ),
                continuation_ref=_continuation_ref(request, response, provider_status),
            )

        structured_output, validation_status = extract_structured_output(
            response,
            request.structured_output_schema,
        )
        if validation_status != "success" or structured_output is None:
            return _build_result(
                request=request,
                status=validation_status,
                response=response,
                error_code=f"gemini_{validation_status}",
                error_summary=redacted_error_summary(
                    "Gemini structured output validation failed",
                    validation_status,
                ),
            )

        return _build_result(
            request=request,
            status="success",
            response=response,
            artifact_ref=build_structured_artifact_ref("gemini", structured_output),
            structured_output=structured_output,
        )


def _validate_request(request: ProviderRequest) -> None:
    if request.provider != "gemini":
        raise ValueError(
            "GeminiAdapter only handles provider='gemini', "
            f"got {request.provider!r}"
        )
    if request.api_or_feature != "generate_content":
        raise ValueError(
            "GeminiAdapter only handles api_or_feature='generate_content', "
            f"got {request.api_or_feature!r}"
        )


def _resolve_api_key(
    request: ProviderRequest,
    resolver: SecretTokenResolver,
) -> str:
    token = request.secret_capability_token
    if token is None:
        raise ValueError("GeminiAdapter requires request.secret_capability_token from SecretBroker.")

    resolved = resolve_maybe_awaitable(resolver(token))
    if not isinstance(resolved, str) or not resolved:
        raise ValueError("secret_token_resolver must return a non-empty provider credential.")
    return resolved


def _build_generate_content_body(request: ProviderRequest) -> dict[str, Any]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []

    for message in request.messages:
        if message.role == "system":
            system_parts.append(provider_message_content_to_text(message.content))
            continue
        contents.append(_message_to_gemini_content(message))

    generation_config: dict[str, Any] = {
        "responseMimeType": "application/json",
        "responseSchema": request.structured_output_schema,
    }
    if request.max_tokens is not None:
        generation_config["maxOutputTokens"] = request.max_tokens
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": generation_config,
    }
    if system_parts:
        body["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}],
        }

    safety_settings = _gemini_safety_settings(request.safety_settings)
    if safety_settings is not None:
        body["safetySettings"] = safety_settings

    return body


def _message_to_gemini_content(message: ProviderMessage) -> dict[str, Any]:
    role = "model" if message.role == "assistant" else "user"
    return {
        "role": role,
        "parts": [{"text": provider_message_content_to_text(message.content)}],
    }


def _gemini_safety_settings(value: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if value is None:
        return None

    direct = value.get("safetySettings")
    if isinstance(direct, list) and all(isinstance(item, dict) for item in direct):
        return direct

    snake = value.get("safety_settings")
    if isinstance(snake, list) and all(isinstance(item, dict) for item in snake):
        return snake

    return None


def _unsupported_schema_reason(schema: dict[str, Any] | None) -> str | None:
    """Return Gemini structured-output preflight failure reason, if any."""

    if not schema:
        return None

    unsupported = _schema_find_unsupported_types(schema)
    if unsupported is not None:
        return f"Gemini does not support schema type/feature: {unsupported}"

    if _schema_has_array_of_array_of_object(schema):
        return "Gemini does not support array-of-array-of-object schema shape."

    if _schema_has_excessive_properties(
        schema,
        max_props=_MAX_RESPONSE_SCHEMA_PROPERTIES,
    ):
        return (
            "Gemini response_schema has too many properties "
            f"(limit: {_MAX_RESPONSE_SCHEMA_PROPERTIES})."
        )

    depth = _schema_container_depth(schema)
    if depth > _MAX_RESPONSE_SCHEMA_CONTAINER_DEPTH:
        return (
            "Gemini response_schema container depth exceeds supported limit "
            f"{_MAX_RESPONSE_SCHEMA_CONTAINER_DEPTH}."
        )

    return None


def _schema_container_depth(schema: object, depth: int = 0) -> int:
    """Return JSON Schema container nesting depth without crashing on list types.

    R3-F-001 (R4): JSON Schema type may be an array, for example
    ["string", "null"]. Treat non-string type values as non-containers here;
    unsupported-type detection runs before the depth check and reports them.
    """

    if not isinstance(schema, Mapping):
        return depth

    schema_type = schema.get("type")
    if schema_type is not None and not isinstance(schema_type, str):
        return depth

    is_container = (
        (isinstance(schema_type, str) and schema_type in {"object", "array"})
        or "properties" in schema
        or "items" in schema
    )
    if not is_container:
        return depth

    next_depth = depth + 1
    max_depth = next_depth

    for _, child in _iter_schema_children(schema, "$"):
        max_depth = max(max_depth, _schema_container_depth(child, next_depth))

    return max_depth


def _schema_find_unsupported_types(schema: object, path: str = "$") -> str | None:
    if not isinstance(schema, Mapping):
        return None

    for feature in _UNSUPPORTED_GEMINI_SCHEMA_FEATURES:
        if feature in schema:
            return f"{feature} at {path}.{feature}"

    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        normalized_type = schema_type.lower()
        if (
            normalized_type in _UNSUPPORTED_GEMINI_SCHEMA_TYPE_VALUES
            or normalized_type not in _GEMINI_SUPPORTED_SCHEMA_TYPES
        ):
            return f"type={schema_type!r} at {path}.type"
    elif isinstance(schema_type, list):
        return f"type array at {path}.type"
    elif schema_type is not None:
        return f"non-string type at {path}.type"

    for child_path, child in _iter_schema_children(schema, path):
        unsupported = _schema_find_unsupported_types(child, child_path)
        if unsupported is not None:
            return unsupported

    return None


def _schema_has_array_of_array_of_object(schema: object) -> bool:
    if not isinstance(schema, Mapping):
        return False

    schema_type = schema.get("type")
    if schema_type is not None and not isinstance(schema_type, str):
        return False

    if _is_array_schema(schema):
        items = schema.get("items")
        if isinstance(items, Mapping) and _is_array_schema(items):
            nested_items = items.get("items")
            if isinstance(nested_items, Mapping) and _is_object_schema(nested_items):
                return True

    for _, child in _iter_schema_children(schema, "$"):
        if _schema_has_array_of_array_of_object(child):
            return True

    return False


def _schema_has_excessive_properties(schema: object, *, max_props: int) -> bool:
    if not isinstance(schema, Mapping):
        return False

    schema_type = schema.get("type")
    if schema_type is not None and not isinstance(schema_type, str):
        return False

    properties = schema.get("properties")
    if isinstance(properties, Mapping) and len(properties) > max_props:
        return True

    for _, child in _iter_schema_children(schema, "$"):
        if _schema_has_excessive_properties(child, max_props=max_props):
            return True

    return False


def _iter_schema_children(schema: Mapping[object, object], path: str) -> list[tuple[str, object]]:
    children: list[tuple[str, object]] = []

    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for name, child in properties.items():
            children.append((f"{path}.properties.{name}", child))

    items = schema.get("items")
    if isinstance(items, Mapping):
        children.append((f"{path}.items", items))

    additional_properties = schema.get("additionalProperties")
    if isinstance(additional_properties, Mapping):
        children.append((f"{path}.additionalProperties", additional_properties))

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for index, child in enumerate(all_of):
            children.append((f"{path}.allOf[{index}]", child))

    for defs_key in ("$defs", "definitions"):
        defs = schema.get(defs_key)
        if isinstance(defs, Mapping):
            for name, child in defs.items():
                children.append((f"{path}.{defs_key}.{name}", child))

    return children


def _is_array_schema(schema: Mapping[object, object]) -> bool:
    schema_type = schema.get("type")
    return isinstance(schema_type, str) and schema_type == "array"


def _is_object_schema(schema: Mapping[object, object]) -> bool:
    schema_type = schema.get("type")
    if schema_type is not None and not isinstance(schema_type, str):
        return False
    return schema_type == "object" or "properties" in schema


def _map_gemini_response_status(response: Mapping[str, Any]) -> ProviderResultKind:
    if _has_schema_error_signal(response):
        return "unsupported_schema"

    finish_reason = _finish_reason(response)
    if finish_reason in {None, "", "STOP"}:
        return "success"
    if finish_reason == "MAX_TOKENS":
        return "max_token"
    if finish_reason == "SAFETY":
        return "safety_refusal"
    if finish_reason == "RECITATION":
        return "refusal"
    return "incomplete"


def _finish_reason(response: Mapping[str, Any]) -> str | None:
    candidates = response.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                finish_reason = candidate.get("finishReason")
                if isinstance(finish_reason, str):
                    return finish_reason.upper()

    direct = response.get("finishReason")
    if isinstance(direct, str):
        return direct.upper()

    return None


def _has_schema_error_signal(response: Mapping[str, Any]) -> bool:
    error = response.get("error")
    fields: list[str] = []
    if isinstance(error, Mapping):
        fields.extend(str(error.get(key) or "") for key in ("status", "code", "message"))
    fields.append(str(response.get("finishReason") or ""))

    joined = " ".join(fields).lower()
    return "schema" in joined or "unsupported" in joined


def _continuation_ref(
    request: ProviderRequest,
    response: Mapping[str, Any],
    status: ProviderResultKind,
) -> dict[str, Any] | None:
    if status not in {"max_token", "incomplete", "timeout_retryable"}:
        return None

    state = {
        "finish_reason": _finish_reason(response) or status,
        "candidates_present": isinstance(response.get("candidates"), list),
    }
    return build_non_exportable_continuation_ref(
        provider=request.provider,
        api_or_feature=request.api_or_feature,
        state=state,
    )


def _build_result(
    *,
    request: ProviderRequest,
    status: ProviderResultKind,
    response: dict[str, Any],
    artifact_ref: str | None = None,
    structured_output: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_summary: str | None = None,
    continuation_ref: dict[str, Any] | None = None,
) -> ProviderResult:
    result_status = status
    result_artifact_ref = artifact_ref
    result_error_code = error_code
    result_error_summary = error_summary
    result_continuation_ref = continuation_ref

    try:
        summary = redact_response_summary(response, request)
        if structured_output is not None:
            summary = attach_structured_output_metadata(summary, structured_output)
    except ValueError as exc:
        summary = raw_secret_response_summary(request)
        result_status = "incomplete"
        result_artifact_ref = None
        result_error_code = "raw_secret_in_response"
        result_error_summary = redacted_error_summary(
            "response contained raw secret pattern",
            exc,
        )
        result_continuation_ref = None

    return ProviderResult(
        status=result_status,
        artifact_ref=result_artifact_ref,
        usage=_usage(response),
        model_resolved=request.model_resolved,
        api_version=_GEMINI_API_VERSION,
        sdk_version=_GEMINI_SDK_VERSION,
        provider_request_fingerprint=compute_provider_request_fingerprint(
            request,
            matrix_version=request.provider_compliance_matrix_version,
            api_version=_GEMINI_API_VERSION,
            sdk_version=_GEMINI_SDK_VERSION,
        ),
        error_code=result_error_code,
        error_summary=result_error_summary,
        redacted_response_summary=summary,
        continuation_ref=result_continuation_ref,
    )


def _usage(response: dict[str, Any]) -> ProviderUsage:
    return provider_usage_from_response(
        response,
        input_token_keys=("promptTokenCount", "input_tokens"),
        output_token_keys=("candidatesTokenCount", "output_tokens"),
    )


def _is_timeout_exception(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


__all__ = ["GeminiAdapter"]

