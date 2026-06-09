"""SP-034 (ADR-00026): FastMCP middleware — mutating tool の ingress guard。

`on_call_tool` hook で mutating tool だけに rate limit / max concurrent / max input bytes を
適用する。read tool は素通し。guard 内部エラーは fail-open (可用性優先)。

直接 ``tool.run()`` を呼ぶ unit test はこの middleware を経由しない (MCP call pipeline のみ)。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from backend.app.mcp.hardening import (
    DEFAULT_ACTOR_KEY,
    MUTATION_TOOLS,
    SERVER_OWNED_FORBIDDEN_FIELDS,
    admission_error,
    arguments_contain_secret,
    check_admission,
    estimate_input_bytes,
    input_size_exceeded,
    release_admission,
)

if TYPE_CHECKING:  # pragma: no cover
    import mcp.types as mt
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools import ToolResult

logger = logging.getLogger(__name__)


def resolve_actor_key(arguments: dict[str, object] | None) -> str:
    """ingress guard の actor key を解決する。

    現状 MCP は固定 default actor で動くため常に :data:`DEFAULT_ACTOR_KEY`。SP-016 で
    per-actor 認証が wired されると認証 actor を返すように差し替える (forward-compat)。
    caller-supplied な actor 申告 (arguments 内) は **信用しない** (server-owned boundary)。
    """
    return DEFAULT_ACTOR_KEY


class MutationGuardMiddleware(Middleware):
    """mutating tool の ingress を rate / concurrency / input-size で gate する。"""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = ""
        actor_key: str | None = None
        reason: str | None = None
        forbidden_fields: list[str] = []
        slot_acquired = False
        arguments: dict[str, object] | None = None
        try:
            params = context.message
            tool_name = params.name
            arguments = params.arguments
        except Exception:  # noqa: BLE001 — message 構造を読めないなら素通し (availability)。
            logger.debug("mcp ingress guard could not read call params; failing open", exc_info=True)
            return await call_next(context)

        # --- Security checks (Codex R16 F-24: scan 失敗は **fail-CLOSED**、fail-open しない) ---
        # Codex R11 F-16 / R12 F-18 / R13 F-20: server-owned forbidden field (capability_token /
        # provider_payload / actor_id / api_key 等の alias) を FastMCP validation 到達前に拒否する
        # (FastMCP の additionalProperties rejection は raw field value を ValidationError / WARNING へ
        # 露出する)。判定は case-insensitive、返却は original 名を保持し field 名のみ返す。
        try:
            forbidden_fields = sorted(
                original
                for original in (arguments or {})
                if str(original).lower() in SERVER_OWNED_FORBIDDEN_FIELDS
            )
            if forbidden_fields:
                reason = "caller_supplied_field_rejected"
            # Codex R15 F-23 / R16 F-24: forbidden 名でない unknown 引数の secret 値 / secret-shaped key を
            # FastMCP validation 到達前に bounded scan で止める。generic reject (field 名 / 値なし)。
            elif arguments_contain_secret(arguments):
                reason = "caller_supplied_secret_detected"
        except Exception:  # noqa: BLE001 — security-scan 失敗は fail-CLOSED (suspicious として reject)。
            logger.warning(
                "mcp ingress guard secret-scan error; failing closed tool=%s", tool_name
            )
            reason = "caller_supplied_secret_detected"

        # --- Availability checks (rate / concurrency / size): 内部エラーは fail-OPEN (可用性優先) ---
        if reason is None:
            try:
                if input_size_exceeded(estimate_input_bytes(arguments)):
                    reason = "input_too_large"
                elif tool_name in MUTATION_TOOLS:
                    actor_key = resolve_actor_key(arguments)
                    reason = check_admission(actor_key)
                    slot_acquired = reason is None
            except Exception:  # noqa: BLE001 — availability check の内部エラーは素通し。
                logger.debug("mcp ingress guard availability check error; failing open", exc_info=True)
                reason = None
                actor_key = None
                slot_acquired = False

        if reason is not None:
            # Codex R7 F-11: 拒否は ToolError 経由で MCP client に isError=true として届ける
            # (ToolResult だと isError=false の成功扱いになり blocked mutation を automation が誤認)。
            # log / 例外 payload には reason / tool / field 名のみ (raw 引数値は含めない、F-16)。
            logger.warning("mcp ingress guard rejected tool=%s reason=%s", tool_name, reason)
            raise ToolError(
                json.dumps(
                    admission_error(reason, tool_name, fields=forbidden_fields or None),
                    ensure_ascii=False,
                )
            )

        try:
            return await call_next(context)
        finally:
            if slot_acquired and actor_key is not None:
                try:
                    release_admission(actor_key)
                except Exception:  # noqa: BLE001
                    logger.debug("mcp ingress guard release failed", exc_info=True)


__all__ = ["MutationGuardMiddleware", "resolve_actor_key"]
