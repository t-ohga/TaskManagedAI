from __future__ import annotations

from typing import Literal

MemoryRecordKind = Literal[
    "manual_user",
    "manual_agent",
    "auto_completion",
    "auto_failure",
    "auto_review_finding",
]

ALL_MEMORY_RECORD_KINDS: tuple[MemoryRecordKind, ...] = (
    "manual_user",
    "manual_agent",
    "auto_completion",
    "auto_failure",
    "auto_review_finding",
)

MEMORY_RECORD_KINDS: frozenset[MemoryRecordKind] = frozenset(ALL_MEMORY_RECORD_KINDS)

__all__ = ["ALL_MEMORY_RECORD_KINDS", "MEMORY_RECORD_KINDS", "MemoryRecordKind"]
