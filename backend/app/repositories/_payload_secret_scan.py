"""共通 raw secret scanner module (Sprint 4 Batch 1 / Batch 2 共有).

F-002 (Batch 2 R2): AgentRunEvent / Artifact / ContextSnapshot で同 18 prohibited
keys + 8 regex pattern + recursive + max_depth + visited set を使う。drift 防止。
"""

from __future__ import annotations

import re
from typing import Any

_PROHIBITED_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "api_token",
        "raw_secret",
        "secret",
        "secret_value",
        "private_key",
        "auth_token",
        "bearer_token",
        "capability_token",
        "capability_token_value",
        "provider_key",
        "github_installation_token",
        "github_app_private_key",
        "tailscale_auth_key",
        "sops_age_key",
        "age_private_key",
        "canary_value",
        "raw_canary",
    }
)

_RAW_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github_installation_token", re.compile(r"ghs_[A-Za-z0-9]{20,}")),
    ("github_oauth_token", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("github_personal_token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("tailscale_auth_key", re.compile(r"tskey-[a-z0-9]{16,}-[a-z0-9]{16,}")),
    ("age_private_key", re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{50,}")),
    ("pem_private_key", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
)

_DEFAULT_MAX_DEPTH = 32


def assert_no_raw_secret(
    obj: Any,
    *,
    path: str = "$",
    max_depth: int = _DEFAULT_MAX_DEPTH,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> None:
    """payload を recursive に raw secret pattern + prohibited key scan。

    Sprint 4 Batch 1 / Batch 2 共通実装。AgentRunEvent / Artifact / ContextSnapshot
    全体で同一 18 key + 8 regex pattern を使う (drift 防止)。

    Raises:
        ValueError: prohibited key, raw secret pattern, max_depth 超過, 循環参照
    """

    if _seen is None:
        _seen = set()
    if _depth > max_depth:
        raise ValueError(
            f"payload exceeds max_depth={max_depth} at {path}; "
            "payload must be acyclic JSON-serializable with bounded depth"
        )

    if isinstance(obj, dict):
        oid = id(obj)
        if oid in _seen:
            raise ValueError(f"payload has cyclic reference at {path}")
        _seen.add(oid)
        try:
            for k, v in obj.items():
                if not isinstance(k, str):
                    raise ValueError(
                        f"payload contains non-string key at {path} "
                        f"(type={type(k).__name__})"
                    )
                if k in _PROHIBITED_PAYLOAD_KEYS:
                    raise ValueError(
                        "payload contains prohibited key "
                        f"(prohibited payload key) at {path}.{k!r}"
                    )
                for hit_kind, regex in _RAW_SECRET_PATTERNS:
                    if regex.search(k):
                        raise ValueError(
                            "payload key matches raw secret pattern "
                            f"({hit_kind!r}) at {path} (key redacted)"
                        )
                assert_no_raw_secret(
                    v,
                    path=f"{path}.{k}",
                    max_depth=max_depth,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
        finally:
            _seen.discard(oid)
    elif isinstance(obj, (list, tuple)):
        oid = id(obj)
        if oid in _seen:
            raise ValueError(f"payload has cyclic reference at {path}")
        _seen.add(oid)
        try:
            for i, item in enumerate(obj):
                assert_no_raw_secret(
                    item,
                    path=f"{path}[{i}]",
                    max_depth=max_depth,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
        finally:
            _seen.discard(oid)
    elif isinstance(obj, str):
        for hit_kind, regex in _RAW_SECRET_PATTERNS:
            if regex.search(obj):
                raise ValueError(
                    "payload value matches raw secret pattern "
                    f"({hit_kind!r}) at {path}"
                )
    elif obj is None or isinstance(obj, (int, float, bool)):
        pass
    else:
        raise ValueError(
            f"payload contains non-JSON-serializable type at {path} "
            f"(type={type(obj).__name__})"
        )


__all__ = [
    "_PROHIBITED_PAYLOAD_KEYS",
    "_RAW_SECRET_PATTERNS",
    "assert_no_raw_secret",
]

