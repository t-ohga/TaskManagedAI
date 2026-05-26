"""RepoProxy AgentRunEvent integration for Draft PR creation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.domain.agent_runtime.event_type import AgentRunEventType
from backend.app.repositories.agent_run_event import AgentRunEventRepository
from backend.app.services.repoproxy.repoproxy import DraftPRBinding, DraftPRResult

_GIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")
_REPO_FULL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class RepoPROpenedEventDenyReason(StrEnum):
    """Reasons a Draft PR result cannot produce a repo_pr_opened event."""

    PR_NOT_CREATED = "pr_not_created"
    PR_RESULT_INCOMPLETE = "pr_result_incomplete"
    NON_DRAFT_PR = "non_draft_pr"


@dataclass(frozen=True, slots=True)
class RepoPROpenedEventPayload:
    """Canonical safe payload for AgentRunEvent `repo_pr_opened`."""

    pr_number: int
    pr_url: str
    repo_full_name: str
    branch: str
    head_sha: str
    draft: bool
    created_at: str
    approval_id: str
    source: str = "repoproxy"

    def to_dict(self) -> dict[str, object]:
        return {
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "repo_full_name": self.repo_full_name,
            "branch": self.branch,
            "head_sha": self.head_sha,
            "draft": self.draft,
            "created_at": self.created_at,
            "approval_id": self.approval_id,
            "source": self.source,
        }


class RepoPREventRepository(Protocol):
    """Append-only event repository boundary for tests and production."""

    async def append_event(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        event_type: AgentRunEventType,
        event_payload: dict[str, object],
        actor_id: UUID,
        idempotency_key: str | None = None,
        expected_previous_seq_no: int | None = None,
    ) -> AgentRunEvent: ...


class RepoPROpenedEventWriter:
    """Append `repo_pr_opened` after a successful RepoProxy Draft PR creation."""

    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        event_repository: RepoPREventRepository | None = None,
    ) -> None:
        if event_repository is None and session is None:
            raise ValueError("session or event_repository is required.")
        if event_repository is not None:
            self._event_repository = event_repository
        else:
            if session is None:
                raise ValueError("session is required when event_repository is omitted.")
            self._event_repository = AgentRunEventRepository(session)

    async def append_from_result(
        self,
        *,
        binding: DraftPRBinding,
        actor_id: UUID,
        result: DraftPRResult,
        created_at: datetime | None = None,
        expected_previous_seq_no: int | None = None,
    ) -> AgentRunEvent | RepoPROpenedEventDenyReason:
        payload = build_repo_pr_opened_payload(
            binding=binding,
            result=result,
            created_at=created_at,
        )
        if isinstance(payload, RepoPROpenedEventDenyReason):
            return payload
        from uuid import UUID as _UUID
        run_id = _UUID(binding.agent_run_id) if isinstance(binding.agent_run_id, str) else binding.agent_run_id
        return await self._event_repository.append_event(
            tenant_id=binding.tenant_id,
            run_id=run_id,
            event_type="repo_pr_opened",
            event_payload=payload.to_dict(),
            actor_id=actor_id,
            idempotency_key=_idempotency_key(binding=binding, pr_number=payload.pr_number),
            expected_previous_seq_no=expected_previous_seq_no,
        )


def build_repo_pr_opened_payload(
    *,
    binding: DraftPRBinding,
    result: DraftPRResult,
    created_at: datetime | None = None,
) -> RepoPROpenedEventPayload | RepoPROpenedEventDenyReason:
    """Build a raw-token-free `repo_pr_opened` payload from server-owned result fields."""

    if result.deny_reason is not None or result.pr_number is None:
        return RepoPROpenedEventDenyReason.PR_NOT_CREATED
    if result.draft is not True:
        return RepoPROpenedEventDenyReason.NON_DRAFT_PR

    repo_full_name = result.repo_full_name
    branch = result.branch
    head_sha = result.head_sha
    if (
        not isinstance(repo_full_name, str)
        or _REPO_FULL_NAME_RE.fullmatch(repo_full_name) is None
        or not isinstance(branch, str)
        or not branch
        or not isinstance(head_sha, str)
        or _GIT_SHA_RE.fullmatch(head_sha) is None
        or result.pr_number < 1
    ):
        return RepoPROpenedEventDenyReason.PR_RESULT_INCOMPLETE

    timestamp = (created_at or datetime.now(tz=UTC)).astimezone(UTC).isoformat()
    return RepoPROpenedEventPayload(
        pr_number=result.pr_number,
        pr_url=f"https://github.com/{repo_full_name}/pull/{result.pr_number}",
        repo_full_name=repo_full_name,
        branch=branch,
        head_sha=head_sha,
        draft=True,
        created_at=timestamp,
        approval_id=str(binding.approval_id),
    )


def _idempotency_key(*, binding: DraftPRBinding, pr_number: int) -> str:
    return f"repoproxy:repo_pr_opened:{binding.agent_run_id}:{pr_number}"


async def append_repo_pr_opened_event(
    session: AsyncSession,
    *,
    binding: DraftPRBinding,
    actor_id: UUID,
    result: DraftPRResult,
    created_at: datetime | None = None,
    expected_previous_seq_no: int | None = None,
) -> AgentRunEvent | RepoPROpenedEventDenyReason:
    """Convenience wrapper for the standard SQLAlchemy repository path."""

    return await RepoPROpenedEventWriter(session).append_from_result(
        binding=binding,
        actor_id=actor_id,
        result=result,
        created_at=created_at,
        expected_previous_seq_no=expected_previous_seq_no,
    )


__all__ = [
    "RepoPROpenedEventDenyReason",
    "RepoPROpenedEventPayload",
    "RepoPROpenedEventWriter",
    "append_repo_pr_opened_event",
    "build_repo_pr_opened_payload",
]
