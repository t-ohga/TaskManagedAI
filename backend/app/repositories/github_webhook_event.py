"""Read-side repository for github_webhook_events (ADR-00050 SP-028)。

project-scoped read feed: ``status='accepted'`` の event を repositories と join し、対象 project に属する
repository の event のみ返す。``status='quarantined'`` (repository_id NULL) は join で自然に除外される
(通常 feed 非表示、ADR-00050 §read endpoint)。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.github_webhook_event import GitHubWebhookEvent
from backend.app.db.models.repository import Repository

WEBHOOK_EVENT_FEED_MAX_LIMIT = 100


class GitHubWebhookEventRepository:
    """github_webhook_events の read-only repository。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_accepted_for_project(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        repository_id: UUID | None = None,
        limit: int = 50,
    ) -> list[GitHubWebhookEvent]:
        """project 配下の accepted event を received_at 降順で返す (tenant + project boundary を join で enforce)。

        ``repository_id`` 指定時は当該 project 内に属する repository に限定 (別 project の repo_id を指定しても
        join 条件で 0 件、cross-project leak 防止)。
        """

        bounded_limit = max(1, min(limit, WEBHOOK_EVENT_FEED_MAX_LIMIT))
        stmt = (
            select(GitHubWebhookEvent)
            .join(
                Repository,
                (GitHubWebhookEvent.tenant_id == Repository.tenant_id)
                & (GitHubWebhookEvent.repository_id == Repository.id),
            )
            .where(
                GitHubWebhookEvent.tenant_id == tenant_id,
                Repository.project_id == project_id,
                GitHubWebhookEvent.status == "accepted",
            )
            .order_by(
                GitHubWebhookEvent.received_at.desc(),
                GitHubWebhookEvent.id.desc(),
            )
            .limit(bounded_limit)
        )
        if repository_id is not None:
            stmt = stmt.where(GitHubWebhookEvent.repository_id == repository_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


__all__ = [
    "WEBHOOK_EVENT_FEED_MAX_LIMIT",
    "GitHubWebhookEventRepository",
]
