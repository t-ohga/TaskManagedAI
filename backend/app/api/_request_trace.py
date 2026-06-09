"""Request correlation / trace id の sanitize helper (SP-032 で新設、共有)。

claims.py 等が inline で持つ `_TRACE_ID_RE` / `_correlation_id` / `_trace_id` と同一ロジック。
caller-controlled な x-trace-id / x-correlation-id header に raw secret / canary が混入する経路を
遮断するため、W3C/OpenTelemetry hex (16-32) + UUID のみ許可し、不正 format は drop する。
"""

from __future__ import annotations

import re

from fastapi import Request

# secret-shaped string (sk- / Bearer / api_key_ 等) を許可しない narrow な format。
# W3C / OpenTelemetry hex (16-32 chars) + UUID (with hyphen) のみ。
_TRACE_ID_RE = re.compile(
    r"^[0-9a-fA-F]{16,32}$"
    r"|^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def correlation_id(request: Request) -> str:
    value = request.headers.get("x-correlation-id")
    if value and _TRACE_ID_RE.fullmatch(value):
        return value
    fallback = str(getattr(request.state, "request_id", ""))
    if fallback and _TRACE_ID_RE.fullmatch(fallback):
        return fallback
    return ""


def trace_id(request: Request) -> str | None:
    value = request.headers.get("x-trace-id")
    if value is None or not _TRACE_ID_RE.fullmatch(value):
        return None
    return value


__all__ = ["correlation_id", "trace_id"]
