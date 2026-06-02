"""A-7 (ADR-00045 R13): ticket write boundary の strict YMD due_date contract.

Pydantic v2 の `date | None` は lax coercion で datetime 文字列 / epoch を `date` に silent coerce する。
server-owned boundary (REST request + 内部 TicketCreate/Update) で full-match `YYYY-MM-DD` または null
のみ受理し、datetime / epoch / 非実在日 / junk suffix を fail-closed で reject することを固定する
(frontend strict-YMD all-surface 不変条件と trust boundary を揃える authoritative な強制点)。
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import BaseModel, ValidationError

from backend.app.api.tickets import TicketCreateRequest, TicketUpdateRequest
from backend.app.schemas.ticket import TicketCreate, TicketUpdate, coerce_strict_due_date

# server / version skew で送られうる non-YMD 入力 (全て reject されるべき)。
_MALFORMED_DUE_DATES: tuple[object, ...] = (
    "2026-06-01T00:00:00Z",  # datetime 文字列
    "2026-06-01T00:00:00",  # naive datetime 文字列
    1772323200,  # epoch int
    1772323200.0,  # epoch float
    "1772323200",  # epoch 数字文字列
    "2026-02-31",  # 非実在日
    "2026-13-01",  # 非実在月
    "2026-6-3",  # 非ゼロパディング
    "2026-06-01junk",  # junk suffix
    "2026/06/01",  # 区切り文字違い
    "",  # 空文字
)


def test_coerce_strict_due_date_accepts_none_and_valid_ymd() -> None:
    assert coerce_strict_due_date(None) is None
    assert coerce_strict_due_date("2026-06-01") == datetime.date(2026, 6, 1)
    # date オブジェクト (datetime でない) はそのまま通す。
    assert coerce_strict_due_date(datetime.date(2026, 6, 1)) == datetime.date(2026, 6, 1)


def test_coerce_strict_due_date_rejects_datetime_object() -> None:
    # datetime は date のサブクラスだが、時刻付き入力を date に潰さないため reject。
    with pytest.raises(ValueError, match="due_date"):
        coerce_strict_due_date(datetime.datetime(2026, 6, 1, 12, 0, 0))


@pytest.mark.parametrize("bad", _MALFORMED_DUE_DATES)
def test_coerce_strict_due_date_rejects_malformed(bad: object) -> None:
    with pytest.raises(ValueError, match="due_date"):
        coerce_strict_due_date(bad)


@pytest.mark.parametrize(
    "model",
    [TicketCreateRequest, TicketUpdateRequest, TicketCreate, TicketUpdate],
)
@pytest.mark.parametrize("bad", _MALFORMED_DUE_DATES)
def test_ticket_write_schemas_reject_malformed_due_date(
    model: type[BaseModel], bad: object
) -> None:
    # 全 ticket write schema (REST request + 内部 promotion) で同一の strict 契約を enforce する。
    payload: dict[str, object] = {"due_date": bad}
    # create 系は必須 field を満たす。
    if model in (TicketCreateRequest, TicketCreate):
        payload["slug"] = "valid-slug"
        payload["title"] = "Valid Title"
    if model is TicketCreate:
        payload["created_by_actor_id"] = "00000000-0000-4000-8000-000000000001"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "model",
    [TicketCreateRequest, TicketUpdateRequest, TicketCreate, TicketUpdate],
)
def test_ticket_write_schemas_accept_valid_ymd_and_null(model: type[BaseModel]) -> None:
    base: dict[str, object] = {}
    if model in (TicketCreateRequest, TicketCreate):
        base["slug"] = "valid-slug"
        base["title"] = "Valid Title"
    if model is TicketCreate:
        base["created_by_actor_id"] = "00000000-0000-4000-8000-000000000001"

    valid = model.model_validate({**base, "due_date": "2026-06-30"})
    assert valid.model_dump()["due_date"] == datetime.date(2026, 6, 30)
    cleared = model.model_validate({**base, "due_date": None})
    assert cleared.model_dump()["due_date"] is None
