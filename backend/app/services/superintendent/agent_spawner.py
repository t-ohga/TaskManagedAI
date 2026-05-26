"""Agent process spawner: starts AI agent subprocesses.

Each agent runs as a separate process (claude / codex / custom)
with its own MCP client config pointing to TaskManagedAI.

Security:
- Subprocess env is scrubbed (no raw secrets)
- Agent process runs in project-scoped workdir
- Kill switch terminates process group
"""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

AgentProvider = Literal["claude", "codex", "custom"]

SPAWN_TIMEOUT_SECONDS = 30
STOP_GRACE_SECONDS = 10

_ENV_SCRUB_KEYS = frozenset({
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "SOPS_AGE_KEY_FILE",
    "TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET",
    "TASKMANAGEDAI_DEV_LOGIN_TOKEN",
})


@dataclass
class SpawnedAgent:
    agent_id: UUID
    provider: AgentProvider
    process: asyncio.subprocess.Process | None = None
    pid: int | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    exit_code: int | None = None


_active_agents: dict[UUID, SpawnedAgent] = {}


def _build_agent_command(provider: AgentProvider, project_dir: str) -> list[str]:
    if provider == "claude":
        return ["claude", "--mcp-config", ".mcp.json", "--print", "--dangerously-skip-permissions"]
    if provider == "codex":
        return ["codex", "exec", "-C", project_dir, "--sandbox", "read-only"]
    return ["echo", "custom-agent-stub"]


def _build_safe_env(project_dir: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _ENV_SCRUB_KEYS}
    env["TASKMANAGEDAI_AGENT_MODE"] = "true"
    env["TASKMANAGEDAI_PROJECT_DIR"] = project_dir
    return env


async def spawn_agent(
    agent_id: UUID,
    provider: AgentProvider,
    project_dir: str,
) -> SpawnedAgent:
    cmd = _build_agent_command(provider, project_dir)
    env = _build_safe_env(project_dir)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=project_dir,
        start_new_session=True,
    )

    agent = SpawnedAgent(
        agent_id=agent_id,
        provider=provider,
        process=proc,
        pid=proc.pid,
        started_at=datetime.now(UTC),
    )
    _active_agents[agent_id] = agent
    return agent


async def stop_agent(agent_id: UUID) -> SpawnedAgent | None:
    agent = _active_agents.get(agent_id)
    if agent is None or agent.process is None:
        return agent

    try:
        agent.process.terminate()
        await asyncio.wait_for(agent.process.wait(), timeout=STOP_GRACE_SECONDS)
    except (TimeoutError, ProcessLookupError):
        try:
            agent.process.kill()
            await agent.process.wait()
        except ProcessLookupError:
            pass

    agent.stopped_at = datetime.now(UTC)
    agent.exit_code = agent.process.returncode
    return agent


async def kill_all_agents() -> list[UUID]:
    killed = []
    for agent_id, agent in list(_active_agents.items()):
        if agent.process and agent.process.returncode is None:
            try:
                os.killpg(os.getpgid(agent.process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            agent.stopped_at = datetime.now(UTC)
            agent.exit_code = -9
            killed.append(agent_id)
    return killed


def list_agents() -> list[dict[str, object]]:
    return [
        {
            "agent_id": str(a.agent_id),
            "provider": a.provider,
            "pid": a.pid,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "stopped_at": a.stopped_at.isoformat() if a.stopped_at else None,
            "running": a.process is not None and a.process.returncode is None,
        }
        for a in _active_agents.values()
    ]
