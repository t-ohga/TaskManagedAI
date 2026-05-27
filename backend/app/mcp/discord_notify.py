"""Discord notification helper for TaskManagedAI MCP tools.

Uses the existing Discord MCP (mcp__discord__discord_send) via
subprocess call to the discord MCP server. Falls back to no-op
if Discord is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

DISCORD_CHANNEL_ID = os.environ.get(
    "TASKMANAGEDAI_DISCORD_CHANNEL", "1466673510444433428"
)

_NOTIFY_ENABLED = True


async def notify_discord(message: str) -> bool:
    if not _NOTIFY_ENABLED:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-c",
            f"""
import asyncio, json, sys
try:
    import httpx
    # Use Discord bot token from env to send directly
    token = "{os.environ.get('DISCORD_TOKEN', '')}"
    if not token:
        sys.exit(0)
    async def send():
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages",
                headers={{"Authorization": f"Bot {{token}}", "Content-Type": "application/json"}},
                json={{"content": {json.dumps(message)}}},
                timeout=10,
            )
            print(r.status_code)
    asyncio.run(send())
except Exception:
    pass
""",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
        return proc.returncode == 0
    except Exception:
        logger.debug("Discord notification failed (non-critical)")
        return False


async def notify_ticket_created(title: str, project_name: str) -> None:
    await notify_discord(f"📋 **新規チケット**: {title}\nプロジェクト: {project_name}")


async def notify_dispatch(agent_id: str, ticket_title: str, action_class: str) -> None:
    await notify_discord(
        f"🤖 **タスク割り当て**: {ticket_title}\n"
        f"Agent: `{agent_id[:8]}...` | Action: {action_class}"
    )


async def notify_run_completed(run_id: str, status: str, purpose: str) -> None:
    emoji = "✅" if status == "completed" else "❌" if status == "failed" else "⏹️"
    await notify_discord(f"{emoji} **AgentRun {status}**: {purpose}\nRun: `{run_id[:8]}...`")


async def notify_approval_needed(action_class: str, ticket_title: str) -> None:
    await notify_discord(
        f"🔔 **承認待ち**: {action_class}\nチケット: {ticket_title}\n"
        "TaskManagedAI UI で承認してください。"
    )
