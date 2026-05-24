from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.artifact import canonical_json_for_hash

InterAgentPayloadRejectReason = Literal[
    "inter_agent_message_token_payload",
    "raw_secret_or_canary",
    "server_owned_claim",
]
InterAgentRedactionStatus = Literal["clean"]
_INTER_AGENT_TOKEN_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "capability_token",
        "capability_token_value",
        "raw_token",
        "secret_capability_token",
        "session_token",
    }
)
_PROHIBITED_SERVER_OWNED_CLAIM_KEYS: frozenset[str] = frozenset(
    {
        "tenant_id",
        "project_id",
        "sender_actor_id",
        "sender_run_id",
        "parent_run_id",
        "child_run_id",
        "payload_data_class",
        "trust_level",
        "approval_request_id",
        "source_artifact_id",
        "artifact_hash",
        "policy_version",
        "provider_request_fingerprint",
        "action_class",
    }
)


class InterAgentPayloadRejected(ValueError):
    def __init__(self, reason_code: InterAgentPayloadRejectReason, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class SanitizedInterAgentPayload:
    content_jsonb: dict[str, Any]
    payload_hash: str
    sanitizer_policy_version: str
    redaction_status: InterAgentRedactionStatus = "clean"


def sanitize_inter_agent_payload(
    payload: dict[str, Any],
    *,
    schema_version: str,
    sanitizer_policy_version: str,
) -> SanitizedInterAgentPayload:
    """Validate and canonicalize an inter-agent message body.

    Batch 0b is intentionally fail-closed: raw secrets / canaries are rejected
    rather than redacted into a possibly misleading message.
    """

    if not isinstance(payload, dict):
        raise ValueError("inter-agent payload must be a JSON object.")
    if not schema_version.strip():
        raise ValueError("schema_version must be non-empty.")
    if not sanitizer_policy_version.strip():
        raise ValueError("sanitizer_policy_version must be non-empty.")

    if _contains_inter_agent_token_payload(payload):
        raise InterAgentPayloadRejected(
            "inter_agent_message_token_payload",
            "inter-agent message payload must not contain SecretBroker capability token.",
        )
    try:
        assert_no_raw_secret(payload, path="$inter_agent.payload")
    except ValueError as exc:
        raise InterAgentPayloadRejected("raw_secret_or_canary", str(exc)) from exc
    _assert_no_server_owned_claims(payload)

    content: dict[str, Any] = {
        "schema_version": schema_version,
        "sanitizer_policy_version": sanitizer_policy_version,
        "payload": payload,
    }
    canonical = canonical_json_for_hash(content)
    normalized = json.loads(canonical)
    if not isinstance(normalized, dict):
        raise ValueError("inter-agent payload canonicalization must produce an object.")

    return SanitizedInterAgentPayload(
        content_jsonb=normalized,
        payload_hash=sha256(canonical.encode("utf-8")).hexdigest(),
        sanitizer_policy_version=sanitizer_policy_version,
    )


def _contains_inter_agent_token_payload(obj: object) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _INTER_AGENT_TOKEN_PAYLOAD_KEYS:
                return True
            if _contains_inter_agent_token_payload(value):
                return True
    elif isinstance(obj, list):
        return any(_contains_inter_agent_token_payload(value) for value in obj)
    return False


def _assert_no_server_owned_claims(
    obj: object,
    *,
    path: str = "$inter_agent.payload",
) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ValueError(f"inter-agent payload contains non-string key at {path}.")
            child_path = f"{path}.{key}" if key.isidentifier() else f"{path}[{key!r}]"
            if key in _PROHIBITED_SERVER_OWNED_CLAIM_KEYS:
                raise InterAgentPayloadRejected(
                    "server_owned_claim",
                    "inter-agent payload contains server-owned claim key "
                    f"at {child_path}.",
                )
            _assert_no_server_owned_claims(value, path=child_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _assert_no_server_owned_claims(value, path=f"{path}[{index}]")


__all__ = [
    "InterAgentPayloadRejectReason",
    "InterAgentPayloadRejected",
    "InterAgentRedactionStatus",
    "SanitizedInterAgentPayload",
    "_INTER_AGENT_TOKEN_PAYLOAD_KEYS",
    "_PROHIBITED_SERVER_OWNED_CLAIM_KEYS",
    "sanitize_inter_agent_payload",
]
