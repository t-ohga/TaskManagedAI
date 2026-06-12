from __future__ import annotations

from decimal import Decimal
from typing import Final, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.acceptance_criteria import AcceptanceCriteria
from backend.app.db.models.actor import Actor
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.approval_request import ApprovalRequest
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.principal import Principal
from backend.app.db.models.project import Project
from backend.app.db.models.repository import Repository
from backend.app.db.models.tenant import Tenant
from backend.app.db.models.ticket import Ticket
from backend.app.db.models.workspace import Workspace

DEFAULT_TENANT_ID: Final[int] = 1
DEFAULT_TENANT_NAME: Final[str] = "default-tenant"
DEFAULT_ACTOR_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_ACTOR_STABLE_ID: Final[str] = "human:default"
DEFAULT_ACTOR_TYPE: Final[str] = "human"
DEFAULT_USER_NAME: Final[str] = "Dev User"
DEFAULT_PRINCIPAL_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000002")
DEFAULT_WORKSPACE_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000003")
DEFAULT_WORKSPACE_SLUG: Final[str] = "default-workspace"
DEFAULT_WORKSPACE_NAME: Final[str] = "default-workspace"
DEFAULT_PROJECT_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000004")
DEFAULT_PROJECT_SLUG: Final[str] = "default-project"
DEFAULT_PROJECT_NAME: Final[str] = "default-project"
DEFAULT_PROJECT_STATUS: Final[str] = "active"
DEFAULT_REPOSITORY_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000005")
DEFAULT_REPOSITORY_PROVIDER: Final[str] = "github"
DEFAULT_REPOSITORY_EXTERNAL_ID: Final[str] = "0"
DEFAULT_REPOSITORY_OWNER_NAME: Final[str] = "taskmanagedai"
DEFAULT_REPOSITORY_NAME: Final[str] = "placeholder"
DEFAULT_REPOSITORY_DEFAULT_BRANCH: Final[str] = "main"
DEFAULT_REPOSITORY_INSTALLATION_REF: Final[str | None] = None
DEFAULT_TICKET_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000006")
DEFAULT_TICKET_SLUG: Final[str] = "welcome"
DEFAULT_TICKET_TITLE: Final[str] = "Welcome to TaskManagedAI"
DEFAULT_TICKET_STATUS: Final[str] = "open"
DEFAULT_ACCEPTANCE_CRITERIA_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000007")
DEFAULT_ACCEPTANCE_CRITERIA_DESCRIPTION: Final[str] = "Sprint 1 が起動可能"
DEFAULT_ACCEPTANCE_CRITERIA_STATUS: Final[str] = "pending"
DEFAULT_AUDIT_EVENT_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000008")
DEFAULT_AUDIT_EVENT_TYPE: Final[str] = "seed_initialized"
# golden flow (SP-009) seed: agent actor が human approval を要求する pending approval。
# self-approval 禁止 (approval_requests_ck_self_approval) を満たすため requester は human ではなく
# agent actor とし、human (DEFAULT_ACTOR) が decider 候補として実際に承認 / 却下できる状態にする。
DEFAULT_AGENT_ACTOR_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000009")
DEFAULT_AGENT_ACTOR_STABLE_ID: Final[str] = "agent:default"
DEFAULT_AGENT_ACTOR_TYPE: Final[str] = "agent"
DEFAULT_AGENT_ACTOR_NAME: Final[str] = "Default Agent"
DEFAULT_APPROVAL_REQUEST_ID: Final[UUID] = UUID("00000000-0000-4000-8000-00000000000a")
DEFAULT_APPROVAL_ACTION_CLASS: Final[str] = "task_write"
DEFAULT_APPROVAL_RISK_LEVEL: Final[str] = "medium"
DEFAULT_APPROVAL_POLICY_VERSION: Final[str] = "v1"
DEFAULT_APPROVAL_STATUS: Final[str] = "pending"
DEFAULT_APPROVAL_RESOURCE_REF: Final[str] = f"ticket:{DEFAULT_TICKET_ID}"
# golden flow (SP-009) seed: 完了済み AgentRun + 追記専用 AgentRunEvent タイムライン。
# /runs と /runs/<id> を空でなくし、状態機械 (16 状態) / event_type enum に整合させる。
DEFAULT_AGENT_RUN_ID: Final[UUID] = UUID("00000000-0000-4000-8000-00000000000b")
DEFAULT_AGENT_RUN_STATUS: Final[str] = "completed"
DEFAULT_AGENT_RUN_COST_USD: Final[Decimal] = Decimal("0.0123")
DEFAULT_AGENT_RUN_TOKENS_INPUT: Final[int] = 1200
DEFAULT_AGENT_RUN_TOKENS_OUTPUT: Final[int] = 480
DEFAULT_RUN_EVENT_QUEUED_ID: Final[UUID] = UUID("00000000-0000-4000-8000-00000000000c")
DEFAULT_RUN_EVENT_RESPONDED_ID: Final[UUID] = UUID("00000000-0000-4000-8000-00000000000d")
DEFAULT_RUN_EVENT_COMPLETED_ID: Final[UUID] = UUID("00000000-0000-4000-8000-00000000000e")
# canonical run_queued payload は run→ticket binding を持つ。migration 0040 の downgrade preflight は
# 非 null な agent_runs.ticket_id が canonical run_queued event payload の ticket_id と lossless 一致
# することを要求する (不一致なら rollback 拒否)。実 run 作成 (bridge_run_create) と同形状にする。
DEFAULT_RUN_QUEUED_PAYLOAD: Final[dict[str, object]] = {
    "ticket_id": str(DEFAULT_TICKET_ID),
    "purpose": "golden-flow-seed",
    "project_id": str(DEFAULT_PROJECT_ID),
    "role_id": None,
    "parent_run_id": None,
}
DEFAULT_RUN_EVENT_PAYLOAD: Final[dict[str, object]] = {"note": "golden-flow-seed"}

TENANT_TABLE: Final[sa.Table] = cast(sa.Table, Tenant.__table__)
ACTOR_TABLE: Final[sa.Table] = cast(sa.Table, Actor.__table__)
AGENT_RUN_TABLE: Final[sa.Table] = cast(sa.Table, AgentRun.__table__)
AGENT_RUN_EVENT_TABLE: Final[sa.Table] = cast(sa.Table, AgentRunEvent.__table__)
APPROVAL_REQUEST_TABLE: Final[sa.Table] = cast(sa.Table, ApprovalRequest.__table__)
PRINCIPAL_TABLE: Final[sa.Table] = cast(sa.Table, Principal.__table__)
WORKSPACE_TABLE: Final[sa.Table] = cast(sa.Table, Workspace.__table__)
PROJECT_TABLE: Final[sa.Table] = cast(sa.Table, Project.__table__)
REPOSITORY_TABLE: Final[sa.Table] = cast(sa.Table, Repository.__table__)
TICKET_TABLE: Final[sa.Table] = cast(sa.Table, Ticket.__table__)
ACCEPTANCE_CRITERIA_TABLE: Final[sa.Table] = cast(sa.Table, AcceptanceCriteria.__table__)
AUDIT_EVENT_TABLE: Final[sa.Table] = cast(sa.Table, AuditEvent.__table__)


def _metadata(**extra: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "rls_ready": True,
        "seed_version": "sprint2",
    }
    metadata.update(extra)
    return metadata


async def seed_initial(session: AsyncSession) -> None:
    await session.execute(
        insert(TENANT_TABLE)
        .values(
            id=DEFAULT_TENANT_ID,
            name=DEFAULT_TENANT_NAME,
            metadata=_metadata(entity="tenant"),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(ACTOR_TABLE)
        .values(
            id=DEFAULT_ACTOR_ID,
            tenant_id=DEFAULT_TENANT_ID,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_id=DEFAULT_ACTOR_STABLE_ID,
            display_name=DEFAULT_USER_NAME,
            auth_context_hash=None,
            metadata=_metadata(entity="actor"),
            impersonated_by=None,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(PRINCIPAL_TABLE)
        .values(
            id=DEFAULT_PRINCIPAL_ID,
            tenant_id=DEFAULT_TENANT_ID,
            actor_id=DEFAULT_ACTOR_ID,
            principal_type="session",
            auth_context_hash="dev-login:human:default",
            metadata=_metadata(entity="principal"),
            expires_at=None,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(WORKSPACE_TABLE)
        .values(
            id=DEFAULT_WORKSPACE_ID,
            tenant_id=DEFAULT_TENANT_ID,
            slug=DEFAULT_WORKSPACE_SLUG,
            name=DEFAULT_WORKSPACE_NAME,
            owner_actor_id=DEFAULT_ACTOR_ID,
            metadata=_metadata(entity="workspace"),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(PROJECT_TABLE)
        .values(
            id=DEFAULT_PROJECT_ID,
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=DEFAULT_WORKSPACE_ID,
            slug=DEFAULT_PROJECT_SLUG,
            name=DEFAULT_PROJECT_NAME,
            status=DEFAULT_PROJECT_STATUS,
            policy_profile="default",
            metadata=_metadata(entity="project"),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(REPOSITORY_TABLE)
        .values(
            id=DEFAULT_REPOSITORY_ID,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            provider=DEFAULT_REPOSITORY_PROVIDER,
            external_id=DEFAULT_REPOSITORY_EXTERNAL_ID,
            owner_name=DEFAULT_REPOSITORY_OWNER_NAME,
            repo_name=DEFAULT_REPOSITORY_NAME,
            default_branch=DEFAULT_REPOSITORY_DEFAULT_BRANCH,
            installation_ref=DEFAULT_REPOSITORY_INSTALLATION_REF,
            metadata=_metadata(
                entity="repository",
                placeholder=True,
                integration_target="repo_proxy_github_app_sprint8",
            ),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(TICKET_TABLE)
        .values(
            id=DEFAULT_TICKET_ID,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            repository_id=None,
            slug=DEFAULT_TICKET_SLUG,
            title=DEFAULT_TICKET_TITLE,
            description=None,
            status=DEFAULT_TICKET_STATUS,
            priority=None,
            assignee_actor_id=None,
            created_by_actor_id=DEFAULT_ACTOR_ID,
            metadata=_metadata(entity="ticket"),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(ACCEPTANCE_CRITERIA_TABLE)
        .values(
            id=DEFAULT_ACCEPTANCE_CRITERIA_ID,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=DEFAULT_TICKET_ID,
            description=DEFAULT_ACCEPTANCE_CRITERIA_DESCRIPTION,
            status=DEFAULT_ACCEPTANCE_CRITERIA_STATUS,
            evidence_ref=None,
            metadata=_metadata(entity="acceptance_criteria"),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.execute(
        insert(AUDIT_EVENT_TABLE)
        .values(
            id=DEFAULT_AUDIT_EVENT_ID,
            tenant_id=DEFAULT_TENANT_ID,
            event_type=DEFAULT_AUDIT_EVENT_TYPE,
            event_payload=_metadata(entity="seed", initialized=True),
            actor_id=DEFAULT_ACTOR_ID,
            principal_id=DEFAULT_PRINCIPAL_ID,
            correlation_id="seed-initialized",
            trace_id=None,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    await session.flush()


async def seed_golden_flow_fixtures(session: AsyncSession) -> None:
    """SP-009 golden flow の E2E 用 fixture (agent actor + pending approval + 完了 run + events)。

    **test 環境専用** (``seeds.runner`` で ``environment == "test"`` の時のみ呼ばれる)。本番 seed に
    混ぜると ``/approvals`` にテスト承認が「本物の pending work」として露出し KPI / 監査に混ざるため
    分離する (Codex adversarial R2 [high])。base record (tenant / project / ticket / actor) が seed 済み
    である前提で、その上に golden-flow 用の actionable データを冪等追加する。
    """
    # golden flow approval の requester。AI / worker が作る approval は agent actor として記録する
    # (rules instincts §9)。human (DEFAULT_ACTOR) を requester にすると self-approval 禁止により
    # 唯一の human が approve / reject の双方を実行できず approval が永久に詰まるため、agent を使う。
    await session.execute(
        insert(ACTOR_TABLE)
        .values(
            id=DEFAULT_AGENT_ACTOR_ID,
            tenant_id=DEFAULT_TENANT_ID,
            actor_type=DEFAULT_AGENT_ACTOR_TYPE,
            actor_id=DEFAULT_AGENT_ACTOR_STABLE_ID,
            display_name=DEFAULT_AGENT_ACTOR_NAME,
            auth_context_hash=None,
            metadata=_metadata(entity="actor", role="golden_flow_requester"),
            impersonated_by=None,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    # /approvals に actionable な pending approval を 1 件用意する。resource_ref は seed ticket
    # (status='open') を指すため inbox の active-scope filter (is_approval_target_actionable) を
    # 通過する。decided_by / decided_at は null (pending)。
    await session.execute(
        insert(APPROVAL_REQUEST_TABLE)
        .values(
            id=DEFAULT_APPROVAL_REQUEST_ID,
            tenant_id=DEFAULT_TENANT_ID,
            run_id=None,
            action_class=DEFAULT_APPROVAL_ACTION_CLASS,
            resource_ref=DEFAULT_APPROVAL_RESOURCE_REF,
            risk_level=DEFAULT_APPROVAL_RISK_LEVEL,
            artifact_hash=None,
            diff_hash=None,
            policy_version=DEFAULT_APPROVAL_POLICY_VERSION,
            policy_pack_lock=None,
            provider_request_fingerprint=None,
            stale_after_event_seq=None,
            status=DEFAULT_APPROVAL_STATUS,
            requested_by_actor_id=DEFAULT_AGENT_ACTOR_ID,
            decided_by_actor_id=None,
            decided_at=None,
            rationale=None,
            metadata=_metadata(entity="approval_request"),
        )
        # state-repairing upsert: reused test DB で approve / reject 済みでも reseed で pending へ
        # 戻し golden-flow gate を deterministic に保つ (Codex adversarial R4 [medium])。
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "status": DEFAULT_APPROVAL_STATUS,
                "decided_by_actor_id": None,
                "decided_at": None,
                "rationale": None,
            },
        )
    )

    # 完了済み AgentRun。/runs に 1 件以上の run link を出し、/runs/<id> の AgentRunEvent
    # タイムラインを描画させる。status='completed' は terminal (blocked_reason は null)。
    # ticket_id は同一 (tenant, project) の seed ticket を指す。
    await session.execute(
        insert(AGENT_RUN_TABLE)
        .values(
            id=DEFAULT_AGENT_RUN_ID,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=DEFAULT_PROJECT_ID,
            ticket_id=DEFAULT_TICKET_ID,
            parent_run_id=None,
            status=DEFAULT_AGENT_RUN_STATUS,
            blocked_reason=None,
            error_code=None,
            error_summary=None,
            cost_usd=DEFAULT_AGENT_RUN_COST_USD,
            tokens_input=DEFAULT_AGENT_RUN_TOKENS_INPUT,
            tokens_output=DEFAULT_AGENT_RUN_TOKENS_OUTPUT,
            completed_at=sa.func.now(),
            role_id=None,
            role_scope=None,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )

    # 追記専用 AgentRunEvent タイムライン (seq_no 昇順)。canonical run_queued payload は
    # migration 0040 downgrade preflight (ticket_id lossless 一致) を満たすため ticket_id を含む。
    # event_payload は raw secret を含まない object。event_type は ck_event_type enum に整合する。
    for event_id, seq_no, event_type, payload in (
        (DEFAULT_RUN_EVENT_QUEUED_ID, 1, "run_queued", DEFAULT_RUN_QUEUED_PAYLOAD),
        (DEFAULT_RUN_EVENT_RESPONDED_ID, 2, "provider_responded", DEFAULT_RUN_EVENT_PAYLOAD),
        (DEFAULT_RUN_EVENT_COMPLETED_ID, 3, "run_completed", DEFAULT_RUN_EVENT_PAYLOAD),
    ):
        await session.execute(
            insert(AGENT_RUN_EVENT_TABLE)
            .values(
                id=event_id,
                tenant_id=DEFAULT_TENANT_ID,
                run_id=DEFAULT_AGENT_RUN_ID,
                seq_no=seq_no,
                event_type=event_type,
                event_payload=dict(payload),
                actor_id=DEFAULT_ACTOR_ID,
                idempotency_key=None,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )

    await session.flush()


__all__ = [
    "DEFAULT_ACCEPTANCE_CRITERIA_DESCRIPTION",
    "DEFAULT_ACCEPTANCE_CRITERIA_ID",
    "DEFAULT_ACCEPTANCE_CRITERIA_STATUS",
    "DEFAULT_ACTOR_ID",
    "DEFAULT_ACTOR_STABLE_ID",
    "DEFAULT_ACTOR_TYPE",
    "DEFAULT_AGENT_ACTOR_ID",
    "DEFAULT_AGENT_ACTOR_NAME",
    "DEFAULT_AGENT_ACTOR_STABLE_ID",
    "DEFAULT_AGENT_ACTOR_TYPE",
    "DEFAULT_AGENT_RUN_COST_USD",
    "DEFAULT_AGENT_RUN_ID",
    "DEFAULT_AGENT_RUN_STATUS",
    "DEFAULT_AGENT_RUN_TOKENS_INPUT",
    "DEFAULT_AGENT_RUN_TOKENS_OUTPUT",
    "DEFAULT_APPROVAL_ACTION_CLASS",
    "DEFAULT_APPROVAL_POLICY_VERSION",
    "DEFAULT_APPROVAL_REQUEST_ID",
    "DEFAULT_APPROVAL_RESOURCE_REF",
    "DEFAULT_APPROVAL_RISK_LEVEL",
    "DEFAULT_APPROVAL_STATUS",
    "DEFAULT_AUDIT_EVENT_ID",
    "DEFAULT_AUDIT_EVENT_TYPE",
    "DEFAULT_PRINCIPAL_ID",
    "DEFAULT_PROJECT_ID",
    "DEFAULT_PROJECT_NAME",
    "DEFAULT_PROJECT_SLUG",
    "DEFAULT_PROJECT_STATUS",
    "DEFAULT_REPOSITORY_DEFAULT_BRANCH",
    "DEFAULT_REPOSITORY_EXTERNAL_ID",
    "DEFAULT_REPOSITORY_ID",
    "DEFAULT_REPOSITORY_INSTALLATION_REF",
    "DEFAULT_REPOSITORY_NAME",
    "DEFAULT_REPOSITORY_OWNER_NAME",
    "DEFAULT_REPOSITORY_PROVIDER",
    "DEFAULT_RUN_EVENT_COMPLETED_ID",
    "DEFAULT_RUN_EVENT_PAYLOAD",
    "DEFAULT_RUN_EVENT_QUEUED_ID",
    "DEFAULT_RUN_EVENT_RESPONDED_ID",
    "DEFAULT_RUN_QUEUED_PAYLOAD",
    "DEFAULT_TENANT_ID",
    "DEFAULT_TENANT_NAME",
    "DEFAULT_TICKET_ID",
    "DEFAULT_TICKET_SLUG",
    "DEFAULT_TICKET_STATUS",
    "DEFAULT_TICKET_TITLE",
    "DEFAULT_USER_NAME",
    "DEFAULT_WORKSPACE_ID",
    "DEFAULT_WORKSPACE_NAME",
    "DEFAULT_WORKSPACE_SLUG",
    "seed_golden_flow_fixtures",
    "seed_initial",
]

