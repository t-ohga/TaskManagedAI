from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.repositories.policy_decision import PolicyDecisionRepository


class _DummySession:
    pass


@pytest.mark.asyncio
async def test_policy_decision_repository_update_raises_not_implemented() -> None:
    repo = PolicyDecisionRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="append-only"):
        await repo.update(tenant_id=1, id=uuid4(), payload={})


@pytest.mark.asyncio
async def test_policy_decision_repository_delete_raises_not_implemented() -> None:
    repo = PolicyDecisionRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="append-only"):
        await repo.delete(tenant_id=1, id=uuid4())


def test_policy_decision_repository_statement_for_update_raises() -> None:
    repo = PolicyDecisionRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="statement_for_update"):
        repo.statement_for_update(tenant_id=1, id=uuid4(), payload={})


def test_policy_decision_repository_statement_for_delete_raises() -> None:
    repo = PolicyDecisionRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="statement_for_delete"):
        repo.statement_for_delete(tenant_id=1, id=uuid4())
