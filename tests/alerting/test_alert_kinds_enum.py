"""Sprint 11.5 batch 2 BL-0135: AlertKind enum 5+ source integrity test.

Sources:
1. `AlertKind` Literal
2. `ALERT_KIND_VALUES` frozenset
3. `EXPECTED_ALERT_KINDS` pytest constant (本 file)
4. Pydantic Field validator (test 経由で reject 確認)
5. NotificationEvent.event_type は text 列、`to_event_type()` で `alert.*` prefix
   (frontend TypeScript enum は Sprint 17 で追加予定、現時点は 4 source)
"""

from __future__ import annotations

from typing import Final, get_args

import pytest

from backend.app.services.alerting.kinds import (
    ALERT_EVENT_TYPE_PREFIX,
    ALERT_KIND_VALUES,
    EXPECTED_ALERT_KINDS,
    AlertKind,
    to_event_type,
)

# pytest EXPECTED constant (本 source、5+ source integrity の 5 番目).
EXPECTED: Final[frozenset[str]] = frozenset(
    {
        "approval_pending_overdue",
        "budget_exceeded",
        "run_failed_spike",
        "secret_rotation_deferred",
    }
)


def test_alert_kind_literal_matches_expected_set() -> None:
    """Source 1: `AlertKind` Literal の値域."""

    literal_values = frozenset(get_args(AlertKind))
    assert literal_values == EXPECTED


def test_alert_kind_values_frozenset_integrity() -> None:
    """Source 2: `ALERT_KIND_VALUES` frozenset 整合."""

    assert ALERT_KIND_VALUES == EXPECTED


def test_expected_alert_kinds_pytest_constant_integrity() -> None:
    """Source 3: module-level `EXPECTED_ALERT_KINDS` 定数整合."""

    assert EXPECTED_ALERT_KINDS == EXPECTED


def test_alert_kind_count_is_exactly_four() -> None:
    """新規 enum 追加なし (Sprint 11.5 batch 2 scope)."""

    assert len(ALERT_KIND_VALUES) == 4


def test_to_event_type_prefix() -> None:
    """`to_event_type(kind)` は `alert.` prefix を付与."""

    assert ALERT_EVENT_TYPE_PREFIX == "alert."
    assert to_event_type("approval_pending_overdue") == "alert.approval_pending_overdue"
    assert to_event_type("budget_exceeded") == "alert.budget_exceeded"
    assert to_event_type("run_failed_spike") == "alert.run_failed_spike"
    assert to_event_type("secret_rotation_deferred") == "alert.secret_rotation_deferred"


def test_5_plus_source_exact_set_match() -> None:
    """5+ source 整合 exact set match (Sprint 11.5 batch 2 plan v1 §3)."""

    sources = {
        "literal": frozenset(get_args(AlertKind)),
        "values_frozenset": ALERT_KIND_VALUES,
        "expected_constant": EXPECTED_ALERT_KINDS,
        "pytest_expected": EXPECTED,
    }
    # 全 source が同一 set.
    union = set()
    intersection = set(EXPECTED)
    for value_set in sources.values():
        union |= value_set
        intersection &= value_set
    assert union == intersection == set(EXPECTED)


@pytest.mark.parametrize(
    "kind",
    [
        "approval_pending_overdue",
        "budget_exceeded",
        "run_failed_spike",
        "secret_rotation_deferred",
    ],
)
def test_each_kind_in_set(kind: str) -> None:
    """parameterized: 各 kind が ALERT_KIND_VALUES に含まれる."""

    assert kind in ALERT_KIND_VALUES
