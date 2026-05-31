"""ADR-00038 (L-3 SSE realtime) fast contract / redaction test (no DB)。

security-critical な全 SSE DTO allowlist redaction (R1/R9: raw payload/secret/forbidden field を
stream に乗せない) と endpoint contract (flag-off 204 / invalid ?last_event_id= 422) を fast に固定する。
DB-backed な catch-up / scope_revoked / capacity 503 / pool 隔離 / trigger NOTIFY の統合 test は
TASKMANAGEDAI_RUN_DB_TESTS gate 下の別ファイルで扱う (本 fast test は DB 不要)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.app.config import get_settings
from backend.app.main import create_app
from backend.app.services.realtime import agent_run_stream as ars

# ---------------------------------------------------------------------------
# 全 SSE DTO allowlist redaction (R1/R9 security-critical)
# ---------------------------------------------------------------------------


def test_event_dto_redacts_prohibited_key_payload() -> None:
    event = SimpleNamespace(
        id=uuid4(),
        seq_no=3,
        event_type="provider_requested",
        actor_id=uuid4(),
        event_payload={"api_key": "sk-live-deadbeefdeadbeef", "model": "gpt"},
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    dto = ars._event_dto(event)
    assert dto["payload_keys"] == []
    assert dto["payload_redaction_status"] == "blocked_by_secret_scan"
    # raw secret 値も payload dict も stream に乗らない。
    serialized = json.dumps(dto)
    assert "sk-live-deadbeefdeadbeef" not in serialized
    assert "event_payload" not in dto


def test_event_dto_clean_payload_keys_only_no_values() -> None:
    event = SimpleNamespace(
        id=uuid4(),
        seq_no=5,
        event_type="run_queued",
        actor_id=uuid4(),
        event_payload={"role_id": "implementer", "alpha": 1},
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    dto = ars._event_dto(event)
    assert dto["payload_keys"] == ["alpha", "role_id"]  # sorted
    assert dto["payload_redaction_status"] == "keys_only"
    assert dto["seq_no"] == 5
    assert dto["event_type"] == "run_queued"
    # raw payload value は乗らない / UUID は event_id に rename (R2 framing)。
    assert "implementer" not in json.dumps(dto)
    assert "event_id" in dto
    assert "id" not in dto


def test_status_dto_allowlist_exact() -> None:
    row = SimpleNamespace(
        status="running", blocked_reason=None, completed_at=None, error_code=None
    )
    dto = ars._status_dto(row)
    assert set(dto.keys()) == {"status", "blocked_reason", "terminal", "completed_at", "error_code"}
    assert dto["terminal"] is False
    # forbidden field (error_summary raw / provider metadata / cost) は乗らない (R1/R9)。
    for forbidden in ("error_summary", "cost_usd", "tokens_input", "tokens_output", "provider"):
        assert forbidden not in dto


def test_status_dto_terminal_flag_true_on_terminal() -> None:
    row = SimpleNamespace(
        status="completed",
        blocked_reason=None,
        completed_at=datetime(2026, 6, 1, tzinfo=UTC),
        error_code=None,
    )
    assert ars._status_dto(row)["terminal"] is True


def test_status_dto_blocked_reason_passthrough() -> None:
    row = SimpleNamespace(
        status="blocked", blocked_reason="policy_blocked", completed_at=None, error_code="E_X"
    )
    dto = ars._status_dto(row)
    assert dto["status"] == "blocked"
    assert dto["blocked_reason"] == "policy_blocked"
    assert dto["terminal"] is False


# ---------------------------------------------------------------------------
# SSE framing contract (R2: id は agent_run_event のみ seq_no)
# ---------------------------------------------------------------------------


def test_frame_event_carries_id_and_event() -> None:
    body = ars._frame("agent_run_event", {"seq_no": 7}, sse_id=7).decode()
    assert body.startswith("id: 7\n")
    assert "event: agent_run_event\n" in body
    assert body.endswith("\n\n")


def test_frame_status_has_no_sse_id() -> None:
    body = ars._frame("agent_run_status", {"status": "running"})
    assert b"id:" not in body
    assert b"event: agent_run_status" in body


def test_frame_stream_end_and_error_have_no_id() -> None:
    assert b"id:" not in ars._frame("stream_end", {"reason": "terminal"})
    assert b"id:" not in ars._frame(
        "agent_run_error", {"reason": "internal_error", "retryable": True}
    )


def test_reason_and_terminal_enums() -> None:
    assert ars.STREAM_END_REASONS == frozenset(
        {"terminal", "scope_revoked", "max_lifetime", "server_shutdown"}
    )
    assert "internal_error" in ars.ERROR_REASONS
    assert ars.TERMINAL_STATUSES == frozenset(
        {"completed", "failed", "cancelled", "provider_refused", "repair_exhausted"}
    )


# ---------------------------------------------------------------------------
# endpoint contract (app, no DB)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as http_client:
        yield http_client


async def test_stream_flag_off_returns_204(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # flag-off は 204 (client は spec 通り再接続停止、R4)。DB を触らず返る。
    monkeypatch.setattr(get_settings(), "agentrun_sse_enabled", False)
    resp = await client.get(f"/api/v1/agent_runs/{uuid4()}/events/stream")
    assert resp.status_code == 204


async def test_stream_invalid_last_event_id_returns_422(client: AsyncClient) -> None:
    # 非整数 ?last_event_id= は FastAPI validation で 422 (pool acquire 前、R7)。
    resp = await client.get(
        f"/api/v1/agent_runs/{uuid4()}/events/stream?last_event_id=notanint"
    )
    assert resp.status_code == 422


async def test_stream_negative_last_event_id_returns_422(client: AsyncClient) -> None:
    resp = await client.get(f"/api/v1/agent_runs/{uuid4()}/events/stream?last_event_id=-1")
    assert resp.status_code == 422
