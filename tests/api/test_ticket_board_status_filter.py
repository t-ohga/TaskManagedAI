"""ADR-00054: ticket board の status 絞り込み helper (`apply_board_status_filter`) の pure unit test。

DB/HTTP 非依存 (in-memory Ticket を構築して filter logic のみ検証)。precedence (status exact >
exclude_cancelled)、中止除外、非破壊 default を固定する。HTTP-level の total_unfiltered / 404 regression /
end-to-end は DB-gated integration test (tests/api/test_tickets_api.py、TASKMANAGEDAI_RUN_DB_TESTS=1) で検証。
"""

from __future__ import annotations

from backend.app.api.tickets import apply_board_status_filter
from backend.app.db.models.ticket import Ticket


def _ticket(status: str) -> Ticket:
    # transient (session 非結合) な ORM インスタンス。helper は .status のみ参照するため DB 不要。
    return Ticket(status=status)


def test_status_exact_filter() -> None:
    tickets = [_ticket("open"), _ticket("closed"), _ticket("cancelled")]
    result = apply_board_status_filter(
        tickets, ticket_status="closed", exclude_cancelled=False
    )
    assert [t.status for t in result] == ["closed"]


def test_exclude_cancelled_removes_only_cancelled() -> None:
    tickets = [_ticket("open"), _ticket("in_progress"), _ticket("cancelled")]
    result = apply_board_status_filter(
        tickets, ticket_status=None, exclude_cancelled=True
    )
    assert [t.status for t in result] == ["open", "in_progress"]


def test_status_takes_precedence_over_exclude_cancelled() -> None:
    # status=cancelled は exclude_cancelled=True でも勝つ (StatusFilter=中止 で証跡参照できる)。
    tickets = [_ticket("open"), _ticket("cancelled")]
    result = apply_board_status_filter(
        tickets, ticket_status="cancelled", exclude_cancelled=True
    )
    assert [t.status for t in result] == ["cancelled"]


def test_no_param_returns_all_unchanged() -> None:
    # param なし (status=None, exclude_cancelled=False) は従来どおり全 status (非破壊)。
    tickets = [_ticket("open"), _ticket("cancelled"), _ticket("closed")]
    result = apply_board_status_filter(
        tickets, ticket_status=None, exclude_cancelled=False
    )
    assert [t.status for t in result] == ["open", "cancelled", "closed"]


def test_status_filter_empty_result() -> None:
    # 該当 0 件 (例 blocked が無い) でも例外なく空を返す。
    tickets = [_ticket("open"), _ticket("closed")]
    result = apply_board_status_filter(
        tickets, ticket_status="blocked", exclude_cancelled=False
    )
    assert result == []
