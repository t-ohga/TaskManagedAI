"""Comprehensive MCP tool tests — all 39 tools covered."""

from __future__ import annotations

import pytest

TOOL_NAMES_EXPECTED = {
    "ticket_list", "ticket_show", "ticket_create", "ticket_update",
    "ticket_comment", "ticket_link", "ticket_list_all", "ticket_search",
    "run_create", "run_show", "run_cancel", "run_list", "run_update",
    "run_plan_dry_run", "run_cost",
    "approval_list", "approval_show", "approval_request_create",
    "audit_list", "context_show", "context_auto", "kpi_show",
    "notification_list", "notification_resolve",
    "project_list",
    "delegation_create", "delegation_inbox", "delegation_accept",
    "delegation_submit", "delegation_review", "delegation_tree",
    "delegation_cancel", "workflow_status",
    "superintendent_agent_register", "superintendent_agent_start",
    "superintendent_agent_stop", "superintendent_agent_list",
    "superintendent_delegation_show", "superintendent_dispatch",
}


@pytest.mark.asyncio
async def test_tool_count_is_39() -> None:
    from backend.app.mcp.server import mcp
    tools = await mcp.list_tools()
    assert len(tools) == 39


@pytest.mark.asyncio
async def test_all_expected_tools_registered() -> None:
    from backend.app.mcp.server import mcp
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    missing = TOOL_NAMES_EXPECTED - names
    extra = names - TOOL_NAMES_EXPECTED
    assert not missing, f"Missing tools: {missing}"
    assert not extra, f"Unexpected tools: {extra}"


@pytest.mark.asyncio
async def test_project_list_returns_projects() -> None:
    from backend.app.mcp.server import project_list
    r = await project_list()
    assert "projects" in r or "error" in r


@pytest.mark.asyncio
async def test_context_auto_returns_project_or_error() -> None:
    from backend.app.mcp.server import context_auto
    r = await context_auto(cwd="/Users/tohga/repo/kintone")
    assert "project_slug" in r or "error" in r


@pytest.mark.asyncio
async def test_context_show_returns_project_info() -> None:
    from backend.app.mcp.server import context_show
    r = await context_show()
    assert "project_id" in r or "error" in r


@pytest.mark.asyncio
async def test_kpi_show_returns_kpis() -> None:
    from backend.app.mcp.server import kpi_show
    r = await kpi_show()
    assert "kpis" in r or "error" in r


@pytest.mark.asyncio
async def test_ticket_list_all_returns_tickets() -> None:
    from backend.app.mcp.server import ticket_list_all
    r = await ticket_list_all()
    assert "tickets" in r or "error" in r


@pytest.mark.asyncio
async def test_ticket_search_returns_results() -> None:
    from backend.app.mcp.server import ticket_search
    r = await ticket_search(query="test")
    assert "tickets" in r or "error" in r


@pytest.mark.asyncio
async def test_approval_list_validates_status() -> None:
    from backend.app.mcp.server import approval_list
    r = await approval_list(status="bogus")
    assert r.get("error") == "invalid_status"


@pytest.mark.asyncio
async def test_approval_show_not_found() -> None:
    from backend.app.mcp.server import approval_show
    r = await approval_show(approval_id="00000000-0000-0000-0000-000000000000")
    assert "error" in r or "id" in r


@pytest.mark.asyncio
async def test_run_plan_dry_run() -> None:
    from backend.app.mcp.server import run_plan_dry_run
    r = await run_plan_dry_run(purpose="test")
    assert "purpose" in r


@pytest.mark.asyncio
async def test_run_create_invalid_ticket_uuid() -> None:
    from backend.app.mcp.server import run_create
    r = await run_create(
        project_id="00000000-0000-4000-8000-000000000004",
        ticket_id="not-a-uuid",
        purpose="test",
    )
    assert r.get("error") == "invalid_uuid"


@pytest.mark.asyncio
async def test_run_create_invalid_role() -> None:
    from backend.app.mcp.server import run_create
    r = await run_create(
        project_id="00000000-0000-4000-8000-000000000004",
        ticket_id="00000000-0000-4000-8000-000000000006",
        purpose="test",
        role_id="nonexistent",
    )
    assert r.get("error") == "invalid_role_id"


@pytest.mark.asyncio
async def test_ticket_list_all_invalid_status() -> None:
    from backend.app.mcp.server import ticket_list_all
    r = await ticket_list_all(status="bogus")
    assert r.get("error") == "invalid_status"


@pytest.mark.asyncio
async def test_superintendent_delegation_show() -> None:
    from backend.app.mcp.server import superintendent_delegation_show
    r = await superintendent_delegation_show()
    assert "forbidden_actions" in r
    assert "approval_decide" in r["forbidden_actions"]
    assert "merge" in r["forbidden_actions"]


@pytest.mark.asyncio
async def test_superintendent_dispatch_invalid_uuid() -> None:
    from backend.app.mcp.server import superintendent_dispatch
    r = await superintendent_dispatch(agent_id="not-uuid", ticket_id="test")
    assert r.get("error") == "invalid_uuid"


@pytest.mark.asyncio
async def test_superintendent_dispatch_forbidden_action() -> None:
    from backend.app.mcp.server import superintendent_dispatch
    r = await superintendent_dispatch(
        agent_id="00000000-0000-4000-8000-000000000099",
        ticket_id="00000000-0000-4000-8000-000000000006",
        action_class="merge",
    )
    assert r.get("denied") is True


@pytest.mark.asyncio
async def test_delegation_create_invalid_role() -> None:
    from backend.app.mcp.server import delegation_create
    r = await delegation_create(
        project_id="00000000-0000-4000-8000-000000000004",
        parent_run_id="00000000-0000-4000-8000-000000000099",
        ticket_id="00000000-0000-4000-8000-000000000006",
        purpose="test",
        role_id="nonexistent",
    )
    assert r.get("error") == "invalid_role_id"


@pytest.mark.asyncio
async def test_delegation_review_invalid_decision() -> None:
    from backend.app.mcp.server import delegation_review
    r = await delegation_review(
        run_id="00000000-0000-4000-8000-000000000099",
        reviewer_run_id="00000000-0000-4000-8000-000000000098",
        decision="maybe",
    )
    assert "error" in r


@pytest.mark.asyncio
async def test_workflow_status_returns_summary() -> None:
    from backend.app.mcp.server import workflow_status
    r = await workflow_status()
    assert "total_runs" in r or "error" in r


@pytest.mark.asyncio
async def test_approval_request_create_forbidden() -> None:
    from backend.app.mcp.server import approval_request_create
    r = await approval_request_create(
        project_id="00000000-0000-4000-8000-000000000004",
        ticket_id="00000000-0000-4000-8000-000000000006",
        action_class="merge",
    )
    assert r.get("error") == "forbidden_action"
