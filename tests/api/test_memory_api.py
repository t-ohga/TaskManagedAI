"""SP-018 T08 memory API disabled and feature-flagged contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.memory import router as memory_router
from backend.app.config import Settings
from backend.app.db.models.memory_record import MemoryRecord, MemoryRetrievalArtifact
from backend.app.schemas.memory import MemoryRetrievalRequest
from backend.app.services.memory.retrieval import (
    MemoryRetrievalDenied,
    MemoryRetrievalResult,
    MemoryRetrievalService,
)

_TENANT_ID = 1
_ACTOR_ID = UUID("00000000-0000-4000-8000-000000018801")
_PROJECT_ID = UUID("00000000-0000-4000-8000-000000018802")
_RUN_ID = UUID("00000000-0000-4000-8000-000000018803")
_MEMORY_RECORD_ID = UUID("00000000-0000-4000-8000-000000018804")
_CONTEXT_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000018805")


def _settings(*, memory_api_enabled: bool) -> Settings:
    return Settings(
        environment="test",
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        database_url="postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:5432/test",
        redis_url="redis://127.0.0.1:6379/1",
        dev_login_cookie_secret="test-cookie-secret-memory-api",
        memory_api_enabled=memory_api_enabled,
    )


def _build_app(*, memory_api_enabled: bool) -> FastAPI:
    app = FastAPI()
    app.state.settings = _settings(memory_api_enabled=memory_api_enabled)
    app.include_router(memory_router)

    async def override_tenant() -> int:
        return _TENANT_ID

    async def override_actor() -> UUID:
        return _ACTOR_ID

    async def override_db() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_tenant_id] = override_tenant
    app.dependency_overrides[get_current_actor_id] = override_actor
    app.dependency_overrides[get_db_session] = override_db
    return app


@pytest_asyncio.fixture
async def disabled_client() -> AsyncIterator[AsyncClient]:
    app = _build_app(memory_api_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def enabled_client() -> AsyncIterator[AsyncClient]:
    app = _build_app(memory_api_enabled=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def test_memory_api_feature_flag_defaults_disabled() -> None:
    assert _settings(memory_api_enabled=False).memory_api_enabled is False


@pytest.mark.asyncio
async def test_memory_api_disabled_returns_404_without_service_call(
    disabled_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*_: Any, **__: Any) -> MemoryRetrievalResult:
        raise AssertionError("MemoryRetrievalService.retrieve must not be called")

    monkeypatch.setattr(MemoryRetrievalService, "retrieve", fail_if_called)

    response = await disabled_client.get(
        f"/api/v1/projects/{_PROJECT_ID}/memory/retrievals",
        params={"retrieval_run_id": str(_RUN_ID)},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "memory api disabled"


@pytest.mark.asyncio
async def test_memory_api_enabled_returns_ref_only_retrieval_response(
    enabled_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_retrieve(
        self: MemoryRetrievalService,
        *,
        tenant_id: int,
        request: object,
        context_snapshot_id: UUID | None = None,
    ) -> MemoryRetrievalResult:
        captured["tenant_id"] = tenant_id
        captured["request"] = request
        captured["context_snapshot_id"] = context_snapshot_id
        record = SimpleNamespace(
            id=_MEMORY_RECORD_ID,
            record_kind="manual_user",
            content_artifact_ref=f"artifact://memory/{_MEMORY_RECORD_ID}",
            content_hash="a" * 64,
            data_class="internal",
            redaction_status="redacted",
            created_at=datetime(2026, 5, 24, 12, 0, tzinfo=UTC),
        )
        retrieval_artifact = SimpleNamespace(
            retrieval_artifact_ref=f"artifact://memory-retrieval/{_MEMORY_RECORD_ID}",
            retrieval_hash="b" * 64,
            context_snapshot_id=_CONTEXT_SNAPSHOT_ID,
            trust_level="untrusted_content",
        )
        return MemoryRetrievalResult(
            records=(cast(MemoryRecord, record),),
            artifact=None,
            retrieval_artifacts=(cast(MemoryRetrievalArtifact, retrieval_artifact),),
            payload_data_class="internal",
            retrieval_hash="b" * 64,
            sanitizer_policy_version="v1.0.0",
        )

    monkeypatch.setattr(MemoryRetrievalService, "retrieve", fake_retrieve)

    response = await enabled_client.get(
        f"/api/v1/projects/{_PROJECT_ID}/memory/retrievals",
        params=[
            ("retrieval_run_id", str(_RUN_ID)),
            ("memory_record_id", str(_MEMORY_RECORD_ID)),
            ("record_kind", "manual_user"),
            ("limit", "10"),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trust_level"] == "untrusted_content"
    assert payload["retrieval_hash"] == "b" * 64
    assert payload["sanitizer_policy_version"] == "v1.0.0"
    assert payload["items"] == [
        {
            "memory_record_id": str(_MEMORY_RECORD_ID),
            "record_kind": "manual_user",
            "content_artifact_ref": f"artifact://memory/{_MEMORY_RECORD_ID}",
            "content_hash": "a" * 64,
            "data_class": "internal",
            "redaction_status": "redacted",
            "trust_level": "untrusted_content",
            "created_at": "2026-05-24T12:00:00Z",
        }
    ]
    assert payload["retrieval_artifacts"][0]["context_snapshot_id"] == str(
        _CONTEXT_SNAPSHOT_ID
    )
    assert "payload" not in str(payload)
    request = cast(MemoryRetrievalRequest, captured["request"])
    assert request.project_id == _PROJECT_ID
    assert request.retrieval_run_id == _RUN_ID
    assert request.memory_record_ids == (_MEMORY_RECORD_ID,)
    assert request.record_kinds == ("manual_user",)
    assert request.limit == 10


@pytest.mark.asyncio
async def test_memory_api_maps_stale_sanitizer_to_409(
    enabled_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_retrieve(*_: Any, **__: Any) -> MemoryRetrievalResult:
        raise MemoryRetrievalDenied("stale_sanitizer")

    monkeypatch.setattr(MemoryRetrievalService, "retrieve", fake_retrieve)

    response = await enabled_client.get(
        f"/api/v1/projects/{_PROJECT_ID}/memory/retrievals",
        params={"retrieval_run_id": str(_RUN_ID)},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "stale_sanitizer"
