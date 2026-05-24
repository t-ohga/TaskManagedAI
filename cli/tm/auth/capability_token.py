from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

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


KeyringGetter = Callable[[str, str], str | None]
SopsDecryptor = Callable[[Path], Mapping[str, object]]


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


def resolve_operation_token(
    env: Mapping[str, str],
    *,
    token_override: str | None = None,
    auth_method: str = "env",
    credential_ref: str | None = None,
    keyring_getter: KeyringGetter | None = None,
    sops_decryptor: SopsDecryptor | None = None,
) -> str | None:
    if token_override:
        return token_override
    value = env.get(RAW_TOKEN_ENV)
    if value:
        return value
    if auth_method == "env":
        env_name = credential_ref or REFRESH_TOKEN_ENV
        return env.get(env_name) or None
    if auth_method == "keyring":
        service, account = _parse_keyring_ref(credential_ref)
        getter = keyring_getter or _default_keyring_getter
        return getter(service, account)
    if auth_method == "sops":
        path, key_path = _parse_sops_ref(credential_ref)
        decryptor = sops_decryptor or _default_sops_decryptor
        return _resolve_sops_key(decryptor(path), key_path)
    if auth_method == "plain":
        raise CapabilityTokenConfigError("auth_method=plain is rejected by the CLI profile loader")
    raise CapabilityTokenConfigError(f"unsupported auth_method: {auth_method}")


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


def _parse_keyring_ref(credential_ref: str | None) -> tuple[str, str]:
    if credential_ref is None or not credential_ref.strip():
        raise CapabilityTokenConfigError("keyring auth_method requires refresh_credential_ref")
    if "/" in credential_ref:
        service, account = credential_ref.split("/", 1)
    elif ":" in credential_ref:
        service, account = credential_ref.split(":", 1)
    else:
        raise CapabilityTokenConfigError("keyring refresh_credential_ref must be service/account")
    if not service or not account:
        raise CapabilityTokenConfigError("keyring refresh_credential_ref must include service and account")
    return service, account


def _default_keyring_getter(service: str, account: str) -> str | None:
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CapabilityTokenConfigError(
            "keyring auth_method requires the optional keyring package or an injected getter"
        ) from exc
    value = keyring.get_password(service, account)
    return str(value) if value else None


def _parse_sops_ref(credential_ref: str | None) -> tuple[Path, tuple[str, ...]]:
    if credential_ref is None or not credential_ref.strip():
        raise CapabilityTokenConfigError("sops auth_method requires refresh_credential_ref")
    path_text, separator, key_text = credential_ref.partition("#")
    if not path_text:
        raise CapabilityTokenConfigError("sops refresh_credential_ref must include a file path")
    key_path = tuple(part for part in (key_text if separator else "operation_token").split(".") if part)
    if not key_path:
        raise CapabilityTokenConfigError("sops refresh_credential_ref key path must not be empty")
    return Path(path_text), key_path


def _default_sops_decryptor(path: Path) -> Mapping[str, object]:
    sops_path = shutil.which("sops")
    if sops_path is None:
        raise CapabilityTokenConfigError("sops auth_method requires the sops executable")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed sops argv from PATH resolution, no shell
            [sops_path, "--decrypt", "--output-type", "json", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise CapabilityTokenConfigError(f"failed to decrypt sops credential ref: {path}") from exc
    parsed = json.loads(completed.stdout)
    if not isinstance(parsed, dict):
        raise CapabilityTokenConfigError("sops decrypted payload must be a JSON object")
    return parsed


def _resolve_sops_key(payload: Mapping[str, object], key_path: tuple[str, ...]) -> str | None:
    current: object = payload
    for key in key_path:
        if not isinstance(current, Mapping) or key not in current:
            raise CapabilityTokenConfigError("sops credential key path not found: " + ".".join(key_path))
        current = current[key]
    if current is None:
        return None
    if not isinstance(current, str):
        raise CapabilityTokenConfigError("sops credential key must resolve to a string")
    return current or None
