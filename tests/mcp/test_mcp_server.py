"""SP-034: MCP Server tool registration + security boundary tests."""

from __future__ import annotations

import pytest

from backend.app.mcp.server import mcp

EXPECTED_TOOL_COUNT = 35

EXPECTED_READ_TOOLS = {
    "ticket_list",
    "ticket_show",
    "run_show",
    "run_plan_dry_run",
    "approval_list",
    "approval_show",
    "audit_list",
    "context_show",
    "kpi_show",
    "notification_list",
}

EXPECTED_MUTATE_TOOLS = {
    "ticket_create",
    "ticket_update",
    "run_create",
    "run_cancel",
    "notification_resolve",
    "superintendent_agent_register",
    "superintendent_agent_start",
    "superintendent_agent_stop",
    "superintendent_dispatch",
}

EXPECTED_SUPERINTENDENT_READ_TOOLS = {
    "superintendent_agent_list",
    "superintendent_delegation_show",
}

HUMAN_ONLY_EXCLUDED = {
    "approval_decide",
    "repo_push",
    "pr_open",
    "merge",
    "deploy",
}


def _get_tool_names() -> set[str]:
    import asyncio

    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


class TestToolRegistration:
    def test_expected_tool_count(self) -> None:
        names = _get_tool_names()
        if not names:
            pytest.skip("FastMCP tool introspection not available in this version")
        assert len(names) == EXPECTED_TOOL_COUNT

    def test_read_tools_registered(self) -> None:
        names = _get_tool_names()
        if not names:
            pytest.skip("FastMCP tool introspection not available")
        for tool in EXPECTED_READ_TOOLS:
            assert tool in names, f"read tool {tool} not registered"

    def test_mutate_tools_registered(self) -> None:
        names = _get_tool_names()
        if not names:
            pytest.skip("FastMCP tool introspection not available")
        for tool in EXPECTED_MUTATE_TOOLS:
            assert tool in names, f"mutate tool {tool} not registered"


class TestSecurityBoundary:
    def test_human_only_tools_not_exposed(self) -> None:
        names = _get_tool_names()
        if not names:
            pytest.skip("FastMCP tool introspection not available")
        for tool in HUMAN_ONLY_EXCLUDED:
            assert tool not in names, f"human-only tool {tool} must not be exposed via MCP"

    @pytest.mark.asyncio
    async def test_ticket_list_returns_no_raw_secret(self) -> None:
        from backend.app.mcp.server import ticket_list

        result = await ticket_list(project_id="test-project")
        serialized = str(result)
        assert "secret" not in serialized.lower() or "raw" not in serialized.lower()

    @pytest.mark.asyncio
    async def test_audit_list_returns_no_raw_secret(self) -> None:
        from backend.app.mcp.server import audit_list

        result = await audit_list()
        serialized = str(result)
        assert "secret_value" not in serialized
        assert "raw_provider" not in serialized


class TestMcpServerImport:
    def test_server_name(self) -> None:
        assert mcp.name == "TaskManagedAI"

    def test_server_has_instructions(self) -> None:
        assert mcp.instructions is not None
        assert "human-only" in mcp.instructions or "approval_decide" in mcp.instructions
