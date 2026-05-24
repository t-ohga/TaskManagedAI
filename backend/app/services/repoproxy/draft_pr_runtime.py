"""Runtime call-site wiring for RepoProxy Draft PR creation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.services.repoproxy.repo_pr_event import (
    RepoPROpenedEventDenyReason,
    RepoPROpenedEventWriter,
)
from backend.app.services.repoproxy.repoproxy import (
    DraftPRBinding,
    DraftPRResult,
    RepoProxy,
)


@dataclass(frozen=True, slots=True)
class DraftPRRuntimeResult:
    """Draft PR result plus the append-only `repo_pr_opened` event outcome."""

    draft_pr_result: DraftPRResult
    repo_pr_opened_event: AgentRunEvent | None
    event_deny_reason: RepoPROpenedEventDenyReason | None


class DraftPRRuntime:
    """Create Draft PRs through RepoProxy and append `repo_pr_opened` on success."""

    def __init__(
        self,
        *,
        repo_proxy: RepoProxy,
        event_writer: RepoPROpenedEventWriter,
    ) -> None:
        self._repo_proxy = repo_proxy
        self._event_writer = event_writer

    async def create_draft_pr(
        self,
        *,
        binding: DraftPRBinding,
        actor_id: UUID,
        created_at: datetime | None = None,
        expected_previous_seq_no: int | None = None,
    ) -> DraftPRRuntimeResult:
        result = await self._repo_proxy.create_draft_pr(binding)
        if result.deny_reason is not None or result.pr_number is None:
            return DraftPRRuntimeResult(
                draft_pr_result=result,
                repo_pr_opened_event=None,
                event_deny_reason=None,
            )

        event = await self._event_writer.append_from_result(
            binding=binding,
            actor_id=actor_id,
            result=result,
            created_at=created_at,
            expected_previous_seq_no=expected_previous_seq_no,
        )
        if isinstance(event, RepoPROpenedEventDenyReason):
            return DraftPRRuntimeResult(
                draft_pr_result=result,
                repo_pr_opened_event=None,
                event_deny_reason=event,
            )
        return DraftPRRuntimeResult(
            draft_pr_result=result,
            repo_pr_opened_event=event,
            event_deny_reason=None,
        )


__all__ = [
    "DraftPRRuntime",
    "DraftPRRuntimeResult",
]
