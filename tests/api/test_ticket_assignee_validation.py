"""A-6 (ADR-00046): assignee 検証ロジックの unit test (no-DB).

- `TicketRepository._assert_assignee_human`: DB から resolve した actor_type が 'human' のみ許可、
  非 human / 不在 (cross-tenant / nonexistent) は `AssigneeNotAssignableError`。caller 申告でなく
  DB resolve であること (server-owned-boundary)。
- `_is_assignee_fk_violation`: assignee FK 制約違反のみ True、slug unique 等の他制約は False
  (R1 F-004 backstop が他制約を誤写像しない)。

full な create/update deny (REST + MCP + research adapter) と audit は DB-gated test
(TASKMANAGEDAI_RUN_DB_TESTS=1、CI Compose) でカバーする。
"""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.tickets import _is_assignee_fk_violation
from backend.app.repositories.ticket import (
    AssigneeNotAssignableError,
    TicketRepository,
)


class _ScalarSession:
    """`_assert_assignee_human` が呼ぶ session.scalar(select(Actor.actor_type)) を固定値で返す fake."""

    def __init__(self, actor_type: str | None) -> None:
        self._actor_type = actor_type
        self.scalar_calls = 0

    async def scalar(self, statement: object, *args: object, **kwargs: object) -> str | None:
        self.scalar_calls += 1
        return self._actor_type


def _repo(actor_type: str | None) -> tuple[TicketRepository, _ScalarSession]:
    session = _ScalarSession(actor_type)
    return TicketRepository(cast(AsyncSession, session)), session


def test_assert_assignee_human_allows_human() -> None:
    repo, session = _repo("human")
    # human はそのまま許可 (raise しない)。DB resolve した値で判定していること。
    asyncio.run(repo._assert_assignee_human(1, uuid4()))
    assert session.scalar_calls == 1


@pytest.mark.parametrize(
    "actor_type",
    ["agent", "provider", "service", "github_app"],
)
def test_assert_assignee_human_rejects_non_human(actor_type: str) -> None:
    repo, _ = _repo(actor_type)
    with pytest.raises(AssigneeNotAssignableError):
        asyncio.run(repo._assert_assignee_human(1, uuid4()))


def test_assert_assignee_human_rejects_missing_actor() -> None:
    # actor 不在 / 別 tenant は scalar() が None を返す → fail-closed で reject (FK IntegrityError 500
    # に至る前に 422 化される)。
    repo, _ = _repo(None)
    with pytest.raises(AssigneeNotAssignableError):
        asyncio.run(repo._assert_assignee_human(1, uuid4()))


class _Orig:
    def __init__(self, constraint_name: str | None) -> None:
        self.constraint_name = constraint_name


class _FakeIntegrityError:
    def __init__(self, constraint_name: str | None) -> None:
        self.orig = _Orig(constraint_name)


def test_is_assignee_fk_violation_true_for_assignee_constraint() -> None:
    exc = cast(IntegrityError, _FakeIntegrityError("tickets_assignee_actor_fkey"))
    assert _is_assignee_fk_violation(exc) is True


@pytest.mark.parametrize(
    "constraint",
    [
        "tickets_uq_tenant_project_slug",  # slug unique は 422-assignee に誤写像しない
        "tickets_created_by_actor_fkey",  # 別 actor FK
        "tickets_project_fkey",
        None,
    ],
)
def test_is_assignee_fk_violation_false_for_other_constraints(
    constraint: str | None,
) -> None:
    exc = cast(IntegrityError, _FakeIntegrityError(constraint))
    assert _is_assignee_fk_violation(exc) is False


def test_is_assignee_fk_violation_false_when_orig_missing() -> None:
    class _NoOrig:
        pass

    exc = cast(IntegrityError, _NoOrig())
    assert _is_assignee_fk_violation(exc) is False
