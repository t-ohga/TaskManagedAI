from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID

RequestedOperation = Literal[
    "provider.call",
    "repo.push",
    "repo.pr_open",
    "secret.verify",
    "rotation.read_old",
    "rotation.read_new",
]

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")

_REQUIRED_TARGET_KEYS: dict[RequestedOperation, frozenset[str]] = {
    "provider.call": frozenset({"provider", "api_or_feature", "model_resolved"}),
    "repo.push": frozenset({"repo_full_name", "branch", "commit_sha"}),
    # Codex SP8 R1 F-SP8-007 adopt: 4 整合 binding (artifact_hash / policy_version /
    # provider_request_fingerprint / repo_state_commit_sha) を fingerprint で
    # 表現するため、target に commit_sha (head 確定値) と repo_state_commit_sha
    # (push 直前 HEAD) を追加。ADR-00011 §採用案 + SP-008 §設計判断 で要求。
    "repo.pr_open": frozenset(
        {
            "repo_full_name",
            "base_branch",
            "head_branch",
            "draft",
            "commit_sha",
            "repo_state_commit_sha",
        }
    ),
    "secret.verify": frozenset({"secret_ref_id", "version"}),
    "rotation.read_old": frozenset({"secret_ref_id", "version"}),
    "rotation.read_new": frozenset({"secret_ref_id", "version"}),
}


@dataclass(frozen=True, slots=True)
class OperationContext:
    tenant_id: int
    actor_id: UUID
    run_id: UUID | None
    secret_ref_id: UUID
    requested_operation: RequestedOperation
    target: Mapping[str, object]
    payload_hash: str
    approval_id: UUID | None
    policy_version: str
    provider_compliance_matrix_version: str | None

    def __post_init__(self) -> None:
        validate_operation_context(self)


def _normalize_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _json_safe(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return _normalize_string(value)
    if isinstance(value, Mapping):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return value


def canonical_json_dumps(value: object) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_payload_hash(payload: object) -> str:
    if isinstance(payload, bytes):
        payload_bytes = payload
    elif isinstance(payload, str):
        payload_bytes = _normalize_string(payload).encode("utf-8")
    else:
        payload_bytes = canonical_json_dumps(payload).encode("utf-8")
    return hashlib.sha256(payload_bytes).hexdigest()


def compute_fingerprint(ctx: OperationContext) -> str:
    canonical_json = canonical_json_dumps(asdict(ctx))
    normalized = unicodedata.normalize("NFC", canonical_json)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_operation_context(ctx: OperationContext) -> None:
    if not isinstance(ctx.tenant_id, int) or isinstance(ctx.tenant_id, bool) or ctx.tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")
    if not _SHA256_HEX_RE.fullmatch(ctx.payload_hash):
        raise ValueError("payload_hash must be a SHA-256 lowercase hex digest.")
    if not ctx.policy_version:
        raise ValueError("policy_version is required.")

    required_keys = _REQUIRED_TARGET_KEYS[ctx.requested_operation]
    target_keys = frozenset(ctx.target.keys())
    if target_keys != required_keys:
        raise ValueError(
            f"{ctx.requested_operation} target keys must be {sorted(required_keys)}, "
            f"got {sorted(target_keys)}."
        )

    if ctx.requested_operation == "provider.call":
        _require_nonempty_string(ctx.target, "provider")
        _require_nonempty_string(ctx.target, "api_or_feature")
        _require_nonempty_string(ctx.target, "model_resolved")
        if not ctx.provider_compliance_matrix_version:
            raise ValueError(
                "provider_compliance_matrix_version is required for provider.call."
            )
        return

    if ctx.requested_operation == "repo.push":
        _require_nonempty_string(ctx.target, "repo_full_name")
        _require_nonempty_string(ctx.target, "branch")
        _require_nonempty_string(ctx.target, "commit_sha")
        return

    if ctx.requested_operation == "repo.pr_open":
        _require_nonempty_string(ctx.target, "repo_full_name")
        _require_nonempty_string(ctx.target, "base_branch")
        _require_nonempty_string(ctx.target, "head_branch")
        # Codex SP8 R1 F-SP8-007 adopt: server-owned 4 整合 binding に必要
        _require_nonempty_string(ctx.target, "commit_sha")
        _require_nonempty_string(ctx.target, "repo_state_commit_sha")
        if ctx.target["draft"] is not True:
            raise ValueError("repo.pr_open target draft must be true.")
        return

    _require_nonempty_string(ctx.target, "version")
    try:
        UUID(str(ctx.target["secret_ref_id"]))
    except ValueError as exc:
        raise ValueError("secret target secret_ref_id must be a UUID.") from exc


def _require_nonempty_string(target: Mapping[str, object], key: str) -> None:
    value = target[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"target.{key} must be a non-empty string.")


__all__ = [
    "OperationContext",
    "RequestedOperation",
    "canonical_json_dumps",
    "compute_fingerprint",
    "compute_payload_hash",
    "validate_operation_context",
]

