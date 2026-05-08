from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.actor import Actor
from backend.app.repositories.base import BaseRepository

HUMAN_DEFAULT_ACTOR_ID = "human:default"


class ActorRepository(BaseRepository[Actor]):
    def __init__(self, session: AsyncSession, tenant_id: int | None = None) -> None:
        super().__init__(session, Actor, tenant_id=tenant_id)

    async def get_human_default(self, tenant_id: int) -> Actor:
        await self._ensure_tenant_context(tenant_id)
        stmt = select(Actor).where(
            Actor.tenant_id == tenant_id,
            Actor.actor_type == "human",
            Actor.actor_id == HUMAN_DEFAULT_ACTOR_ID,
        )
        actor = await self.session.scalar(stmt)
        if actor is None:
            raise LookupError("Default human actor is not seeded for this tenant.")
        return actor


__all__ = ["ActorRepository", "HUMAN_DEFAULT_ACTOR_ID"]

