from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

ALL_CAPABILITIES: tuple[str, ...] = (
    "task_list",
    "task_show",
    "task_create",
    "task_write",
    "approval_list",
    "approval_decide",
    "repo_status",
    "repo_push",
    "pr_open",
    "run_show",
    "run_cancel",
    "secret_resolve",
    "provider_call",
)

READ_ONLY_CAPABILITIES: frozenset[str] = frozenset(
    {
        "task_list",
        "task_show",
        "approval_list",
        "repo_status",
        "run_show",
    }
)

APPROVAL_REQUIRED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "approval_decide",
        "secret_resolve",
        "provider_call",
    }
)

RAW_TOKEN_ENV = "TASKMANAGEDAI_OPERATION_TOKEN"  # noqa: S105 - environment variable name, not a token value
REFRESH_TOKEN_ENV = "TASKMANAGEDAI_REFRESH_TOKEN"  # noqa: S105 - environment variable name, not a token value


class CapabilityTokenConfigError(ValueError):
    """Raised when local CLI auth config would persist raw secret material."""


def is_mutating_capability(capability: str) -> bool:
    return capability not in READ_ONLY_CAPABILITIES


def validate_capability_set(actions: Iterable[str]) -> tuple[str, ...]:
    values = tuple(actions)
    unknown = sorted(set(values) - set(ALL_CAPABILITIES))
    if unknown:
        raise CapabilityTokenConfigError(f"unknown CLI capabilities: {', '.join(unknown)}")
    if len(set(values)) != len(values):
        raise CapabilityTokenConfigError("CLI capabilities must not contain duplicates")
    return values


def resolve_operation_token(env: Mapping[str, str], *, token_override: str | None = None) -> str | None:
    if token_override:
        return token_override
    value = env.get(RAW_TOKEN_ENV)
    if value:
        return value
    return None


def compute_auth_context_hash(auth_method: str, credential_ref: str | None) -> str:
    material = f"{auth_method}:{credential_ref or ''}".encode()
    return hashlib.sha256(material).hexdigest()


def assert_profile_has_no_raw_token(profile_data: Mapping[str, object]) -> None:
    forbidden_keys = {
        "operation_token",
        "raw_operation_token",
        "bearer_token",
        "capability_token",
        "api_token",
        "access_token",
    }
    found: list[str] = []

    def visit(mapping: Mapping[str, object], prefix: str) -> None:
        for key, value in mapping.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in forbidden_keys:
                found.append(path)
            if isinstance(value, Mapping):
                visit(value, path)

    visit(profile_data, "")
    if found:
        raise CapabilityTokenConfigError(
            "profile must not persist raw operation token fields: " + ", ".join(sorted(found))
        )
