from __future__ import annotations

from collections.abc import MutableMapping


async def noop_task(ctx: MutableMapping[str, object]) -> dict[str, str]:
    request_id = str(ctx.get("request_id", "worker"))
    return {
        "status": "ok",
        "task": "noop",
        "request_id": request_id,
    }

