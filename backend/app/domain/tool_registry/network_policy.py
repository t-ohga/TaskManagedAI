from __future__ import annotations

from typing import Final, Literal, get_args

NetworkAccessMode = Literal["none", "allowlist", "internet"]
ToolTransport = Literal["local", "stdio"]
ToolAuthMode = Literal["none", "env_ref"]
ToolTrustTier = Literal["official", "self_hosted", "third_party", "experimental"]
PayloadDataClass = Literal["public", "internal", "confidential", "pii"]

ALL_NETWORK_ACCESS_MODES: Final[frozenset[str]] = frozenset(
    {"none", "allowlist", "internet"}
)
ALL_TOOL_TRANSPORTS: Final[frozenset[str]] = frozenset({"local", "stdio"})
ALL_TOOL_AUTH_MODES: Final[frozenset[str]] = frozenset({"none", "env_ref"})
ALL_TOOL_TRUST_TIERS: Final[frozenset[str]] = frozenset(
    {"official", "self_hosted", "third_party", "experimental"}
)
ALL_PAYLOAD_DATA_CLASSES: Final[frozenset[str]] = frozenset(
    {"public", "internal", "confidential", "pii"}
)
DATA_CLASS_ORDER: Final[dict[PayloadDataClass, int]] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "pii": 3,
}
DEFAULT_DENY_ONLY_TOOL_KEYS: Final[tuple[str, str]] = ("web_fetch", "docs_search")

_LITERAL_CHECKS: Final[tuple[tuple[str, frozenset[str], frozenset[str]], ...]] = (
    (
        "NetworkAccessMode",
        frozenset(get_args(NetworkAccessMode)),
        ALL_NETWORK_ACCESS_MODES,
    ),
    ("ToolTransport", frozenset(get_args(ToolTransport)), ALL_TOOL_TRANSPORTS),
    ("ToolAuthMode", frozenset(get_args(ToolAuthMode)), ALL_TOOL_AUTH_MODES),
    ("ToolTrustTier", frozenset(get_args(ToolTrustTier)), ALL_TOOL_TRUST_TIERS),
    (
        "PayloadDataClass",
        frozenset(get_args(PayloadDataClass)),
        ALL_PAYLOAD_DATA_CLASSES,
    ),
)
for _name, _literal_values, _constant_values in _LITERAL_CHECKS:
    if _literal_values != _constant_values:
        raise AssertionError(
            f"{_name} Literal and constant drift: "
            f"Literal={sorted(_literal_values)}, constant={sorted(_constant_values)}"
        )


__all__ = [
    "ALL_NETWORK_ACCESS_MODES",
    "ALL_PAYLOAD_DATA_CLASSES",
    "ALL_TOOL_AUTH_MODES",
    "ALL_TOOL_TRANSPORTS",
    "ALL_TOOL_TRUST_TIERS",
    "DATA_CLASS_ORDER",
    "DEFAULT_DENY_ONLY_TOOL_KEYS",
    "NetworkAccessMode",
    "PayloadDataClass",
    "ToolAuthMode",
    "ToolTransport",
    "ToolTrustTier",
]
