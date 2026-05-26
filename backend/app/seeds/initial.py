from __future__ import annotations

from typing import Final, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models.acceptance_criteria import AcceptanceCriteria
from backend.app.db.models.actor import Actor
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

TENANT_TABLE: Final[sa.Table] = cast(sa.Table, Tenant.__table__)
ACTOR_TABLE: Final[sa.Table] = cast(sa.Table, Actor.__table__)
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


__all__ = [
    "DEFAULT_ACCEPTANCE_CRITERIA_DESCRIPTION",
    "DEFAULT_ACCEPTANCE_CRITERIA_ID",
    "DEFAULT_ACCEPTANCE_CRITERIA_STATUS",
    "DEFAULT_ACTOR_ID",
    "DEFAULT_ACTOR_STABLE_ID",
    "DEFAULT_ACTOR_TYPE",
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
    "seed_initial",
]

