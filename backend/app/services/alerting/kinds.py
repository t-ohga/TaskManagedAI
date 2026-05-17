"""AlertKind enum (Sprint 11.5 batch 2 BL-0135、5+ source enum integrity).

5+ source:
1. Python Literal (`AlertKind`)
2. `ALERT_KIND_VALUES` frozenset
3. `EXPECTED_ALERT_KINDS` pytest constant (test 側で import)
4. Pydantic Field validator (evaluator.py / schema 内で `pattern=`)
5. NotificationEvent.event_type は text 列のため DB CHECK 不要 (frontend TypeScript enum は
   Sprint 17 notification UI で追加予定、その時点で 5 source 達成)
"""

from __future__ import annotations

from typing import Final, Literal

AlertKind = Literal[
    "approval_pending_overdue",
    "budget_exceeded",
    "run_failed_spike",
    "secret_rotation_deferred",
]

ALERT_KIND_VALUES: Final[frozenset[str]] = frozenset(
    {
        "approval_pending_overdue",
        "budget_exceeded",
        "run_failed_spike",
        "secret_rotation_deferred",
    }
)

# pytest 用 EXPECTED constant (5+ source 整合 verify).
EXPECTED_ALERT_KINDS: Final[frozenset[str]] = frozenset(ALERT_KIND_VALUES)


# 各 alert kind の event_type prefix (NotificationEvent.event_type に直接 set).
# `alert.*` prefix で他 event_type (approval_pending 等) と name 衝突防止.
ALERT_EVENT_TYPE_PREFIX: Final[str] = "alert."


def to_event_type(kind: AlertKind) -> str:
    """`AlertKind` を NotificationEvent.event_type 文字列に変換."""

    return f"{ALERT_EVENT_TYPE_PREFIX}{kind}"


__all__ = [
    "ALERT_EVENT_TYPE_PREFIX",
    "ALERT_KIND_VALUES",
    "AlertKind",
    "EXPECTED_ALERT_KINDS",
    "to_event_type",
]
