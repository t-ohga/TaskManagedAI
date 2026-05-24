from __future__ import annotations

import re

from tm.types import JSONValue

_SAFE_IDENTIFIER_KEYS = {
    "token_id",
    "principal_id",
    "approval_id",
    "project_id",
    "ticket_id",
    "run_id",
    "authorization_header_used",
}
_SENSITIVE_FRAGMENTS = (
    "operation_token",
    "raw_operation_token",
    "capability_token",
    "secret",
    "password",
    "api_key",
    "authorization",
    "credential",
    "access_token",
    "refresh_token",
)
_RAW_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AGE-SECRET-KEY-[A-Z0-9]{10,}"),
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
)


def redact_json(value: JSONValue) -> JSONValue:
    if isinstance(value, dict):
        redacted: dict[str, JSONValue] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_json(item)
        return redacted
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, str) and _is_sensitive_value(value):
        return "[REDACTED]"
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    if normalized in _SAFE_IDENTIFIER_KEYS:
        return False
    return any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def _is_sensitive_value(value: str) -> bool:
    return any(pattern.search(value) is not None for pattern in _RAW_SECRET_VALUE_PATTERNS)
