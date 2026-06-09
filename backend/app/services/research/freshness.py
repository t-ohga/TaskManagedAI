"""SP-032 (ADR-00052 R1 F-006 / F-009): freshness 再計算 (deterministic、read-only advisory)。

evidence の age から半減期 decay で [0,1] の freshness を算出する純関数。stored
``claims.freshness_score`` (source-provided) は変更しない。本 module は read-side advisory のみ。
"""

from __future__ import annotations

from datetime import UTC, datetime

HALF_LIFE_DAYS = 365.0
SECONDS_PER_DAY = 86400.0


def _to_utc(value: datetime) -> datetime:
    """aware UTC へ正規化。naive datetime は UTC とみなす (純関数の防御)。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def effective_at(published_at: datetime | None, retrieved_at: datetime | None) -> datetime | None:
    """evidence の effective timestamp = published_at ?? retrieved_at (両方欠如なら None)。"""
    chosen = published_at if published_at is not None else retrieved_at
    if chosen is None:
        return None
    return _to_utc(chosen)


def compute_freshness(
    published_at: datetime | None,
    retrieved_at: datetime | None,
    as_of: datetime,
) -> float | None:
    """単一 evidence の freshness を算出する。

    - effective_at = published_at ?? retrieved_at。両方欠如なら None。
    - age_days = max(0, (as_of - effective_at) 日数)。未来日付は age 0 → 1.0 (clamp)。
    - freshness = 0.5 ** (age_days / HALF_LIFE_DAYS)、clamp [0,1]。
    """
    eff = effective_at(published_at, retrieved_at)
    if eff is None:
        return None
    as_of_utc = _to_utc(as_of)
    age_seconds = (as_of_utc - eff).total_seconds()
    age_days = max(0.0, age_seconds / SECONDS_PER_DAY)
    freshness: float = 0.5 ** (age_days / HALF_LIFE_DAYS)
    return max(0.0, min(1.0, freshness))


def compute_claim_freshness(
    evidence_timestamps: list[tuple[datetime | None, datetime | None]],
    as_of: datetime,
) -> float | None:
    """claim の computed_freshness = supporting evidence の max(effective_at) を基準に decay。

    - 各 evidence の effective_at = published_at ?? retrieved_at。両方欠如の evidence は除外。
    - supporting evidence が 0 件 (または全除外) なら None。
    - 最も新しい effective_at (= 最小 age) を採用 → 最高 freshness。
    """
    effs = [
        eff
        for published_at, retrieved_at in evidence_timestamps
        if (eff := effective_at(published_at, retrieved_at)) is not None
    ]
    if not effs:
        return None
    newest = max(effs)
    return compute_freshness(newest, None, as_of)


__all__ = [
    "HALF_LIFE_DAYS",
    "compute_claim_freshness",
    "compute_freshness",
    "effective_at",
]
