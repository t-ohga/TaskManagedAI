"""A-7 期限リマインダーの bucket 判定 + 基準日 helper (ADR-00045).

純粋なドメインロジックのみを持つ (DB / FastAPI 非依存)。reminder endpoint と date_context
endpoint がこの module の `compute_reminder_bucket` / `_today_jst` / 定数を共有することで、
bucket 判定と "today" の権威を 1 箇所に集約する (plan-review R1 F-002 / R2 F-001)。

不変条件:
- `due_date` は ADR-00034 の暦日 (`date`、timezone なし)。"today" も固定 timezone (Asia/Tokyo) の暦日。
- bucket 判定は `compute_reminder_bucket(due_date, reference_date, threshold_days)` が正本。
  SQL prefilter (`due_date <= reference_date + threshold_days`) に依存せず、window 外を `None`
  で判定できる (R2 F-001)。
- frontend `dueDateBucket` (`frontend/lib/domain/due-date.ts`) は同一 signature / 同一 4 値を返す。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

# upcoming (期限近接) とみなす窓 (日数)。reference_date + この日数 までを upcoming とする。
# 変更は ADR-00045 の更新を要する (backend 固定、caller 入力不可)。
REMINDER_UPCOMING_WINDOW_DAYS = 7

# bucket ごとに独立して返す items の上限 (plan-review R1 F-001)。全 bucket 横断の単一 LIMIT は
# 採らない (overdue が due_today / upcoming の表示枠を枯渇させる silent truncation を防ぐ)。
REMINDER_BUCKET_LIST_LIMIT = 50

# 期限の暦日を解釈する timezone。due_date は時刻概念のない暦日のため、"today" も JST 暦日で固定する。
_JST = ZoneInfo("Asia/Tokyo")

ReminderBucketName = Literal["overdue", "due_today", "upcoming"]


def today_jst(now: datetime | None = None) -> date:
    """Asia/Tokyo の暦日 ("today") を返す。

    reminder endpoint と date_context endpoint が共有する "today" の唯一権威 (R1 F-002 / R2 F-002)。
    ``now`` は test 用の注入点 (省略時は現在時刻)。JST 深夜 0 時境界を決定的に検証できる。
    """
    instant = now if now is not None else datetime.now(tz=_JST)
    return instant.astimezone(_JST).date()


def compute_reminder_bucket(
    due_date: date,
    reference_date: date,
    threshold_days: int = REMINDER_UPCOMING_WINDOW_DAYS,
) -> ReminderBucketName | None:
    """due_date を基準日 + 閾値から bucket 分類する (bucket 判定の正本、R2 F-001)。

    - ``due_date < reference_date`` -> ``"overdue"`` (下限なし、古い超過も超過)
    - ``due_date == reference_date`` -> ``"due_today"``
    - ``reference_date < due_date <= reference_date + threshold_days`` -> ``"upcoming"``
    - ``due_date > reference_date + threshold_days`` -> ``None`` (window 外、reminder 対象外)

    SQL の prefilter と同一 ``threshold_days`` を渡すこと。frontend ``dueDateBucket`` と同じ判定。
    """
    days_until = (due_date - reference_date).days
    if days_until < 0:
        return "overdue"
    if days_until == 0:
        return "due_today"
    if days_until <= threshold_days:
        return "upcoming"
    return None


__all__ = [
    "REMINDER_BUCKET_LIST_LIMIT",
    "REMINDER_UPCOMING_WINDOW_DAYS",
    "ReminderBucketName",
    "compute_reminder_bucket",
    "today_jst",
]
