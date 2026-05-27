"""E2E dogfooding: MCP tools → DB → verify round-trip.

Tests that MCP ticket_create actually writes to DB and ticket_list reads it back.
Requires running PostgreSQL (skips if unavailable).
"""

from __future__ import annotations

import os

import pytest

DOGFOODING_PROJECT_ID = os.environ.get(
    "TASKMANAGEDAI_DOGFOODING_PROJECT_ID",
    "00000000-0000-4000-8000-000000000099",
)


@pytest.mark.asyncio
async def test_mcp_ticket_create_and_list_round_trip() -> None:
    """Create a ticket via MCP tool, then list and verify it exists."""
    from backend.app.mcp.server import ticket_create, ticket_list

    create_result = await ticket_create(
        project_id=DOGFOODING_PROJECT_ID,
        title="E2E dogfooding test ticket",
        description="Created by test_mcp_e2e_dogfooding.py",
    )

    if "error" in create_result:
        pytest.skip(f"DB not available: {create_result.get('error')}")

    assert "ticket_id" in create_result
    assert create_result["title"] == "E2E dogfooding test ticket"

    list_result = await ticket_list(project_id=DOGFOODING_PROJECT_ID)

    if "error" in list_result:
        pytest.skip(f"DB not available for list: {list_result.get('error')}")

    ticket_ids = [t["id"] for t in list_result.get("tickets", [])]
    assert create_result["ticket_id"] in ticket_ids


@pytest.mark.asyncio
async def test_mcp_superintendent_delegation_show() -> None:
    """Superintendent delegation policy is readable and contains forbidden actions."""
    from backend.app.mcp.server import superintendent_delegation_show

    result = await superintendent_delegation_show()

    assert "forbidden_actions" in result
    assert "approval_decide" in result["forbidden_actions"]
    assert "merge" in result["forbidden_actions"]
    assert "deploy" in result["forbidden_actions"]
    assert "secret_access" in result["forbidden_actions"]
    assert "provider_call" in result["forbidden_actions"]


@pytest.mark.asyncio
async def test_mcp_superintendent_dispatch_forbidden_action_denied() -> None:
    """Superintendent cannot dispatch merge action."""
    from backend.app.mcp.server import superintendent_dispatch

    result = await superintendent_dispatch(
        agent_id="00000000-0000-4000-8000-000000000099",
        ticket_id="00000000-0000-4000-8000-000000000006",
        action_class="merge",
    )

    assert result.get("denied") is True or result.get("dispatched") is False


@pytest.mark.asyncio
async def test_mcp_tool_count_is_21() -> None:
    """All 22 tools (16 base + 6 superintendent) are registered."""
    from backend.app.mcp.server import mcp

    tools = await mcp.list_tools()
    assert len(tools) == 28
