from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

PayloadDataClass = Literal["public", "internal", "confidential", "pii"]

ALL_PAYLOAD_DATA_CLASSES: tuple[PayloadDataClass, ...] = (
    "public",
    "internal",
    "confidential",
    "pii",
)

DATA_CLASS_ORDINAL: Mapping[PayloadDataClass, int] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "pii": 3,
}

__all__ = [
    "ALL_PAYLOAD_DATA_CLASSES",
    "DATA_CLASS_ORDINAL",
    "PayloadDataClass",
]

