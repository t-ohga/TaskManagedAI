from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.app.domain.agent_runtime.operation_context import compute_payload_hash
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

_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
_OPENAI_API_VERSION = "2026-01-01"
_OPENAI_SDK_VERSION = "openai-python-2.0.0"
_HTTP_TIMEOUT_SECONDS = 30.0

SecretTokenResolver = Callable[[str], str | Awaitable[str]]


class OpenAIResponsesAdapter:
    def __init__(self, http_client: object, secret_token_resolver: SecretTokenResolver) -> None:
        self._http_client = http_client
        self._secret_token_resolver = secret_token_resolver

    def provider_name(self) -> str:
        return "openai"

    def api_or_feature(self) -> str:
        return "responses"

    def execute(self, request: ProviderRequest) -> ProviderResult:
        _validate_request(request)
        api_key = _resolve_api_key(request, self._secret_token_resolver)
        body = _build_responses_body(request)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            status_code, response_payload = post_json(
                self._http_client,
                _OPENAI_RESPONSES_URL,
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
                error_code="openai_timeout" if status == "timeout_retryable" else "openai_transport_error",
                error_summary=redacted_error_summary("OpenAI Responses transport error"),
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
                    "OpenAI Responses HTTP error",
                    f"status={status_code}",
                ),
            )

        provider_status = _map_openai_response_status(response)
        if provider_status != "success":
            return _build_result(
                request=request,
                status=provider_status,
                response=response,
                error_code=f"openai_{provider_status}",
                error_summary=redacted_error_summary(
                    "OpenAI Responses returned non-success status",
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
                error_code=f"openai_{validation_status}",
                error_summary=redacted_error_summary(
                    "OpenAI Responses structured output validation failed",
                    validation_status,
                ),
            )

        return _build_result(
            request=request,
            status="success",
            response=response,
            artifact_ref=build_structured_artifact_ref("openai", structured_output),
            structured_output=structured_output,
        )


def _validate_request(request: ProviderRequest) -> None:
    if request.provider != "openai":
        raise ValueError(
            "OpenAIResponsesAdapter only handles provider='openai', "
            f"got {request.provider!r}"
        )
    if request.api_or_feature != "responses":
        raise ValueError(
            "OpenAIResponsesAdapter only handles api_or_feature='responses', "
            f"got {request.api_or_feature!r}"
        )


def _resolve_api_key(
    request: ProviderRequest,
    resolver: SecretTokenResolver,
) -> str:
    token = request.secret_capability_token
    if token is None:
        raise ValueError(
            "OpenAIResponsesAdapter requires request.secret_capability_token from "
            "SecretBroker."
        )

    resolved = resolve_maybe_awaitable(resolver(token))
    if not isinstance(resolved, str) or not resolved:
        raise ValueError("secret_token_resolver must return a non-empty provider credential.")
    return resolved


def _build_responses_body(request: ProviderRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": request.model_resolved,
        "input": [_message_to_openai_input(message) for message in request.messages],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "taskmanagedai_structured_output",
                "schema": request.structured_output_schema,
                "strict": True,
            },
        },
    }

    if request.max_tokens is not None:
        body["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.safety_settings is not None:
        body["metadata"] = {
            "safety_settings_hash": compute_payload_hash(request.safety_settings),
            "provider_compliance_matrix_version": request.provider_compliance_matrix_version,
        }

    return body


def _message_to_openai_input(message: ProviderMessage) -> dict[str, str]:
    role = "user" if message.role == "tool" else message.role
    return {
        "role": role,
        "content": provider_message_content_to_text(message.content),
    }


def _map_openai_response_status(response: Mapping[str, Any]) -> ProviderResultKind:
    if _has_schema_error_signal(response):
        return "unsupported_schema"

    if _has_refusal_block(response):
        return "safety_refusal" if _has_safety_signal(response) else "refusal"

    status = str(response.get("status") or "").lower()
    if status == "incomplete":
        reason = _incomplete_reason(response)
        if reason in {"max_output_tokens", "max_tokens", "length"}:
            return "max_token"
        return "incomplete"
    if status in {"failed", "cancelled", "expired"}:
        return "incomplete"

    finish_reason = _finish_reason(response)
    if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
        return "max_token"
    if finish_reason in {"content_filter", "safety"}:
        return "safety_refusal"

    return "success"


def _has_refusal_block(response: Mapping[str, Any]) -> bool:
    output = response.get("output")
    if not isinstance(output, list):
        return False

    for item in output:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "").lower() == "refusal":
            return True
        content = item.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, Mapping) and "refusal" in str(
                    block.get("type") or block.get("refusal") or ""
                ).lower():
                    return True
    return False


def _has_safety_signal(response: Mapping[str, Any]) -> bool:
    signal = " ".join(
        str(value)
        for value in (
            response.get("status"),
            _finish_reason(response),
            _incomplete_reason(response),
        )
        if value is not None
    ).lower()
    return "safety" in signal or "content_filter" in signal


def _has_schema_error_signal(response: Mapping[str, Any]) -> bool:
    error = response.get("error")
    fields: list[str] = []
    if isinstance(error, Mapping):
        fields.extend(str(error.get(key) or "") for key in ("type", "code", "status", "message"))
    fields.append(str(response.get("status") or ""))

    joined = " ".join(fields).lower()
    return "schema" in joined or "unsupported" in joined


def _finish_reason(response: Mapping[str, Any]) -> str | None:
    for key in ("finish_reason", "finishReason", "stop_reason"):
        value = response.get(key)
        if isinstance(value, str) and value:
            return value.lower()

    choices = response.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, Mapping):
                value = choice.get("finish_reason")
                if isinstance(value, str) and value:
                    return value.lower()
    return None


def _incomplete_reason(response: Mapping[str, Any]) -> str | None:
    incomplete_details = response.get("incomplete_details")
    if isinstance(incomplete_details, Mapping):
        reason = incomplete_details.get("reason")
        if isinstance(reason, str) and reason:
            return reason.lower()
    return None


def _continuation_ref(
    request: ProviderRequest,
    response: Mapping[str, Any],
    status: ProviderResultKind,
) -> dict[str, Any] | None:
    if status not in {"max_token", "incomplete", "timeout_retryable"}:
        return None

    state = {
        "response_id_present": isinstance(response.get("id"), str) and bool(response.get("id")),
        "status": str(response.get("status") or status),
        "finish_reason": _finish_reason(response) or _incomplete_reason(response) or status,
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
        api_version=_OPENAI_API_VERSION,
        sdk_version=_OPENAI_SDK_VERSION,
        provider_request_fingerprint=compute_provider_request_fingerprint(
            request,
            matrix_version=request.provider_compliance_matrix_version,
            api_version=_OPENAI_API_VERSION,
            sdk_version=_OPENAI_SDK_VERSION,
        ),
        error_code=result_error_code,
        error_summary=result_error_summary,
        redacted_response_summary=summary,
        continuation_ref=result_continuation_ref,
    )


def _usage(response: dict[str, Any]) -> ProviderUsage:
    return provider_usage_from_response(
        response,
        input_token_keys=("input_tokens", "prompt_tokens"),
        output_token_keys=("output_tokens", "completion_tokens"),
    )


def _is_timeout_exception(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


__all__ = ["OpenAIResponsesAdapter"]

