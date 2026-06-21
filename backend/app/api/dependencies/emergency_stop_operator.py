"""Emergency-stop operator gate (SP-PHASE1 B3、ADR-00048 §C/A-10)。

``require_emergency_stop_operator``: human-only emergency-stop の操作境界を fail-closed で enforce する。
ADR-00048 §C の operator gate 5 条件:

1. **authenticated session** (``request.state.authenticated is True``)。dev/test の
   ``DevActorContextMiddleware`` は cookie 無しでも default actor を seed し authenticated=False とするため
   明示的に弾く (未ログイン操作を拒否)。
2. **DB resolve した ``actor_type == 'human'``** (agent/service/provider/github_app は不可)。
3. **configured owner** (stable ``actor_id == settings.default_actor_id``)。同一 tenant の別 human が
   勝手に発動できない (P0)。
4. **tenant context** を明示 (``get_tenant_id``)。
5. 上記いずれか不成立は fail-closed (1 → 401、それ以外 → 403)。kill / latch engage は実行されない。

A-10: P0 では ``_require_authenticated_owner`` (me.py) と同一 owner gate (authenticated + human +
default owner) を流用し、別 emergency-stop role は新設しない (P0.1 で role 化を forward-compat 予約)。
本 dependency は me.py の owner gate と同じ判定を emergency-stop 専用の detail message で行う。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.me import _require_authenticated_owner


async def require_emergency_stop_operator(
    request: Request,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> UUID:
    """emergency-stop engage/clear/status の human-only operator gate (fail-closed)。

    ADR-00048 §C: kill switch は human surface (FastAPI) に置き、MCP には露出しない。本 gate は
    authenticated + human + configured owner を要求し、unauthenticated → 401 / その他 (別 human /
    service / agent / provider / github_app) → 403 で fail-closed。kill switch は approval 経路外で
    self-approval invariant に干渉しない。
    """
    return await _require_authenticated_owner(
        request,
        actor_id,
        tenant_id,
        session,
        unauthenticated_detail=(
            "emergency-stop requires an authenticated owner session"
        ),
        forbidden_detail="emergency-stop is restricted to the project owner",
    )


__all__ = ["require_emergency_stop_operator"]
