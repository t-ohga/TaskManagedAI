"""Discord notification helper for TaskManagedAI MCP tools.

Sends notifications to Discord via an **in-process** HTTP call (httpx).
Falls back to no-op if the Discord token is unavailable.

SP-034 (Codex R7 F-10): 以前は ``python -c`` subprocess で通知を送っていたが、subprocess の
``import httpx`` が project-local ``httpx.py`` / project-local ``.venv`` interpreter symlink に
hijack され token-bearing child が repo コードに token を読まれ得た。subprocess を全廃し
**in-process httpx** に寄せる (token は親 process memory に留まり child env / argv に出ない、
import-path / interpreter hijack の class を根本から無くす)。通知は引き続き best-effort
(token 不在 / HTTP 失敗は silent no-op、bounded timeout)。
"""

from __future__ import annotations

import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

DISCORD_CHANNEL_ID = os.environ.get(
    "TASKMANAGEDAI_DISCORD_CHANNEL", "1466673510444433428"
)

_DISCORD_API_BASE = "https://discord.com/api/v10"
_NOTIFY_TIMEOUT_SECONDS = 10.0

_NOTIFY_ENABLED = True


def _is_trusted_dependency_path(path: str | None) -> bool:
    """third-party module が信頼できる install location から load されているか。

    Codex R8 F-12 / R9 F-13: in-process httpx でも、MCP server が project context から起動されると
    project-local ``httpx.py`` が site-packages より先に import され得る。``httpx`` が
    ``site-packages`` / ``dist-packages`` 以外 (= project-local shadow 疑い) から来ている場合は
    token を使う通知を **fail-closed** で無効化する (best-effort 通知なので no-op が安全)。

    **限界 (R9 F-13、honest)**: 本 gate は post-import チェックのため、shadow した module の
    **import-time top-level code の実行自体は防げない** (token を env / ``~/.claude.json`` から読む
    余地は残る)。ただし repo の import path へ ``httpx.py`` を書ける攻撃者は ``discord_notify.py`` を
    含む backend 全モジュールを既に制御でき、token は server 全体と同等の露出 = **server コード完全性**
    の問題 (deployment / file 権限 layer、SP-034 scope 外)。本 gate は HTTP call 経路で token を
    untrusted httpx へ渡さない **defense-in-depth** に留める。
    """
    if not path:
        return False
    normalized = path.replace(os.sep, "/")
    return "site-packages/" in normalized or "dist-packages/" in normalized


#: httpx が信頼できる場所から load されているか (module load 時に一度評価)。
_HTTPX_TRUSTED = _is_trusted_dependency_path(getattr(httpx, "__file__", None))
if not _HTTPX_TRUSTED:
    logger.warning(
        "discord notify disabled: httpx resolved from an untrusted/project-local path (%s)",
        getattr(httpx, "__file__", None),
    )


def _resolve_discord_token() -> str:
    token = os.environ.get("DISCORD_TOKEN", "")
    if token:
        return token
    try:
        with open(os.path.expanduser("~/.claude.json")) as f:
            config = json.load(f)
        return str(
            config.get("mcpServers", {})
            .get("discord", {})
            .get("env", {})
            .get("DISCORD_TOKEN", "")
        )
    except Exception:
        return ""


async def notify_discord(message: str) -> bool:
    if not _NOTIFY_ENABLED:
        return False
    # Codex R8 F-12: httpx が project-local shadow 疑いなら token を使う送信を fail-closed で抑止。
    if not _HTTPX_TRUSTED:
        return False
    token = _resolve_discord_token()
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=_NOTIFY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{_DISCORD_API_BASE}/channels/{DISCORD_CHANNEL_ID}/messages",
                headers={
                    "Authorization": f"Bot {token}",
                    "Content-Type": "application/json",
                },
                json={"content": message},
            )
        return response.status_code < 300
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
    await notify_discord(
        f"{emoji} **AgentRun {status}**: {purpose}\nRun: `{run_id[:8]}...`"
    )


async def notify_approval_needed(action_class: str, ticket_title: str) -> None:
    await notify_discord(
        f"🔔 **承認待ち**: {action_class}\nチケット: {ticket_title}\n"
        "TaskManagedAI UI で承認してください。"
    )
