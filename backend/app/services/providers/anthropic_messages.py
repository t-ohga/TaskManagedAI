from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.app.domain.provider.fingerprint import compute_provider_request_fingerprint
from backend.app.domain.provider.request import (
    ProviderMessage,
    ProviderMessageContentBlock,
    ProviderRequest,
)
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

_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_API_VERSION = "2026-04-01"
_ANTHROPIC_SDK_VERSION = "anthropic-python-0.x"
_STRUCTURED_TOOL_NAME = "taskmanagedai_structured_output"
_HTTP_TIMEOUT_SECONDS = 30.0

SecretTokenResolver = Callable[[str], str | Awaitable[str]]


class AnthropicMessagesAdapter:
    def __init__(self, http_client: object, secret_token_resolver: SecretTokenResolver) -> None:
        self._http_client = http_client
        self._secret_token_resolver = secret_token_resolver

    def provider_name(self) -> str:
        return "anthropic"

    def api_or_feature(self) -> str:
        return "messages"

    def execute(self, request: ProviderRequest) -> ProviderResult:
        _validate_request(request)
        api_key = _resolve_api_key(request, self._secret_token_resolver)
        body = _build_messages_body(request)
        headers = {
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }

        try:
            status_code, response_payload = post_json(
                self._http_client,
                _ANTHROPIC_MESSAGES_URL,
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
                error_code="anthropic_timeout"
                if status == "timeout_retryable"
                else "anthropic_transport_error",
                error_summary=redacted_error_summary("Anthropic Messages transport error"),
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
                    "Anthropic Messages HTTP error",
                    f"status={status_code}",
                ),
            )

        provider_status = _map_anthropic_response_status(response)
        if provider_status != "success":
            return _build_result(
                request=request,
                status=provider_status,
                response=response,
                error_code=f"anthropic_{provider_status}",
                error_summary=redacted_error_summary(
                    "Anthropic Messages returned non-success status",
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
                error_code=f"anthropic_{validation_status}",
                error_summary=redacted_error_summary(
                    "Anthropic Messages structured output validation failed",
                    validation_status,
                ),
            )

        return _build_result(
            request=request,
            status="success",
            response=response,
            artifact_ref=build_structured_artifact_ref("anthropic", structured_output),
            structured_output=structured_output,
        )


def _validate_request(request: ProviderRequest) -> None:
    if request.provider != "anthropic":
        raise ValueError(
            "AnthropicMessagesAdapter only handles provider='anthropic', "
            f"got {request.provider!r}"
        )
    if request.api_or_feature != "messages":
        raise ValueError(
            "AnthropicMessagesAdapter only handles api_or_feature='messages', "
            f"got {request.api_or_feature!r}"
        )


def _resolve_api_key(
    request: ProviderRequest,
    resolver: SecretTokenResolver,
) -> str:
    token = request.secret_capability_token
    if token is None:
        raise ValueError(
            "AnthropicMessagesAdapter requires request.secret_capability_token from "
            "SecretBroker."
        )

    resolved = resolve_maybe_awaitable(resolver(token))
    if not isinstance(resolved, str) or not resolved:
        raise ValueError("secret_token_resolver must return a non-empty provider credential.")
    return resolved


def _build_messages_body(request: ProviderRequest) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []

    for message in request.messages:
        if message.role == "system":
            system_parts.append(provider_message_content_to_text(message.content))
            continue
        messages.append(_message_to_anthropic_message(message))

    body: dict[str, Any] = {
        "model": request.model_resolved,
        "max_tokens": request.max_tokens or 1024,
        "messages": messages,
        "tools": [
            {
                "name": _STRUCTURED_TOOL_NAME,
                "description": "Return the task result as JSON matching the provided schema.",
                "input_schema": request.structured_output_schema,
            }
        ],
        "tool_choice": {"type": "tool", "name": _STRUCTURED_TOOL_NAME},
    }

    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    if request.temperature is not None:
        body["temperature"] = request.temperature

    return body


def _message_to_anthropic_message(message: ProviderMessage) -> dict[str, Any]:
    role = "assistant" if message.role == "assistant" else "user"
    return {
        "role": role,
        "content": _content_to_anthropic_blocks(message.content),
    }


def _content_to_anthropic_blocks(
    content: str | list[ProviderMessageContentBlock],
) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    blocks: list[dict[str, Any]] = []
    for block in content:
        if block.type == "text" and block.text is not None:
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_result" and block.tool_call_id is not None:
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_call_id,
                    "content": block.output or "",
                }
            )
        elif block.type == "tool_use" and block.tool_call_id is not None:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.tool_call_id,
                    "name": block.tool_name or "unknown_tool",
                    "input": {},
                }
            )
        elif block.type == "image_ref" and block.image_ref is not None:
            blocks.append({"type": "text", "text": f"[image_ref:{block.image_ref}]"})
    return blocks


def _map_anthropic_response_status(response: Mapping[str, Any]) -> ProviderResultKind:
    if _has_schema_error_signal(response):
        return "unsupported_schema"
    if _has_refusal_signal(response):
        return "safety_refusal" if _has_safety_signal(response) else "refusal"

    stop_reason = str(response.get("stop_reason") or "").lower()
    if stop_reason == "max_tokens":
        return "max_token"
    if stop_reason in {"pause_turn", "model_context_window_exceeded"}:
        return "incomplete"
    if stop_reason in {"refusal", "content_filter"}:
        return "refusal"

    return "success"


def _has_refusal_signal(response: Mapping[str, Any]) -> bool:
    content = response.get("content")
    if not isinstance(content, list):
        return False

    for block in content:
        if not isinstance(block, Mapping):
            continue
        block_type = str(block.get("type") or "").lower()
        if "refusal" in block_type:
            return True
    return False


def _has_safety_signal(response: Mapping[str, Any]) -> bool:
    stop_reason = str(response.get("stop_reason") or "").lower()
    if "safety" in stop_reason or "content_filter" in stop_reason:
        return True

    content = response.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping):
                block_type = str(block.get("type") or "").lower()
                if "safety" in block_type or "content_filter" in block_type:
                    return True
    return False


def _has_schema_error_signal(response: Mapping[str, Any]) -> bool:
    error = response.get("error")
    fields: list[str] = []
    if isinstance(error, Mapping):
        fields.extend(str(error.get(key) or "") for key in ("type", "code", "status", "message"))
    fields.append(str(response.get("stop_reason") or ""))

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
        "message_id_present": isinstance(response.get("id"), str) and bool(response.get("id")),
        "stop_reason": str(response.get("stop_reason") or status),
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
        api_version=_ANTHROPIC_API_VERSION,
        sdk_version=_ANTHROPIC_SDK_VERSION,
        provider_request_fingerprint=compute_provider_request_fingerprint(
            request,
            matrix_version=request.provider_compliance_matrix_version,
            api_version=_ANTHROPIC_API_VERSION,
            sdk_version=_ANTHROPIC_SDK_VERSION,
        ),
        error_code=result_error_code,
        error_summary=result_error_summary,
        redacted_response_summary=summary,
        continuation_ref=result_continuation_ref,
    )


def _usage(response: dict[str, Any]) -> ProviderUsage:
    return provider_usage_from_response(
        response,
        input_token_keys=("input_tokens",),
        output_token_keys=("output_tokens",),
    )


def _is_timeout_exception(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


__all__ = ["AnthropicMessagesAdapter"]

