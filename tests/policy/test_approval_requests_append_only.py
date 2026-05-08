from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.repositories.approval_request import ApprovalRequestRepository


class _DummySession:
    pass


@pytest.mark.asyncio
async def test_approval_request_repository_delete_raises_not_implemented() -> None:
    repo = ApprovalRequestRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="append-only"):
        await repo.delete(tenant_id=1, id=uuid4())


def test_approval_request_repository_statement_for_delete_raises() -> None:
    repo = ApprovalRequestRepository(_DummySession())  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="statement_for_delete"):
        repo.statement_for_delete(tenant_id=1, id=uuid4())

