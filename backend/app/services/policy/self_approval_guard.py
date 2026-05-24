from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.actor import Actor
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.domain.policy.action_class import ActionClass

# ADR-00009 採用案: independent reviewer 必須 action class
INDEPENDENT_REVIEWER_REQUIRED_ACTIONS: frozenset[ActionClass] = frozenset(
    {
        "merge",
        "deploy",
    }
)


@dataclass(frozen=True)
class _ActorIdentity:
    """delegated check 用の actor 正規化情報。"""

    actor_id: UUID
    impersonated_by: UUID | None

    @property
    def effective_human_actor_id(self) -> UUID:
        """impersonating actor は effective human (impersonated_by) を、
        非 impersonating actor は自身を返す。
        """

        return self.impersonated_by if self.impersonated_by is not None else self.actor_id


class SelfApprovalGuardService:
    """approval decision 時に self-approval + delegated actor を reject する guard。"""

    @staticmethod
    def assert_not_self_approval(
        approval: ApprovalRequest,
        decided_by_actor_id: UUID,
    ) -> None:
        """approval の requested_by_actor_id と decided_by_actor_id が一致しないことを assert。"""

        if approval.requested_by_actor_id == decided_by_actor_id:
            raise ValueError(
                "self-approval is forbidden: "
                f"requester {approval.requested_by_actor_id} cannot decide "
                f"on their own approval request {approval.id}"
            )

    async def assert_not_delegated_self_approval(
        self,
        session: AsyncSession,
        approval: ApprovalRequest,
        decided_by_actor_id: UUID,
    ) -> None:
        """F-002 (R2): requester / decider 両方の effective human を比較する両方向 check。

        impersonating actor は impersonated_by を effective human と見なし、
        independent reviewer required action では effective human が同一なら拒否。

        対応する攻撃 path:
        - 順方向: H requests, delegated actor by H decides → reject
        - 逆方向: delegated actor by H requests, H decides → reject
        - 両方 delegated: A delegated by H requests, B delegated by H decides → reject
        """

        # まず単純な self-approval (UUID 一致) を確認
        self.assert_not_self_approval(approval=approval, decided_by_actor_id=decided_by_actor_id)

        # independent reviewer required action 以外は delegated check skip
        if approval.action_class not in INDEPENDENT_REVIEWER_REQUIRED_ACTIONS:
            return

        await self.assert_not_delegated_same_human(
            session=session,
            approval=approval,
            decided_by_actor_id=decided_by_actor_id,
            action_description=(
                "independent-reviewer-required action "
                f"{approval.action_class!r}"
            ),
        )

    async def assert_not_delegated_same_human(
        self,
        session: AsyncSession,
        approval: ApprovalRequest,
        decided_by_actor_id: UUID,
        action_description: str,
    ) -> None:
        """Reject decisions where requester and decider resolve to the same human."""

        self.assert_not_self_approval(approval=approval, decided_by_actor_id=decided_by_actor_id)

        # requester / decider の両 actor を一括取得 (両方向 check)
        result = await session.execute(
            select(Actor.id, Actor.impersonated_by).where(
                Actor.tenant_id == approval.tenant_id,
                Actor.id.in_([approval.requested_by_actor_id, decided_by_actor_id]),
            )
        )
        rows = result.all()
        identities: dict[UUID, _ActorIdentity] = {
            row[0]: _ActorIdentity(actor_id=row[0], impersonated_by=row[1]) for row in rows
        }

        requester = identities.get(approval.requested_by_actor_id)
        decider = identities.get(decided_by_actor_id)
        if requester is None or decider is None:
            # actor row が見つからない場合は明示的に reject (DB FK が保証する想定だが defense-in-depth)
            raise ValueError(
                "delegated self-approval check failed: "
                f"requester or decider actor not found for tenant {approval.tenant_id}"
            )

        # effective human が同一なら reject (両方向)
        if requester.effective_human_actor_id == decider.effective_human_actor_id:
            raise ValueError(
                f"delegated self-approval forbidden for {action_description}: "
                f"requester {approval.requested_by_actor_id} (effective human "
                f"{requester.effective_human_actor_id}) and decider {decided_by_actor_id} "
                f"(effective human {decider.effective_human_actor_id}) share the same human; "
                f"approval {approval.id} requires an independent reviewer"
            )


__all__ = ["SelfApprovalGuardService", "INDEPENDENT_REVIEWER_REQUIRED_ACTIONS"]
