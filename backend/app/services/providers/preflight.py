from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.app.domain.provider.request import ProviderRequest
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret

_CANARY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("canary_pattern", re.compile(r"CANARY-FIXTURE-[A-Z0-9]{16,}")),
)


class PreflightResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["allow", "deny"]
    pattern_hit_kind: str | None = None


def provider_request_preflight(request: ProviderRequest) -> PreflightResult:
    payload = _request_to_scan_payload(request)

    for hit_kind, regex in _CANARY_PATTERNS:
        if _scan_string_payload(payload, regex):
            return PreflightResult(decision="deny", pattern_hit_kind=hit_kind)

    try:
        assert_no_raw_secret(payload, path="$provider_request_preflight")
    except ValueError as exc:
        return PreflightResult(decision="deny", pattern_hit_kind=_extract_hit_kind(str(exc)))

    redacted_metadata_hit = _find_redacted_scanner_metadata(payload)
    if redacted_metadata_hit is not None:
        return PreflightResult(decision="deny", pattern_hit_kind=redacted_metadata_hit)

    return PreflightResult(decision="allow", pattern_hit_kind=None)


def _request_to_scan_payload(request: ProviderRequest) -> dict[str, Any]:
    return {
        "messages": [_json_safe_message(message) for message in getattr(request, "messages", [])],
        "structured_output_schema": _json_safe_value(getattr(request, "structured_output_schema", {})),
        "safety_settings": _json_safe_value(getattr(request, "safety_settings", None)),
    }


def _scan_string_payload(obj: Any, regex: re.Pattern[str]) -> bool:
    if isinstance(obj, dict):
        return any(
            regex.search(str(key)) is not None or _scan_string_payload(value, regex)
            for key, value in obj.items()
        )
    if isinstance(obj, list | tuple):
        return any(_scan_string_payload(item, regex) for item in obj)
    if isinstance(obj, str):
        return regex.search(obj) is not None
    return False


def _json_safe_message(message: Any) -> Any:
    if hasattr(message, "model_dump"):
        return message.model_dump(mode="json")
    return _json_safe_value(message)


def _json_safe_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe_value(item) for item in value]
    return value


def _find_redacted_scanner_metadata(obj: Any) -> str | None:
    if isinstance(obj, dict):
        direct_hit = obj.get("pattern_hit_kind")
        if direct_hit in {"canary_pattern", "provider_key_pattern", "secret_pattern"}:
            return str(direct_hit)

        contains_marker = obj.get("contains_scanner_detectable_marker")
        scanner_ref = obj.get("scanner_pattern_ref")
        if contains_marker is True and isinstance(scanner_ref, str) and scanner_ref != "none":
            return _scanner_ref_to_hit_kind(scanner_ref)

        for value in obj.values():
            hit = _find_redacted_scanner_metadata(value)
            if hit is not None:
                return hit
    elif isinstance(obj, list | tuple):
        for item in obj:
            hit = _find_redacted_scanner_metadata(item)
            if hit is not None:
                return hit
    return None


def _scanner_ref_to_hit_kind(scanner_ref: str) -> str:
    lowered = scanner_ref.lower()
    if "canary" in lowered:
        return "canary_pattern"
    if "provider" in lowered or "key" in lowered or "token" in lowered:
        return "provider_key_pattern"
    return "secret_pattern"


def _extract_hit_kind(message: str) -> str:
    if "prohibited payload key" in message:
        key_match = re.search(r"\.'([^']+)'", message)
        if key_match is not None:
            return f"prohibited_key:{key_match.group(1)}"
        return "prohibited_payload_key"

    quoted_match = re.search(r"\('([^']+)'\)", message)
    if quoted_match is not None:
        return quoted_match.group(1)

    bare_match = re.search(r"\(([A-Za-z0-9_:-]+)\)", message)
    if bare_match is not None:
        return bare_match.group(1)

    return "raw_secret_pattern"


__all__ = ["PreflightResult", "provider_request_preflight"]

