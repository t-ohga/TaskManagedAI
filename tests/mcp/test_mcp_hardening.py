"""SP-034 (ADR-00026): MCP ingress hardening tests (no-DB).

Closes acceptance criteria:
- caller-supplied server-owned field reject (gap #3): additionalProperties=False / forbidden
  field 非露出 / behavioral reject。
- per-actor rate limit + max concurrent + max input bytes (gap #1)。
- read/mutate partition drift guard (5+ source integrity)。
- stdio hardening: 絶対 interpreter path + subprocess env allowlist (gap #2)。
"""

from __future__ import annotations

import ast
import asyncio
import os
import pathlib
from collections.abc import Iterator

import pytest

from backend.app.mcp import hardening
from backend.app.mcp.hardening import (
    MUTATION_TOOLS,
    READ_TOOLS,
    SERVER_OWNED_FORBIDDEN_FIELDS,
    admission_error,
    check_admission,
    estimate_input_bytes,
    input_size_exceeded,
    release_admission,
    reset_admission_state,
)
from backend.app.mcp.middleware import MutationGuardMiddleware, resolve_actor_key

ACTOR = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _reset_guard_state() -> Iterator[None]:
    reset_admission_state()
    yield
    reset_admission_state()


def _registered_tool_names() -> set[str]:
    from backend.app.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def _tools_by_name() -> dict[str, object]:
    from backend.app.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name: t for t in tools}


# --- read/mutate partition (5+ source integrity drift guard) ---


class TestToolPartition:
    def test_partition_is_disjoint(self) -> None:
        assert MUTATION_TOOLS & READ_TOOLS == frozenset()

    def test_partition_covers_all_registered_tools(self) -> None:
        names = _registered_tool_names()
        partition = MUTATION_TOOLS | READ_TOOLS
        # 全 registered tool が partition のどちらかに分類される (新 tool 追加時に fail)。
        assert names == partition, (
            f"unclassified={names - partition} stale={partition - names}"
        )

    def test_partition_counts(self) -> None:
        assert len(MUTATION_TOOLS) == 19
        assert len(READ_TOOLS) == 20
        assert len(MUTATION_TOOLS | READ_TOOLS) == 39

    def test_committing_bridges_are_classified_mutating(self) -> None:
        """Codex adversarial R1 HIGH (F-1): commit する bridge を呼ぶ tool は MUTATION_TOOLS 必須。

        ``run_cost`` のような read 風の名前でも DB を書き込む path が guard を bypass しない
        ことを semantic に固定する (set 数だけの drift guard では捕捉できなかった class)。
        """
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        bridge_src = (repo_root / "backend/app/mcp/api_bridge.py").read_text()
        server_src = (repo_root / "backend/app/mcp/server.py").read_text()

        # 1) commit する bridge_* function を AST で抽出。
        committing_bridges: set[str] = set()
        for node in ast.walk(ast.parse(bridge_src)):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name.startswith(
                "bridge_"
            ):
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "commit"
                    ):
                        committing_bridges.add(node.name)
                        break

        # 2) 各 tool function が参照する bridge_* 名を抽出。
        tool_to_bridges: dict[str, set[str]] = {}
        for node in ast.walk(ast.parse(server_src)):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                refs = {
                    n.id
                    for n in ast.walk(node)
                    if isinstance(n, ast.Name) and n.id.startswith("bridge_")
                }
                if refs:
                    tool_to_bridges[node.name] = refs

        # 3) READ 分類の tool が commit する bridge を呼んでいたら誤分類 (guard bypass)。
        misclassified = {
            tool: sorted(bridges & committing_bridges)
            for tool, bridges in tool_to_bridges.items()
            if tool in READ_TOOLS and (bridges & committing_bridges)
        }
        assert not misclassified, (
            f"read-classified tools call a committing bridge (must be MUTATION_TOOLS): {misclassified}"
        )


# --- gap #3: caller-supplied server-owned field reject ---


class TestCallerSuppliedFieldReject:
    def test_all_tools_forbid_additional_properties(self) -> None:
        tools = _tools_by_name()
        for name, tool in tools.items():
            schema = tool.parameters  # type: ignore[attr-defined]
            assert schema.get("additionalProperties") is False, (
                f"tool {name} must set additionalProperties=False to reject caller-supplied fields"
            )

    def test_no_tool_exposes_server_owned_field(self) -> None:
        tools = _tools_by_name()
        for name, tool in tools.items():
            props = set((tool.parameters.get("properties") or {}).keys())  # type: ignore[attr-defined]
            leaked = props & SERVER_OWNED_FORBIDDEN_FIELDS
            assert not leaked, f"tool {name} exposes server-owned field(s): {sorted(leaked)}"

    def test_extra_server_owned_field_rejected_behaviorally(self) -> None:
        tools = _tools_by_name()
        ticket_create = tools["ticket_create"]
        with pytest.raises(Exception) as exc_info:  # noqa: PT011 — pydantic ValidationError
            asyncio.run(
                ticket_create.run(  # type: ignore[attr-defined]
                    {
                        "project_id": "00000000-0000-4000-8000-000000000abc",
                        "title": "x",
                        "actor_id": ACTOR,
                    }
                )
            )
        assert "actor_id" in str(exc_info.value)


# --- gap #1: rate limit / concurrency / input size ---


class TestAdmissionControl:
    def test_allows_within_limit(self) -> None:
        assert check_admission(ACTOR, now=100.0) is None
        release_admission(ACTOR)

    def test_rate_limit_rejects_over_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 2)
        monkeypatch.setattr(hardening, "MUTATION_RATE_WINDOW_SEC", 60)
        # 2 件は許可、in-flight は即解放して concurrency を空ける。
        assert check_admission(ACTOR, now=100.0) is None
        release_admission(ACTOR)
        assert check_admission(ACTOR, now=101.0) is None
        release_admission(ACTOR)
        # 3 件目は同一 window 内で rate_limited。
        assert check_admission(ACTOR, now=102.0) == "rate_limited"

    def test_rate_limit_window_slides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 1)
        monkeypatch.setattr(hardening, "MUTATION_RATE_WINDOW_SEC", 10)
        assert check_admission(ACTOR, now=100.0) is None
        release_admission(ACTOR)
        # window 内は拒否。
        assert check_admission(ACTOR, now=105.0) == "rate_limited"
        # window 経過後は許可。
        assert check_admission(ACTOR, now=111.0) is None
        release_admission(ACTOR)

    def test_concurrency_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hardening, "MAX_CONCURRENT_MUTATIONS", 1)
        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 1000)
        # 1 件目 in-flight (release しない)。
        assert check_admission(ACTOR, now=100.0) is None
        # 2 件目は concurrency 上限で拒否。
        assert check_admission(ACTOR, now=100.1) == "too_many_concurrent"
        # 解放後は許可。
        release_admission(ACTOR)
        assert check_admission(ACTOR, now=100.2) is None
        release_admission(ACTOR)

    def test_input_size_exceeded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hardening, "MAX_TOOL_INPUT_BYTES", 100)
        assert input_size_exceeded(101) is True
        # 上限ちょうどは許可。
        assert input_size_exceeded(100) is False

    def test_per_actor_isolation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 1)
        actor_a = "actor-a"
        actor_b = "actor-b"
        assert check_admission(actor_a, now=100.0) is None
        release_admission(actor_a)
        # actor_a は上限、actor_b は独立して許可。
        assert check_admission(actor_a, now=100.0) == "rate_limited"
        assert check_admission(actor_b, now=100.0) is None
        release_admission(actor_b)

    def test_estimate_input_bytes(self) -> None:
        assert estimate_input_bytes(None) == 0
        assert estimate_input_bytes({}) == 0
        # key + value の UTF-8 byte 数。
        assert estimate_input_bytes({"a": "bc"}) == len("a") + len("bc")
        assert estimate_input_bytes({"k": "あ"}) == len("k") + len("あ".encode())

    def test_deep_nested_secret_detected_without_recursion(self) -> None:
        """Codex R16 F-24: 深いネスト (recursion 上限超) の secret も RecursionError せず検出。"""
        from backend.app.mcp.hardening import arguments_contain_secret

        node: object = {"x": "sk-proj-CANARYABCDEFGHIJKLMN"}
        for _ in range(3000):
            node = {"x": node}
        assert arguments_contain_secret({"description": node}) is True

    def test_oversized_structure_fail_closed(self) -> None:
        """Codex R16 F-24: scan node 上限超の巨大構造は fail-closed (secret 疑い) で True。"""
        from backend.app.mcp.hardening import arguments_contain_secret

        big = {str(i): "ok" for i in range(20000)}
        assert arguments_contain_secret(big) is True

    def test_estimate_input_bytes_deep_nesting_bounded(self) -> None:
        """Codex R16 F-24: estimate_input_bytes も deep nesting で RecursionError せず too_large 化。"""
        from backend.app.mcp.hardening import MAX_TOOL_INPUT_BYTES, estimate_input_bytes

        big = {str(i): "ok" for i in range(20000)}
        assert estimate_input_bytes(big) > MAX_TOOL_INPUT_BYTES

    def test_secret_scan_failure_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex R16 F-24: security scan が例外を投げても fail-CLOSED (素通ししない)。"""
        import json as _json

        import mcp.types as mt
        from fastmcp.exceptions import ToolError
        from fastmcp.server.middleware import MiddlewareContext
        from fastmcp.tools import ToolResult

        def _boom(*_a: object, **_k: object) -> bool:
            raise RuntimeError("scan crashed")

        monkeypatch.setattr("backend.app.mcp.middleware.arguments_contain_secret", _boom)
        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        params = mt.CallToolRequestParams(
            name="ticket_create", arguments={"project_id": "p", "title": "t"}
        )
        ctx = MiddlewareContext(message=params)
        with pytest.raises(ToolError) as exc_info:
            asyncio.run(mw.on_call_tool(ctx, call_next))  # type: ignore[arg-type]
        # scan crash でも call_next は呼ばれず secret-detected で reject (fail-closed)。
        assert calls["n"] == 0
        assert _json.loads(str(exc_info.value))["error_code"] == "caller_supplied_secret_detected"

    def test_admission_error_has_no_raw_arguments(self) -> None:
        err = admission_error("rate_limited", "ticket_create")
        assert err["error_code"] == "rate_limited"
        assert err["tool"] == "ticket_create"
        assert err["blocked_by"] == "mcp_ingress_guard"
        assert err["retry_after_seconds"] == hardening.MUTATION_RATE_WINDOW_SEC
        # raw 引数値を含めない。
        for value in err.values():
            assert "secret" not in str(value).lower()


# --- middleware behaviour ---


class TestMutationGuardMiddleware:
    def _ctx(self, tool_name: str, arguments: dict[str, object]) -> object:
        import mcp.types as mt
        from fastmcp.server.middleware import MiddlewareContext

        params = mt.CallToolRequestParams(name=tool_name, arguments=arguments)
        return MiddlewareContext(message=params)

    def test_resolve_actor_key_ignores_caller_claim(self) -> None:
        # caller が arguments で actor を申告しても無視され、server-owned key を返す。
        assert resolve_actor_key({"actor_id": "evil"}) == hardening.DEFAULT_ACTOR_KEY
        assert resolve_actor_key(None) == hardening.DEFAULT_ACTOR_KEY

    def test_read_tool_passes_through(self) -> None:
        from fastmcp.tools import ToolResult

        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        ctx = self._ctx("ticket_list", {"project_id": "p"})
        result = asyncio.run(mw.on_call_tool(ctx, call_next))  # type: ignore[arg-type]
        assert calls["n"] == 1
        assert result.structured_content == {"ok": True}

    def test_oversized_read_tool_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex R2 F-3 + R7 F-11: input-size cap は read tool にも適用 + ToolError (isError)。"""
        import json as _json

        from fastmcp.exceptions import ToolError
        from fastmcp.tools import ToolResult

        monkeypatch.setattr(hardening, "MAX_TOOL_INPUT_BYTES", 10)
        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        # read tool に上限超の引数を渡す → call_next は呼ばれず ToolError (isError) で拒否。
        ctx = self._ctx("ticket_search", {"query": "x" * 100})
        with pytest.raises(ToolError) as exc_info:
            asyncio.run(mw.on_call_tool(ctx, call_next))  # type: ignore[arg-type]
        assert calls["n"] == 0
        assert _json.loads(str(exc_info.value))["error_code"] == "input_too_large"

    def test_mutating_tool_over_rate_limit_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        from fastmcp.exceptions import ToolError
        from fastmcp.tools import ToolResult

        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 1)
        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        ctx1 = self._ctx("ticket_create", {"project_id": "p", "title": "t"})
        first = asyncio.run(mw.on_call_tool(ctx1, call_next))  # type: ignore[arg-type]
        assert first.structured_content == {"ok": True}
        assert calls["n"] == 1

        ctx2 = self._ctx("ticket_create", {"project_id": "p", "title": "u"})
        # call_next は呼ばれず ToolError (isError=true) で拒否。
        with pytest.raises(ToolError) as exc_info:
            asyncio.run(mw.on_call_tool(ctx2, call_next))  # type: ignore[arg-type]
        assert calls["n"] == 1
        payload = _json.loads(str(exc_info.value))
        assert payload["error_code"] == "rate_limited"
        assert payload["blocked_by"] == "mcp_ingress_guard"

    @pytest.mark.parametrize(
        "field_name",
        [
            "capability_token",
            "secret_capability_token",
            "api_key",
            "raw_token",
            "session_token",
            "provider_key",
            "actor_id",
            # R13 F-20: case variants も拒否する (大文字 alias で guard を擦り抜けない)。
            "API_KEY",
            "Raw_Token",
            "SESSION_TOKEN",
            "Capability_Token",
        ],
    )
    def test_forbidden_field_rejected_without_value_leak(
        self, field_name: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Codex R11 F-16 / R12 F-18 / R13 F-20: forbidden / secret-alias (case 不問) を漏らさず拒否。"""
        import json as _json
        import logging as _logging

        from fastmcp.exceptions import ToolError
        from fastmcp.tools import ToolResult

        # case-insensitive で canonical forbidden set に含まれることを前提確認 (F-18/F-20 整合)。
        assert field_name.lower() in SERVER_OWNED_FORBIDDEN_FIELDS
        canary = "sk-live-CANARY-MUST-NOT-APPEAR-9f3a"
        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        ctx = self._ctx(
            "ticket_create",
            {"project_id": "p", "title": "t", field_name: canary},
        )
        with caplog.at_level(_logging.DEBUG):
            with pytest.raises(ToolError) as exc_info:
                asyncio.run(mw.on_call_tool(ctx, call_next))  # type: ignore[arg-type]
        # forbidden field は call_next (= FastMCP validation) 到達前に拒否。
        assert calls["n"] == 0
        # canary は例外文字列にも log にも出ない。
        assert canary not in str(exc_info.value)
        assert canary not in caplog.text
        payload = _json.loads(str(exc_info.value))
        assert payload["error_code"] == "caller_supplied_field_rejected"
        assert field_name in payload["fields"]
        assert canary not in _json.dumps(payload)

    @pytest.mark.parametrize("field_name", ["capability_token", "API_KEY", "Raw_Token"])
    def test_forbidden_field_rejected_at_protocol_without_leak(
        self, field_name: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Codex R11 F-16 / R13 F-20: MCP dispatch 経由でも (case 不問) FastMCP validation 前に止める。"""
        import logging as _logging

        from fastmcp import FastMCP
        from fastmcp.exceptions import ToolError

        canary = "sk-live-CANARY-PROTOCOL-7b2c"
        server = FastMCP("forbidden-test")

        @server.tool()
        async def ticket_create(project_id: str, title: str) -> dict[str, object]:
            return {"ok": True}

        server.add_middleware(MutationGuardMiddleware())

        async def _run() -> None:
            await server._call_tool_mcp(
                "ticket_create",
                {"project_id": "p", "title": "t", field_name: canary},
            )

        with caplog.at_level(_logging.DEBUG):
            with pytest.raises(ToolError) as exc_info:
                asyncio.run(_run())
        assert canary not in str(exc_info.value)
        assert canary not in caplog.text

    @pytest.mark.parametrize(
        "arguments",
        [
            {"project_id": "p", "title": "t", "unexpected": "sk-proj-CANARYABCDEFGHIJKLMN"},
            {"project_id": "p", "title": "t", "sk-proj-CANARYABCDEFGHIJKLMN": "v"},
            {"project_id": "p", "description": {"nested": "github_pat_CANARYABCDEFGHIJKLMN"}},
            # R17 F-25: nested prohibited key (broad pattern 非該当の短い値) も拒否。
            {"project_id": "p", "extra": {"capability_token": "short-secret"}},
            {"project_id": "p", "extra": {"API_KEY": "short-secret"}},
            {"project_id": "p", "items": [{"raw_token": "short-secret"}]},
        ],
    )
    def test_unknown_or_nested_secret_rejected_without_leak(
        self, arguments: dict[str, object], caplog: pytest.LogCaptureFixture
    ) -> None:
        """Codex R15 F-23 / R17 F-25: unknown / nested secret 値・key を FastMCP 前に generic 拒否。"""
        import json as _json
        import logging as _logging

        from fastmcp.exceptions import ToolError
        from fastmcp.tools import ToolResult

        canary_fragments = ["sk-proj-CANARY", "github_pat_CANARY", "short-secret"]
        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        ctx = self._ctx("ticket_create", arguments)
        with caplog.at_level(_logging.DEBUG):
            with pytest.raises(ToolError) as exc_info:
                asyncio.run(mw.on_call_tool(ctx, call_next))  # type: ignore[arg-type]
        assert calls["n"] == 0
        payload = _json.loads(str(exc_info.value))
        assert payload["error_code"] == "caller_supplied_secret_detected"
        # generic error: secret fragment は例外・caplog・payload のどこにも出ない。
        for fragment in canary_fragments:
            assert fragment not in str(exc_info.value)
            assert fragment not in caplog.text
            assert fragment not in _json.dumps(payload)
        # field 名 (secret-shaped key) も payload に出さない。
        assert "fields" not in payload

    def test_fail_open_on_internal_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastmcp.tools import ToolResult

        def _boom(*_a: object, **_k: object) -> str | None:
            raise RuntimeError("guard bug")

        monkeypatch.setattr("backend.app.mcp.middleware.check_admission", _boom)
        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        ctx = self._ctx("ticket_create", {"project_id": "p", "title": "t"})
        result = asyncio.run(mw.on_call_tool(ctx, call_next))  # type: ignore[arg-type]
        # 内部エラーでも call は通る (fail-open)。
        assert calls["n"] == 1
        assert result.structured_content == {"ok": True}

    def test_run_cost_is_rate_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex adversarial R1 HIGH (F-1): run_cost (DB-writing) も guard を通る。"""
        from fastmcp.exceptions import ToolError
        from fastmcp.tools import ToolResult

        assert "run_cost" in MUTATION_TOOLS
        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 1)
        mw = MutationGuardMiddleware()
        calls = {"n": 0}

        async def call_next(_ctx: object) -> ToolResult:
            calls["n"] += 1
            return ToolResult(structured_content={"ok": True})

        ctx1 = self._ctx("run_cost", {"run_id": "r", "cost_usd": 1.0})
        first = asyncio.run(mw.on_call_tool(ctx1, call_next))  # type: ignore[arg-type]
        assert first.structured_content == {"ok": True}
        ctx2 = self._ctx("run_cost", {"run_id": "r", "cost_usd": 2.0})
        with pytest.raises(ToolError):
            asyncio.run(mw.on_call_tool(ctx2, call_next))  # type: ignore[arg-type]
        assert calls["n"] == 1

    def test_ingress_rejection_is_protocol_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex R7 F-11: 拒否は MCP call dispatch で ToolError として伝播 (isError=true)。"""
        from fastmcp import FastMCP
        from fastmcp.exceptions import ToolError

        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 1)
        hardening.reset_admission_state()
        server = FastMCP("ingress-test")

        @server.tool()
        async def ticket_create(project_id: str, title: str) -> dict[str, object]:
            return {"ok": True}

        server.add_middleware(MutationGuardMiddleware())

        async def _run() -> None:
            await server._call_tool_mcp("ticket_create", {"project_id": "p", "title": "t"})
            with pytest.raises(ToolError):
                await server._call_tool_mcp("ticket_create", {"project_id": "p", "title": "u"})

        asyncio.run(_run())

    def test_concurrency_released_after_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.tools import ToolResult

        monkeypatch.setattr(hardening, "MAX_CONCURRENT_MUTATIONS", 1)
        monkeypatch.setattr(hardening, "MUTATION_RATE_LIMIT", 1000)
        mw = MutationGuardMiddleware()

        async def call_next(_ctx: object) -> ToolResult:
            return ToolResult(structured_content={"ok": True})

        # 2 回連続呼び出しても、各 call 後に concurrency が解放されるため両方成功する。
        for _ in range(2):
            ctx = self._ctx("run_cancel", {"run_id": "r"})
            result = asyncio.run(mw.on_call_tool(ctx, call_next))  # type: ignore[arg-type]
            assert result.structured_content == {"ok": True}


# --- Codex R3 F-5: read query bound clamp ---


class TestReadQueryBounds:
    def test_ticket_list_clamps_query_limit_before_db(self) -> None:
        """小さい input でも limit=1e9 で unbounded read query を通さない (clamp-before-query)。"""
        from uuid import UUID

        from backend.app.mcp.api_bridge import MAX_LIMIT, bridge_ticket_list

        captured: list[object] = []

        class _Scalars:
            def all(self) -> list[object]:
                return []

        class _Result:
            def scalar(self) -> int:
                return 0

            def scalars(self) -> _Scalars:
                return _Scalars()

        class _Session:
            async def execute(self, stmt: object, *args: object, **kwargs: object) -> _Result:
                captured.append(stmt)
                return _Result()

        asyncio.run(
            bridge_ticket_list(
                _Session(),  # type: ignore[arg-type]
                tenant_id=1,
                project_id=UUID("00000000-0000-4000-8000-000000000abc"),
                limit=10**9,
                offset=0,
            )
        )
        select_stmts = [s for s in captured if hasattr(s, "compile") and "tickets" in str(s).lower()]
        compiled = str(select_stmts[-1].compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]
        assert f"LIMIT {MAX_LIMIT}" in compiled
        assert "LIMIT 1000000000" not in compiled

    def test_ticket_search_clamps_query_limit_before_db(self) -> None:
        """Codex R4 F-6: ticket_search も raw limit を SQL へ渡さない (clamp-before-query)。"""
        from backend.app.mcp.api_bridge import MAX_LIMIT, bridge_ticket_search

        captured_params: list[object] = []

        class _Result:
            def fetchall(self) -> list[object]:
                return []

        class _Session:
            async def execute(self, stmt: object, params: object = None, *a: object) -> _Result:
                captured_params.append(params)
                return _Result()

        asyncio.run(
            bridge_ticket_search(
                _Session(),  # type: ignore[arg-type]
                tenant_id=1,
                query="",
                limit=10**9,
            )
        )
        # 実 query に渡す bind param の limit が MAX_LIMIT に clamp されている。
        assert captured_params, "expected a query execution"
        last = captured_params[-1]
        assert isinstance(last, dict)
        assert last["limit"] == MAX_LIMIT


# --- Codex R12 F-19: free-form task_spec secret scan (delegation) ---


class TestDelegationTaskSpecSecretScan:
    def test_helper_rejects_prohibited_key(self) -> None:
        from backend.app.mcp.api_bridge import _assert_freeform_payload_no_secret

        with pytest.raises(ValueError, match="prohibited secret key"):
            _assert_freeform_payload_no_secret({"nested": {"capability_token": "x"}})

    def test_helper_rejects_secret_value_pattern(self) -> None:
        from backend.app.mcp.api_bridge import _assert_freeform_payload_no_secret

        # broad scanner が拾う provider token pattern。
        with pytest.raises(ValueError):
            _assert_freeform_payload_no_secret({"note": "token sk-proj-ABCDEFGHIJKLMNOPQRSTUV"})

    def test_helper_rejects_secret_shaped_key(self) -> None:
        """Codex R14 F-21: secret-shaped な dict key も拒否 (`{"sk-proj-...": ...}`)。"""
        from backend.app.mcp.api_bridge import _assert_freeform_payload_no_secret

        with pytest.raises(ValueError):
            _assert_freeform_payload_no_secret({"sk-proj-ABCDEFGHIJKLMNOPQRSTUV": "v"})
        # nested でも拒否。
        with pytest.raises(ValueError):
            _assert_freeform_payload_no_secret({"a": {"github_pat_ABCDEFGHIJKLMNOPQRSTUV": "v"}})

    def test_helper_allows_clean_spec(self) -> None:
        from backend.app.mcp.api_bridge import _assert_freeform_payload_no_secret

        # 機密でない通常の task_spec は通る。
        _assert_freeform_payload_no_secret({"goal": "implement feature", "steps": ["a", "b"]})

    def test_bridge_rejects_secret_task_spec_without_db(self) -> None:
        """secret を含む task_spec は DB 書込・MCP echo 前に generic error で reject (raw 非露出)。"""
        import json as _json
        from uuid import UUID

        from backend.app.mcp.api_bridge import bridge_delegation_create

        canary = "CANARY-FIXTURE-ABCDEFGHIJKLMNOP"

        class _Session:
            async def execute(self, *_a: object, **_k: object) -> object:
                raise AssertionError("must reject before any DB access")

        result = asyncio.run(
            bridge_delegation_create(
                _Session(),  # type: ignore[arg-type]
                tenant_id=1,
                project_id=UUID("00000000-0000-4000-8000-0000000000a1"),
                parent_run_id=UUID("00000000-0000-4000-8000-0000000000a2"),
                ticket_id="00000000-0000-4000-8000-0000000000a3",
                purpose="p",
                role_id="implementer",
                task_spec={"capability_token": canary},
                sender_actor_id=UUID("00000000-0000-4000-8000-000000000001"),
            )
        )
        assert result == {"error": "task_spec_contains_secret"}
        assert canary not in _json.dumps(result)


# --- gap #2: stdio hardening — Discord は in-process httpx (Codex R7 F-10、subprocess 全廃) ---


class TestDiscordInProcessNotify:
    def test_no_subprocess_machinery_remains(self) -> None:
        """Codex R7 F-10: subprocess 経路 (token-bearing child / python -c import hijack) を全廃。"""
        from backend.app.mcp import discord_notify

        for removed in (
            "_SEND_SCRIPT",
            "_PYTHON_EXECUTABLE",
            "_hardened_subprocess_env",
            "_terminate_child",
        ):
            assert not hasattr(discord_notify, removed), f"{removed} must be removed"
        src = pathlib.Path(discord_notify.__file__).read_text()
        assert "create_subprocess" not in src
        assert "import httpx" in src

    def test_noop_without_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.app.mcp import discord_notify

        monkeypatch.setattr(discord_notify, "_resolve_discord_token", lambda: "")
        called = {"n": 0}

        def _fail_client(*_a: object, **_k: object) -> object:
            called["n"] += 1
            raise AssertionError("must not create an HTTP client without a token")

        monkeypatch.setattr(discord_notify.httpx, "AsyncClient", _fail_client)
        assert asyncio.run(discord_notify.notify_discord("hi")) is False
        assert called["n"] == 0

    def test_posts_in_process_with_bearer_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.app.mcp import discord_notify

        monkeypatch.setattr(discord_notify, "_resolve_discord_token", lambda: "bot-tok")
        captured: dict[str, object] = {}

        class _Resp:
            status_code = 200

        class _Client:
            def __init__(self, *_a: object, **_k: object) -> None:
                pass

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *_a: object) -> None:
                return None

            async def post(self, url: str, **kwargs: object) -> _Resp:
                captured["url"] = url
                captured["headers"] = kwargs.get("headers")
                captured["json"] = kwargs.get("json")
                return _Resp()

        monkeypatch.setattr(discord_notify.httpx, "AsyncClient", _Client)
        ok = asyncio.run(discord_notify.notify_discord("hello"))
        assert ok is True
        headers = captured["headers"]
        assert isinstance(headers, dict)
        # token は in-process の Authorization header に入り、subprocess env / argv には出ない。
        assert headers["Authorization"] == "Bot bot-tok"
        assert captured["json"] == {"content": "hello"}
        assert str(captured["url"]).startswith("https://discord.com/api/v10/channels/")

    def test_best_effort_swallows_http_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.app.mcp import discord_notify

        monkeypatch.setattr(discord_notify, "_resolve_discord_token", lambda: "bot-tok")

        class _Boom:
            def __init__(self, *_a: object, **_k: object) -> None:
                raise RuntimeError("network down")

        monkeypatch.setattr(discord_notify.httpx, "AsyncClient", _Boom)
        assert asyncio.run(discord_notify.notify_discord("hi")) is False

    def test_trusted_dependency_path_classification(self) -> None:
        """Codex R8 F-12: site-packages/dist-packages のみ trusted、project-local は untrusted。"""
        from backend.app.mcp.discord_notify import _is_trusted_dependency_path

        assert _is_trusted_dependency_path("/srv/app/.venv/lib/python3.12/site-packages/httpx/__init__.py")
        assert _is_trusted_dependency_path("/usr/lib/python3/dist-packages/httpx/__init__.py")
        # project-local shadow (repo root の httpx.py) は untrusted。
        assert not _is_trusted_dependency_path("/srv/repo/httpx.py")
        assert not _is_trusted_dependency_path("/srv/repo/backend/httpx.py")
        assert not _is_trusted_dependency_path(None)

    def test_fail_closed_when_httpx_untrusted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex R8 F-12: httpx が project-local shadow 疑いなら token を使わず no-op。"""
        from backend.app.mcp import discord_notify

        monkeypatch.setattr(discord_notify, "_HTTPX_TRUSTED", False)

        def _fail_token() -> str:
            raise AssertionError("must not resolve/use token when httpx is untrusted")

        def _fail_client(*_a: object, **_k: object) -> object:
            raise AssertionError("must not create an HTTP client when httpx is untrusted")

        monkeypatch.setattr(discord_notify, "_resolve_discord_token", _fail_token)
        monkeypatch.setattr(discord_notify.httpx, "AsyncClient", _fail_client)
        assert asyncio.run(discord_notify.notify_discord("hi")) is False

    def test_real_httpx_is_trusted(self) -> None:
        """実環境の httpx は trusted path から load されている (guard が誤発火しない)。"""
        from backend.app.mcp import discord_notify

        assert discord_notify._HTTPX_TRUSTED is True


# --- Codex R5 F-7: MCP-reachable subprocess absolute argv ---


class TestAgentSpawnerArgvHardening:
    def test_resolves_to_absolute_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.app.services.superintendent import agent_spawner

        monkeypatch.setattr(agent_spawner.shutil, "which", lambda _name: "/usr/local/bin/claude")
        cmd = agent_spawner._build_agent_command("claude", "/srv/project")
        assert cmd[0] == "/usr/local/bin/claude"
        assert os.path.isabs(cmd[0])

    def test_missing_executable_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.app.services.superintendent import agent_spawner

        monkeypatch.setattr(agent_spawner.shutil, "which", lambda _name: None)
        with pytest.raises(FileNotFoundError):
            agent_spawner._build_agent_command("codex", "/srv/project")

    def test_project_local_executable_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.app.services.superintendent import agent_spawner

        # project_dir 配下の binary は hijack 防止のため拒否。
        monkeypatch.setattr(
            agent_spawner.shutil, "which", lambda _name: "/srv/project/evil/claude"
        )
        with pytest.raises(ValueError, match="project-local"):
            agent_spawner._build_agent_command("claude", "/srv/project")

    def test_tmp_resolved_executable_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex R10 F-15: ambient PATH poisoning (/tmp/bin の悪性 claude) を拒否。"""
        from backend.app.services.superintendent import agent_spawner

        monkeypatch.setattr(agent_spawner.shutil, "which", lambda _name: "/tmp/evil/claude")  # noqa: S108
        with pytest.raises(ValueError, match="transient"):
            agent_spawner._build_agent_command("claude", "/srv/project")

    def test_child_path_reconstructed_to_trusted_minimal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex R10 F-15: 子へ ambient PATH を継承させず最小 trusted PATH に再構成。"""
        from backend.app.services.superintendent import agent_spawner

        monkeypatch.setenv("PATH", "/tmp/evil:/usr/bin")  # noqa: S108
        env = agent_spawner._build_safe_env("/srv/project", executable="/usr/local/bin/claude")
        # poisoned ambient PATH (/tmp/evil) は子へ渡さない。
        assert "/tmp/evil" not in env["PATH"].split(":")  # noqa: S108
        # 解決済み executable の dir は含む。
        assert "/usr/local/bin" in env["PATH"].split(":")

    def test_group_world_writable_executable_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Codex R12 F-17: 他ユーザ writable な executable は command hijack として拒否。"""
        import stat as _stat

        from backend.app.services.superintendent import agent_spawner

        monkeypatch.setattr(agent_spawner.shutil, "which", lambda _name: "/opt/shared/bin/claude")
        monkeypatch.setattr(agent_spawner, "_path_mode", lambda _p: 0o755 | _stat.S_IWOTH)
        with pytest.raises(ValueError, match="writable"):
            agent_spawner._build_agent_command("claude", "/srv/project")

    def test_user_owned_executable_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """user-owned (755) の ~/.local/bin 等の正規 install 先は通す (誤発火しない)。"""
        from backend.app.services.superintendent import agent_spawner

        monkeypatch.setattr(
            agent_spawner.shutil, "which", lambda _name: "/home/u/.local/bin/claude"
        )
        monkeypatch.setattr(agent_spawner, "_path_mode", lambda _p: 0o755)
        cmd = agent_spawner._build_agent_command("claude", "/srv/project")
        # realpath は環境で prefix を付け得る (macOS の /home 等)。基底名で検証。
        assert cmd[0].endswith("/.local/bin/claude")
        assert os.path.isabs(cmd[0])


class TestAgentSpawnerLifecycle:
    """Codex R6 F-9: spawn は未使用 pipe を DEVNULL、stop は process group を kill。"""

    def test_spawn_uses_devnull_pipes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from uuid import UUID

        from backend.app.services.superintendent import agent_spawner

        captured: dict[str, object] = {}

        class _Proc:
            pid = 12345
            returncode = None

        async def _fake_exec(*_cmd: object, **kwargs: object) -> _Proc:
            captured.update(kwargs)
            return _Proc()

        monkeypatch.setattr(agent_spawner, "_build_agent_command", lambda _p, _d: ["/usr/bin/true"])
        monkeypatch.setattr(agent_spawner.asyncio, "create_subprocess_exec", _fake_exec)
        try:
            asyncio.run(
                agent_spawner.spawn_agent(
                    UUID("00000000-0000-4000-8000-0000000c0de1"), "claude", "/srv/project"
                )
            )
            assert captured["stdin"] == asyncio.subprocess.DEVNULL
            assert captured["stdout"] == asyncio.subprocess.DEVNULL
            assert captured["stderr"] == asyncio.subprocess.DEVNULL
            assert captured["start_new_session"] is True
        finally:
            agent_spawner._active_agents.clear()

    def test_signal_process_group_targets_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import signal as _sig

        from backend.app.services.superintendent import agent_spawner

        calls: list[tuple[int, int]] = []
        monkeypatch.setattr(agent_spawner.os, "getpgid", lambda _pid: 999)
        monkeypatch.setattr(agent_spawner.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))

        class _Proc:
            pid = 555
            returncode = None

        agent_spawner._signal_process_group(_Proc(), _sig.SIGTERM)  # type: ignore[arg-type]
        assert calls == [(999, _sig.SIGTERM)]

    def test_signal_process_group_fallback_to_direct_child(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import signal as _sig

        from backend.app.services.superintendent import agent_spawner

        def _boom(_pid: int) -> int:
            raise ProcessLookupError

        monkeypatch.setattr(agent_spawner.os, "getpgid", _boom)
        events: list[str] = []

        class _Proc:
            pid = 555
            returncode = None

            def terminate(self) -> None:
                events.append("terminate")

            def kill(self) -> None:
                events.append("kill")

        agent_spawner._signal_process_group(_Proc(), _sig.SIGKILL)  # type: ignore[arg-type]
        assert events == ["kill"]  # group 解決失敗時は直接 child へ fallback。

    def test_signal_process_group_noop_when_exited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import signal as _sig

        from backend.app.services.superintendent import agent_spawner

        called: list[object] = []
        monkeypatch.setattr(agent_spawner.os, "killpg", lambda *a: called.append(a))

        class _Proc:
            pid = 555
            returncode = 0  # 既に終了済。

        agent_spawner._signal_process_group(_Proc(), _sig.SIGTERM)  # type: ignore[arg-type]
        assert called == []
