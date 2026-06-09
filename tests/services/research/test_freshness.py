from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.app.services.research.freshness import (
    HALF_LIFE_DAYS,
    compute_claim_freshness,
    compute_freshness,
    effective_at,
)

_AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def test_age_zero_is_one() -> None:
    assert compute_freshness(_AS_OF, None, _AS_OF) == pytest.approx(1.0)


def test_half_life_is_half() -> None:
    published = _AS_OF - timedelta(days=HALF_LIFE_DAYS)
    assert compute_freshness(published, None, _AS_OF) == pytest.approx(0.5, abs=1e-9)


def test_two_half_lives_is_quarter() -> None:
    published = _AS_OF - timedelta(days=2 * HALF_LIFE_DAYS)
    assert compute_freshness(published, None, _AS_OF) == pytest.approx(0.25, abs=1e-9)


def test_future_date_clamps_to_one() -> None:
    future = _AS_OF + timedelta(days=100)
    assert compute_freshness(future, None, _AS_OF) == pytest.approx(1.0)


def test_large_age_approaches_zero() -> None:
    ancient = _AS_OF - timedelta(days=100 * 365)
    value = compute_freshness(ancient, None, _AS_OF)
    assert value is not None
    assert 0.0 <= value < 1e-6


def test_both_timestamps_missing_returns_none() -> None:
    assert compute_freshness(None, None, _AS_OF) is None


def test_falls_back_to_retrieved_at_when_no_published() -> None:
    retrieved = _AS_OF - timedelta(days=HALF_LIFE_DAYS)
    assert compute_freshness(None, retrieved, _AS_OF) == pytest.approx(0.5, abs=1e-9)


def test_published_at_preferred_over_retrieved_at() -> None:
    published = _AS_OF  # fresh
    retrieved = _AS_OF - timedelta(days=10 * 365)  # ancient
    assert compute_freshness(published, retrieved, _AS_OF) == pytest.approx(1.0)


def test_naive_datetime_treated_as_utc() -> None:
    naive = datetime(2025, 1, 1)  # noqa: DTZ001 — naive 入力の防御を検証
    aware = datetime(2025, 1, 1, tzinfo=UTC)
    assert compute_freshness(naive, None, _AS_OF) == compute_freshness(aware, None, _AS_OF)


def test_aware_non_utc_normalized() -> None:
    jst = timezone(timedelta(hours=9))
    published_jst = datetime(2025, 1, 1, 9, 0, tzinfo=jst)
    published_utc = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)  # 同時刻
    assert compute_freshness(published_jst, None, _AS_OF) == compute_freshness(
        published_utc, None, _AS_OF
    )


def test_effective_at_prefers_published() -> None:
    pub = datetime(2025, 6, 1, tzinfo=UTC)
    ret = datetime(2025, 1, 1, tzinfo=UTC)
    assert effective_at(pub, ret) == pub
    assert effective_at(None, ret) == ret
    assert effective_at(None, None) is None


def test_claim_freshness_uses_newest_supporting_evidence() -> None:
    timestamps = [
        (_AS_OF - timedelta(days=10 * 365), None),  # ancient
        (_AS_OF - timedelta(days=HALF_LIFE_DAYS), None),  # half-life
    ]
    # newest = half-life → 0.5
    assert compute_claim_freshness(timestamps, _AS_OF) == pytest.approx(0.5, abs=1e-9)


def test_claim_freshness_excludes_evidence_without_timestamps() -> None:
    timestamps = [(None, None), (_AS_OF, None)]
    assert compute_claim_freshness(timestamps, _AS_OF) == pytest.approx(1.0)


def test_claim_freshness_none_when_no_usable_evidence() -> None:
    assert compute_claim_freshness([], _AS_OF) is None
    assert compute_claim_freshness([(None, None), (None, None)], _AS_OF) is None
