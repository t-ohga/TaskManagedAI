from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, TypeGuard, TypeVar, cast

from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for

from backend.app.domain.agent_runtime.operation_context import compute_payload_hash
from backend.app.domain.provider.request import ProviderMessageContentBlock, ProviderRequest
from backend.app.domain.provider.result import ProviderUsage
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.services.agent_runtime.provider_result_mapping import ProviderResultKind

T = TypeVar("T")

_DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0


def resolve_maybe_awaitable[T](value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return _run_awaitable_sync(cast(Awaitable[T], value))
    return cast(T, value)


def _run_awaitable_sync[T](awaitable: Awaitable[T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    if inspect.iscoroutine(awaitable):
        awaitable.close()
    raise RuntimeError(
        "ProviderAdapter.execute() received an async dependency while an event loop "
        "is already running; inject a synchronous test client or call it outside the loop."
    )


def post_json(
    http_client: object,
    url: str,
    *,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    timeout: float = _DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    post = getattr(http_client, "post", None)
    if not callable(post):
        raise TypeError("http_client must expose a callable post() method.")

    response = resolve_maybe_awaitable(
        post(url, headers=dict(headers), json=dict(body), timeout=timeout)
    )
    return coerce_http_response(response)


def coerce_http_response(response: object) -> tuple[int, dict[str, Any]]:
    if isinstance(response, tuple) and len(response) == 2:
        return _coerce_status_code(response[0]), _coerce_response_body(response[1])

    status_code = _coerce_status_code(getattr(response, "status_code", 200))
    json_method = getattr(response, "json", None)
    if callable(json_method):
        return status_code, _coerce_response_body(resolve_maybe_awaitable(json_method()))

    return status_code, _coerce_response_body(response)


def _coerce_status_code(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("HTTP status_code must be an integer, not bool.")
    if value is None:
        return 200
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    raise TypeError("HTTP status_code must be an integer.")


def _coerce_response_body(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {"value": value}


def redact_response_summary(response: dict[str, Any], request: ProviderRequest) -> dict[str, Any]:
    """Build a redacted provider-response summary.

    R2 F-003: raw secret scanner failures must propagate to the caller. Provider
    adapters catch ValueError and convert the adapter result to
    status="incomplete" + error_code="raw_secret_in_response".
    """

    summary: dict[str, Any] = {
        "provider": request.provider,
        "api_or_feature": request.api_or_feature,
        "structured_output_schema_hash": compute_payload_hash(request.structured_output_schema),
    }

    http_status_code = _optional_int(response.get("_http_status_code"))
    if http_status_code is not None:
        summary["http_status_code"] = http_status_code

    model = _first_string(
        response.get("model"),
        response.get("modelVersion"),
        response.get("model_version"),
    )
    if model is not None:
        summary["model"] = model

    response_status = _first_string(response.get("status"))
    if response_status is not None:
        summary["status"] = response_status

    finish_reason = _finish_reason_from_response(response)
    if finish_reason is not None:
        summary["finish_reason"] = finish_reason

    usage = _usage_summary(response)
    if usage:
        summary["usage"] = usage

    for source_key, summary_key in (
        ("output", "output_items_count"),
        ("content", "content_items_count"),
        ("candidates", "candidates_count"),
        ("choices", "choices_count"),
    ):
        count = _count_sequence(response.get(source_key))
        if count is not None:
            summary[summary_key] = count

    response_id = response.get("id")
    if isinstance(response_id, str) and response_id:
        summary["response_id_present"] = True

    error = response.get("error")
    if isinstance(error, Mapping):
        safe_error: dict[str, Any] = {}
        for key in ("type", "code", "status"):
            value = _safe_scalar(error.get(key))
            if value is not None:
                safe_error[key] = value
        if safe_error:
            summary["error"] = safe_error

    assert_no_raw_secret(summary, path="$provider_response_summary")
    return summary


def raw_secret_response_summary(request: ProviderRequest) -> dict[str, Any]:
    summary = {
        "provider": request.provider,
        "api_or_feature": request.api_or_feature,
        "structured_output_schema_hash": compute_payload_hash(request.structured_output_schema),
        "redaction": "raw_secret_in_response",
    }
    assert_no_raw_secret(summary, path="$provider_response_summary")
    return summary


def map_http_status_to_result_kind(status_code: int) -> ProviderResultKind:
    """Map HTTP status to ProviderResultKind.

    R2 F-001 keeps ProviderResultKind within the Sprint 4 Batch 4 11-kind
    contract. 401/403/general 4xx are returned as "incomplete" but adapters
    must attach specific error_code values such as "http_401_unauthorized" or
    "http_400_client_error". AgentRun retry suppression based on these
    error_code values is deferred to Sprint 6+ worker retry policy.
    """

    if 200 <= status_code < 300:
        return "success"
    if status_code == 429:
        return "timeout_retryable"
    if 400 <= status_code < 500:
        return "incomplete"
    if 500 <= status_code < 600:
        return "incomplete"
    return "incomplete"


def http_error_code_from_status(status_code: int) -> str | None:
    if 200 <= status_code < 300:
        return None
    if status_code == 401:
        return "http_401_unauthorized"
    if status_code == 403:
        return "http_403_forbidden"
    if status_code == 429:
        return "http_429_rate_limit"
    if 400 <= status_code < 500:
        return f"http_{status_code}_client_error"
    if 500 <= status_code < 600:
        return f"http_{status_code}_server_error"
    return f"http_{status_code}"


def extract_structured_output(
    response: dict[str, Any],
    schema: dict[str, Any],
) -> tuple[dict[str, Any] | None, ProviderResultKind]:
    try:
        validator_cls = validator_for(schema)
        validator_cls.check_schema(schema)
    except SchemaError:
        return None, "unsupported_schema"

    candidate = _find_structured_candidate(response)
    if candidate is None:
        return None, "schema_mismatch"

    try:
        validator_cls(schema).validate(candidate)
    except SchemaError:
        return None, "unsupported_schema"
    except JsonSchemaValidationError:
        return None, "schema_mismatch"

    structured = _structured_output_as_dict(candidate)
    try:
        assert_no_raw_secret(structured, path="$provider_structured_output")
    except ValueError:
        return None, "schema_mismatch"

    return structured, "success"


def _structured_output_as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {"value": value}


def _find_structured_candidate(response: dict[str, Any]) -> object | None:
    for key in ("structured_output", "output_parsed", "output_json", "parsed"):
        candidate = _coerce_structured_candidate(response.get(key))
        if candidate is not None:
            return candidate

    candidate = _coerce_structured_candidate(response.get("output_text"))
    if candidate is not None:
        return candidate

    for key in ("output", "content", "choices", "candidates"):
        candidate = _extract_candidate_from_sequence(response.get(key))
        if candidate is not None:
            return candidate

    return None


def _extract_candidate_from_sequence(value: object) -> object | None:
    if not _is_sequence(value):
        return None

    for item in value:
        if not isinstance(item, Mapping):
            continue

        candidate = _candidate_from_mapping(item)
        if candidate is not None:
            return candidate

        content = item.get("content")
        if isinstance(content, Mapping):
            candidate = _candidate_from_mapping(content)
        else:
            candidate = _extract_candidate_from_sequence(content)
        if candidate is not None:
            return candidate

        message = item.get("message")
        if isinstance(message, Mapping):
            candidate = _candidate_from_mapping(message)
            if candidate is not None:
                return candidate

        parts = item.get("parts")
        candidate = _candidate_from_gemini_parts(parts)
        if candidate is None:
            candidate = _extract_candidate_from_sequence(parts)
        if candidate is not None:
            return candidate

    return None


def _candidate_from_mapping(value: Mapping[str, Any]) -> object | None:
    for key in ("parsed", "input", "arguments", "args"):
        candidate = _coerce_structured_candidate(value.get(key))
        if candidate is not None:
            return candidate

    function_call = value.get("function_call")
    if isinstance(function_call, Mapping):
        candidate = _coerce_structured_candidate(function_call.get("arguments"))
        if candidate is not None:
            return candidate

    function_call = value.get("functionCall")
    if isinstance(function_call, Mapping):
        candidate = _coerce_structured_candidate(function_call.get("args"))
        if candidate is not None:
            return candidate

    tool_calls = value.get("tool_calls")
    if _is_sequence(tool_calls):
        for tool_call in tool_calls:
            if not isinstance(tool_call, Mapping):
                continue
            function = tool_call.get("function")
            if isinstance(function, Mapping):
                candidate = _coerce_structured_candidate(function.get("arguments"))
                if candidate is not None:
                    return candidate

    candidate = _candidate_from_gemini_parts(value.get("parts"))
    if candidate is not None:
        return candidate

    candidate = _coerce_structured_candidate(value.get("text"))
    if candidate is not None:
        return candidate

    content = value.get("content")
    if isinstance(content, Mapping):
        candidate = _candidate_from_mapping(content)
    elif _is_sequence(content):
        candidate = _extract_candidate_from_sequence(content)
        if candidate is None:
            candidate = _coerce_structured_candidate(content)
    else:
        candidate = _coerce_structured_candidate(content)
    if candidate is not None:
        return candidate

    return None


def _candidate_from_gemini_parts(value: object) -> object | None:
    """Extract structured JSON from Gemini content.parts.

    R3-F-002 (R4): Gemini canonical responses put JSON text under
    candidates[].content.parts[].text. Function-call args are normalized through
    the same JSON candidate path when providers return them in parts[].functionCall.
    """

    if not _is_sequence(value):
        return None

    text_parts: list[str] = []
    for part in value:
        if not isinstance(part, Mapping):
            continue

        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)

        function_call = part.get("functionCall")
        if isinstance(function_call, Mapping):
            candidate = _coerce_structured_candidate(function_call.get("args"))
            if candidate is not None:
                text_parts.append(json.dumps(candidate))

    if not text_parts:
        return None

    return _coerce_structured_candidate("".join(text_parts))


def _coerce_structured_candidate(value: object) -> object | None:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return _parse_json_string(value)
    return None


def _parse_json_string(value: str) -> object | None:
    if not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def attach_structured_output_metadata(
    summary: dict[str, Any],
    structured_output: dict[str, Any],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "structured_output_sha256": compute_payload_hash(structured_output),
        "structured_output_top_level_keys": sorted(str(key) for key in structured_output)[:50],
    }
    merged = dict(summary)
    merged.update(metadata)

    try:
        assert_no_raw_secret(merged, path="$provider_response_summary")
        return merged
    except ValueError:
        fallback = dict(summary)
        fallback["structured_output_metadata_redacted"] = True
        assert_no_raw_secret(fallback, path="$provider_response_summary")
        return fallback


def build_structured_artifact_ref(provider: str, structured_output: dict[str, Any]) -> str:
    output_hash = compute_payload_hash(structured_output)
    return f"provider-artifact:{provider}:{output_hash[:16]}"


def build_non_exportable_continuation_ref(
    *,
    provider: str,
    api_or_feature: str,
    state: Mapping[str, Any],
    ttl_seconds: int = 1800,
) -> dict[str, Any]:
    state_hash = compute_payload_hash(dict(state))
    expires_at = (
        datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=ttl_seconds)
    ).isoformat()
    continuation_ref = {
        "provider": provider,
        "api_or_feature": api_or_feature,
        "artifact_ref": f"provider-continuation:{provider}:{state_hash[:16]}",
        "sha256": state_hash,
        "expires_at": expires_at,
        "exportable": False,
    }
    assert_no_raw_secret(continuation_ref, path="$provider_continuation_ref")
    return continuation_ref


def provider_usage_from_response(
    response: dict[str, Any],
    *,
    input_token_keys: tuple[str, ...],
    output_token_keys: tuple[str, ...],
) -> ProviderUsage:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        usage = response.get("usageMetadata")
    if not isinstance(usage, Mapping):
        usage = {}

    tokens_input = _first_nonnegative_int(usage, input_token_keys) or 0
    tokens_output = _first_nonnegative_int(usage, output_token_keys) or 0
    cost_usd = _first_nonnegative_float(usage, ("cost_usd", "costUsd")) or 0.0

    return ProviderUsage(
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        cost_usd=cost_usd,
    )


def provider_message_content_to_text(
    content: str | list[ProviderMessageContentBlock],
) -> str:
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content:
        if block.type == "text" and block.text is not None:
            parts.append(block.text)
        elif block.type == "image_ref" and block.image_ref is not None:
            parts.append(f"[image_ref:{block.image_ref}]")
        elif block.type == "tool_result" and block.output is not None:
            parts.append(block.output)
        elif block.type == "tool_use" and block.tool_name is not None:
            parts.append(f"[tool_use:{block.tool_name}]")
    return "\n".join(parts)


def redacted_error_summary(prefix: str, detail: object | None = None) -> str:
    if detail is None:
        candidate = prefix
    else:
        candidate = f"{prefix}: {str(detail)[:240]}"

    try:
        assert_no_raw_secret({"summary": candidate}, path="$provider_error_summary")
        return candidate
    except ValueError:
        return prefix


def _usage_summary(response: Mapping[str, Any]) -> dict[str, Any]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        usage = response.get("usageMetadata")
    if not isinstance(usage, Mapping):
        return {}

    summary: dict[str, Any] = {}
    for key in (
        "input_tokens",
        "output_tokens",
        "promptTokenCount",
        "candidatesTokenCount",
        "total_tokens",
        "totalTokenCount",
        "cost_usd",
        "costUsd",
    ):
        value = _safe_scalar(usage.get(key))
        if value is not None:
            summary[key] = value
    return summary


def _finish_reason_from_response(response: Mapping[str, Any]) -> str | None:
    direct = _first_string(
        response.get("finish_reason"),
        response.get("stop_reason"),
        response.get("finishReason"),
    )
    if direct is not None:
        return direct

    incomplete_details = response.get("incomplete_details")
    if isinstance(incomplete_details, Mapping):
        reason = _first_string(incomplete_details.get("reason"))
        if reason is not None:
            return reason

    choices = response.get("choices")
    if _is_sequence(choices):
        for choice in choices:
            if isinstance(choice, Mapping):
                reason = _first_string(choice.get("finish_reason"))
                if reason is not None:
                    return reason

    candidates = response.get("candidates")
    if _is_sequence(candidates):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                reason = _first_string(candidate.get("finishReason"))
                if reason is not None:
                    return reason

    return None


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _safe_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return None


def _count_sequence(value: object) -> int | None:
    if _is_sequence(value):
        return len(value)
    return None


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _first_nonnegative_int(
    mapping: Mapping[str, Any],
    keys: tuple[str, ...],
) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, float) and value.is_integer() and value >= 0:
            return int(value)
    return None


def _first_nonnegative_float(
    mapping: Mapping[str, Any],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value >= 0:
            return float(value)
    return None


__all__ = [
    "attach_structured_output_metadata",
    "build_non_exportable_continuation_ref",
    "build_structured_artifact_ref",
    "coerce_http_response",
    "extract_structured_output",
    "http_error_code_from_status",
    "map_http_status_to_result_kind",
    "post_json",
    "provider_message_content_to_text",
    "provider_usage_from_response",
    "raw_secret_response_summary",
    "redact_response_summary",
    "redacted_error_summary",
    "resolve_maybe_awaitable",
]

