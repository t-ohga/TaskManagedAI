"""A-7 (ADR-00045): reminder bucket 純粋関数 + today_jst 基準日 helper の unit test.

plan-review R2 F-001: `compute_reminder_bucket(due, ref, threshold)` が window 外を None
判定できること (上限 off-by-one)。R1/R2 F-002: `today_jst` が JST 暦日 (UTC でない) を返し、
JST 深夜 0 時境界を決定的に切り替えること。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.domain.reminders import (
    REMINDER_UPCOMING_WINDOW_DAYS,
    compute_reminder_bucket,
    today_jst,
)

_JST = ZoneInfo("Asia/Tokyo")
_REF = date(2026, 6, 2)


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        # overdue (下限なし)
        (date(2025, 1, 1), "overdue"),
        (date(2026, 5, 1), "overdue"),
        (_REF - timedelta(days=1), "overdue"),
        # due_today
        (_REF, "due_today"),
        # upcoming (today < due <= today + threshold)
        (_REF + timedelta(days=1), "upcoming"),
        (_REF + timedelta(days=REMINDER_UPCOMING_WINDOW_DAYS), "upcoming"),
        # window 外 (due > today + threshold) -> None
        (_REF + timedelta(days=REMINDER_UPCOMING_WINDOW_DAYS + 1), None),
        (_REF + timedelta(days=365), None),
    ],
)
def test_compute_reminder_bucket(due: date, expected: str | None) -> None:
    assert compute_reminder_bucket(due, _REF) == expected


def test_compute_reminder_bucket_upper_boundary_off_by_one() -> None:
    # 上限境界: today + threshold は upcoming、today + threshold + 1 は None (R2 F-001 必須)。
    on_edge = _REF + timedelta(days=REMINDER_UPCOMING_WINDOW_DAYS)
    over_edge = _REF + timedelta(days=REMINDER_UPCOMING_WINDOW_DAYS + 1)
    assert compute_reminder_bucket(on_edge, _REF) == "upcoming"
    assert compute_reminder_bucket(over_edge, _REF) is None


def test_compute_reminder_bucket_respects_custom_threshold() -> None:
    # threshold を変えると window 上限が連動する (SQL prefilter と同一値を渡す契約)。
    due = _REF + timedelta(days=3)
    assert compute_reminder_bucket(due, _REF, threshold_days=3) == "upcoming"
    assert compute_reminder_bucket(due, _REF, threshold_days=2) is None


def test_today_jst_uses_jst_calendar_date_not_utc() -> None:
    # JST 23:59:59 と翌 00:00:00 で暦日が切り替わる (深夜境界、F-002 必須)。
    assert today_jst(datetime(2026, 6, 2, 23, 59, 59, tzinfo=_JST)) == date(2026, 6, 2)
    assert today_jst(datetime(2026, 6, 3, 0, 0, 0, tzinfo=_JST)) == date(2026, 6, 3)


def test_today_jst_converts_utc_instant_to_jst_date() -> None:
    # 2026-06-02 15:30 UTC = 2026-06-03 00:30 JST -> JST 暦日 (UTC の 06-02 ではない)。
    utc_instant = datetime(2026, 6, 2, 15, 30, 0, tzinfo=UTC)
    assert today_jst(utc_instant) == date(2026, 6, 3)
    # 2026-06-02 14:30 UTC = 2026-06-02 23:30 JST -> まだ 06-02。
    assert today_jst(datetime(2026, 6, 2, 14, 30, 0, tzinfo=UTC)) == date(2026, 6, 2)
