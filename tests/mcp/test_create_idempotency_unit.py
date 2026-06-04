"""ADR-00049 (SP-034) MCP create idempotency の no-DB unit / contract test。

DB 不要 (host で常時実行)。fingerprint の決定性と enum 整合を固定する。
race / reservation の DB 挙動は ``test_create_idempotency_db.py`` (TASKMANAGEDAI_RUN_DB_TESTS) を参照。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from backend.app.db.models.mcp_idempotency_key import (
    MCP_IDEMPOTENCY_RESOURCE_KINDS,
    MCP_IDEMPOTENCY_TOOL_NAMES,
)
from backend.app.services.mcp_idempotency import compute_request_fingerprint

# ADR-00049: 5+ source 整合 (DB CHECK migrations/0043 / ORM / Python Literal / pytest EXPECTED)。
EXPECTED_TOOL_NAMES = ("ticket_create", "run_create")
EXPECTED_RESOURCE_KINDS = ("ticket", "agent_run")


def test_tool_names_exact_set() -> None:
    assert MCP_IDEMPOTENCY_TOOL_NAMES == EXPECTED_TOOL_NAMES


def test_resource_kinds_exact_set() -> None:
    assert MCP_IDEMPOTENCY_RESOURCE_KINDS == EXPECTED_RESOURCE_KINDS


def test_fingerprint_is_deterministic() -> None:
    fields = {"project_id": "p1", "title": "T", "description": "D"}
    assert compute_request_fingerprint(fields) == compute_request_fingerprint(fields)


def test_fingerprint_is_key_order_independent() -> None:
    a = compute_request_fingerprint({"project_id": "p1", "title": "T", "description": "D"})
    b = compute_request_fingerprint({"description": "D", "title": "T", "project_id": "p1"})
    assert a == b


def test_fingerprint_differs_on_different_payload() -> None:
    base = compute_request_fingerprint({"project_id": "p1", "title": "T", "description": "D"})
    diff_title = compute_request_fingerprint(
        {"project_id": "p1", "title": "T2", "description": "D"}
    )
    diff_project = compute_request_fingerprint(
        {"project_id": "p2", "title": "T", "description": "D"}
    )
    assert base != diff_title
    assert base != diff_project


def test_fingerprint_distinguishes_none_from_empty_string() -> None:
    with_none = compute_request_fingerprint({"role_id": None, "x": "v"})
    with_empty = compute_request_fingerprint({"role_id": "", "x": "v"})
    assert with_none != with_empty


def test_fingerprint_is_sha256_hex() -> None:
    fp = compute_request_fingerprint({"project_id": "p1", "title": "T"})
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


@pytest.mark.asyncio
async def test_ticket_create_notifies_only_on_new_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-00049 Codex F-O1: 外部 side-effect (Discord 通知) も idempotent。新規作成のみ通知し、
    idempotent_replay / error では通知しない (downstream automation の重複誤認防止)。"""
    from backend.app.mcp import api_bridge, context, discord_notify, server

    @asynccontextmanager
    async def _fake_session() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(context, "get_db_session", _fake_session)

    notify_calls: list[str] = []

    async def _fake_notify(title: str, project_prefix: str) -> None:
        notify_calls.append(title)

    monkeypatch.setattr(discord_notify, "notify_ticket_created", _fake_notify)

    project_id = "00000000-0000-4000-8000-000000000004"
    new_id = "11111111-1111-4111-8111-111111111111"

    async def _fake_bridge_new(session: object, **kwargs: Any) -> dict[str, Any]:
        return {"ticket_id": new_id, "title": "t", "status": "open"}

    monkeypatch.setattr(api_bridge, "bridge_ticket_create", _fake_bridge_new)
    res_new = await server.ticket_create(project_id=project_id, title="t")
    assert res_new.get("idempotent_replay") is None
    assert notify_calls == ["t"]  # 新規作成 → 1 回通知

    notify_calls.clear()

    async def _fake_bridge_replay(session: object, **kwargs: Any) -> dict[str, Any]:
        return {"ticket_id": new_id, "title": "t", "status": "open", "idempotent_replay": True}

    monkeypatch.setattr(api_bridge, "bridge_ticket_create", _fake_bridge_replay)
    res_replay = await server.ticket_create(project_id=project_id, title="t")
    assert res_replay.get("idempotent_replay") is True
    assert notify_calls == []  # replay → 通知しない (F-O1)

    async def _fake_bridge_error(session: object, **kwargs: Any) -> dict[str, Any]:
        return {"error": "not_found", "ticket_id": "22222222-2222-4222-8222-222222222222"}

    monkeypatch.setattr(api_bridge, "bridge_ticket_create", _fake_bridge_error)
    res_err = await server.ticket_create(project_id=project_id, title="t")
    assert "error" in res_err
    assert notify_calls == []  # error dict → 通知しない
