from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from backend.app.domain.memory.redaction_status import MemoryRedactionStatus
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.artifact import canonical_json_for_hash

MemoryPayloadRejectReason = Literal[
    "raw_secret_or_canary",
    "server_owned_claim",
]

_PROHIBITED_SERVER_OWNED_MEMORY_KEYS: frozenset[str] = frozenset(
    {
        "tenant_id",
        "project_id",
        "run_id",
        "record_kind",
        "content_artifact_ref",
        "content_hash",
        "data_class",
        "payload_data_class",
        "redaction_status",
        "sanitizer_version_id",
        "sanitizer_policy_version",
        "source_artifact_id",
        "trust_level",
        "retention_until",
        "archived_at",
        "created_at",
        "memory_record_id",
        "retrieval_artifact_ref",
        "retrieval_hash",
        "retrieval_run_id",
        "context_snapshot_id",
    }
)


class MemoryPayloadRejected(ValueError):
    def __init__(self, reason_code: MemoryPayloadRejectReason, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class SanitizedMemoryPayload:
    content_jsonb: dict[str, Any]
    content_hash: str
    sanitizer_policy_version: str
    redaction_status: MemoryRedactionStatus = "redacted"


def sanitize_memory_payload(
    payload: dict[str, Any],
    *,
    schema_version: str,
    sanitizer_policy_version: str,
) -> SanitizedMemoryPayload:
    """Validate and canonicalize memory content before artifact storage."""

    if not isinstance(payload, dict):
        raise ValueError("memory payload must be a JSON object.")
    if not schema_version.strip():
        raise ValueError("schema_version must be non-empty.")
    if not sanitizer_policy_version.strip():
        raise ValueError("sanitizer_policy_version must be non-empty.")

    try:
        assert_no_raw_secret(payload, path="$memory.payload")
    except ValueError as exc:
        raise MemoryPayloadRejected("raw_secret_or_canary", str(exc)) from exc
    _assert_no_server_owned_claims(payload)

    content: dict[str, Any] = {
        "schema_version": schema_version,
        "sanitizer_policy_version": sanitizer_policy_version,
        "payload": payload,
    }
    canonical = canonical_json_for_hash(content)
    normalized = json.loads(canonical)
    if not isinstance(normalized, dict):
        raise ValueError("memory payload canonicalization must produce an object.")

    return SanitizedMemoryPayload(
        content_jsonb=normalized,
        content_hash=sha256(canonical.encode("utf-8")).hexdigest(),
        sanitizer_policy_version=sanitizer_policy_version,
    )


def _assert_no_server_owned_claims(
    obj: object,
    *,
    path: str = "$memory.payload",
) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ValueError(f"memory payload contains non-string key at {path}.")
            child_path = f"{path}.{key}" if key.isidentifier() else f"{path}[{key!r}]"
            if key in _PROHIBITED_SERVER_OWNED_MEMORY_KEYS:
                raise MemoryPayloadRejected(
                    "server_owned_claim",
                    "memory payload contains server-owned claim key "
                    f"at {child_path}.",
                )
            _assert_no_server_owned_claims(value, path=child_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _assert_no_server_owned_claims(value, path=f"{path}[{index}]")


__all__ = [
    "MemoryPayloadRejectReason",
    "MemoryPayloadRejected",
    "SanitizedMemoryPayload",
    "_PROHIBITED_SERVER_OWNED_MEMORY_KEYS",
    "sanitize_memory_payload",
]
