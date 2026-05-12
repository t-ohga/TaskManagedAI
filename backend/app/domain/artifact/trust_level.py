from __future__ import annotations

from typing import Literal

TrustLevel = Literal[
    "untrusted_content",
    "validated_artifact",
    "trusted_instruction",
]

ALL_TRUST_LEVELS: tuple[TrustLevel, ...] = (
    "untrusted_content",
    "validated_artifact",
    "trusted_instruction",
)

TRUST_LEVELS: frozenset[TrustLevel] = frozenset(ALL_TRUST_LEVELS)

_TRUST_LEVEL_ORDINAL: dict[TrustLevel, int] = {
    "untrusted_content": 0,
    "validated_artifact": 1,
    "trusted_instruction": 2,
}


def trust_level_ordinal(level: TrustLevel) -> int:
    if level not in TRUST_LEVELS:
        raise ValueError(f"unknown trust_level: {level!r}")
    return _TRUST_LEVEL_ORDINAL[level]


__all__ = [
    "ALL_TRUST_LEVELS",
    "TRUST_LEVELS",
    "TrustLevel",
    "trust_level_ordinal",
]
