"""ADR-00049 (SP-034) MCP create idempotency の no-DB unit / contract test。

DB 不要 (host で常時実行)。fingerprint の決定性と enum 整合を固定する。
race / reservation の DB 挙動は ``test_create_idempotency_db.py`` (TASKMANAGEDAI_RUN_DB_TESTS) を参照。
"""

from __future__ import annotations

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
