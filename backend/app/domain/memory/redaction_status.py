from __future__ import annotations

from typing import Literal

MemoryRedactionStatus = Literal["redacted", "raw_with_canary_scan_passed"]

ALL_MEMORY_REDACTION_STATUSES: tuple[MemoryRedactionStatus, ...] = (
    "redacted",
    "raw_with_canary_scan_passed",
)

MEMORY_REDACTION_STATUSES: frozenset[MemoryRedactionStatus] = frozenset(
    ALL_MEMORY_REDACTION_STATUSES
)

__all__ = [
    "ALL_MEMORY_REDACTION_STATUSES",
    "MEMORY_REDACTION_STATUSES",
    "MemoryRedactionStatus",
]
