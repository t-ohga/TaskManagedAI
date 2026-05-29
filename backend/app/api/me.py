"""Current actor / current project resolution endpoint (SP-012-11.1 BL-TCU-013).

Codex PR #121 R1 F-PR121-002/003 (P1) carry-over fix:
DEFAULT_PROJECT_ID hardcode を frontend から排除し、session 経由 current
project を resolve する path を提供。session の actor が属する tenant の
first project (created_at 順) を current project として返す。

multi-tenant + multi-project への将来拡張は workspace / actor membership
table 追加後に拡張 (現状は single-tenant single-project の simplification)。

invariant:
- server-owned-boundary §1: tenant_id / actor_id は session 経由 resolve、
  caller-supplied 経路なし
- response: raw secret なし (project_id / slug / name / workspace_id / tenant_id のみ)
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.dependencies.api_capability_token import maybe_require_cli_capability
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.project import Project
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.repositories.project import ProjectRepository
from backend.app.services.policy.autonomy_settings import (
    AutonomyExpectationMismatch,
    ProjectAutonomySettingsService,
)

router = APIRouter(prefix="/api/v1/me", tags=["me"])


class CurrentProjectResponse(BaseModel):
    """Current actor's resolved project.

    SP-012-11.1 BL-TCU-013: single-project mode で actor の tenant 内 first project
    を返す。multi-project 化は将来の `actor_project_membership` table 追加で拡張。
    """

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: int
    project_id: UUID
    workspace_id: UUID
    slug: str
    name: str


class ProjectListItem(BaseModel):
    """Read-only project metadata safe for Settings UI."""

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: int
    project_id: UUID
    workspace_id: UUID
    slug: str
    name: str
    description: str | None
    status: str
    policy_profile: str
    autonomy_level: AutonomyLevel


class ProjectListResponse(BaseModel):
    current_project_id: UUID
    projects: list[ProjectListItem]


class ProjectAutonomySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autonomy_level: AutonomyLevel
    # Codex adversarial R7/R8 (HIGH): autonomy_level は AI 権限制御。stale な baseline からの
    # re-escalation を防ぐため compare-and-swap を **必須** にする。caller (frontend / CLI /
    # 直接 API すべて) が編集の基にした現在値を必ず宣言する。row lock 後の DB current と比較し、
    # 不一致なら 409 で拒否する。required にすることで「expected を省略して CAS をすり抜ける」
    # 経路を塞ぐ (R8: opt-in だと CLI / 旧 client が re-escalation できた)。authority 値ではなく
    # If-Match 相当の concurrency token であり、server-owned-boundary に反しない (server が実値を
    # 所有し、caller は期待値を申告するだけ)。
    expected_autonomy_level: AutonomyLevel


class ProjectProfileUpdate(BaseModel):
    """M-3 (ADR-00035): caller-editable project metadata のみ。

    policy_profile / autonomy_level / tenant_id / workspace_id は含めない
    (server-owned-boundary §1)。ProjectRepository が policy_profile / autonomy_level
    の caller payload を reject するため、本 schema は name / description のみ受ける。
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None

    @model_validator(mode="after")
    def _validate_name(self) -> ProjectProfileUpdate:
        """name は omit (= 変更なし) のみ許容し、explicit null / 空白のみは reject。

        Codex adversarial R1: `projects.name` は NOT NULL。`{"name": null}` を
        受理すると DB IntegrityError (500) になり、`{"name": "   "}` は空白名を
        通してしまう。omit と explicit null を model_fields_set で区別し、explicit
        null / blank を 422 で弾く。受理時は strip 済みの name を保持する。
        """
        if "name" not in self.model_fields_set:
            return self
        if self.name is None:
            raise ValueError(
                "name は null にできません (変更しない場合はフィールド自体を省略してください)"
            )
        stripped = self.name.strip()
        if not stripped:
            raise ValueError("name は空白のみにできません")
        object.__setattr__(self, "name", stripped)
        return self


def _to_project_item(project: Project) -> ProjectListItem:
    return ProjectListItem(
        tenant_id=project.tenant_id,
        project_id=project.id,
        workspace_id=project.workspace_id,
        slug=project.slug,
        name=project.name,
        description=project.description,
        status=project.status,
        policy_profile=project.policy_profile,
        autonomy_level=project.autonomy_level,
    )


@router.get("/current_project", response_model=CurrentProjectResponse)
async def get_current_project_endpoint(
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CurrentProjectResponse:
    """Resolve current project for the authenticated actor.

    Single-project mode: return tenant 内 first project (order by created_at)。
    """
    stmt = (
        select(Project)
        .where(Project.tenant_id == tenant_id)
        .order_by(Project.created_at, Project.slug)
        .limit(1)
    )
    project = (await session.execute(stmt)).scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no project found for tenant",
        )

    return CurrentProjectResponse(
        tenant_id=tenant_id,
        project_id=project.id,
        workspace_id=project.workspace_id,
        slug=project.slug,
        name=project.name,
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_current_actor_projects_endpoint(
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProjectListResponse:
    """List current tenant projects for the authenticated actor.

    P0.1 still uses single-tenant membership semantics. Project switching is
    read-only in the UI until an actor-project membership table exists.
    """
    result = await session.execute(
        select(Project)
        .where(Project.tenant_id == tenant_id)
        .order_by(Project.created_at, Project.slug)
    )
    projects = list(result.scalars())
    if not projects:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no project found for tenant",
        )

    return ProjectListResponse(
        current_project_id=projects[0].id,
        projects=[_to_project_item(project) for project in projects],
    )


@router.patch("/projects/{project_id}/autonomy", response_model=ProjectListItem)
async def update_project_autonomy_endpoint(
    project_id: UUID,
    payload: ProjectAutonomySettingsUpdate,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProjectListItem:
    """Update caller-visible autonomy_level only.

    ``policy_profile`` remains server-owned and is resolved by
    ProjectAutonomySettingsService. The request schema forbids extra fields, so
    callers cannot smuggle a policy_profile setter into this surface.

    M-3 (ADR-00035): autonomy_level 変更を ``config_changed`` audit event に残す
    (現状の audit gap を解消)。autonomy_level / policy_profile は enum で自由入力では
    ないため旧→新値を payload に含めてよい。

    Codex adversarial R7/R8/R9 (HIGH): compare-and-swap (CAS) は実際の mutation 境界である
    ``ProjectAutonomySettingsService.update_autonomy_level`` で **必須** に強制する (row lock +
    expected との比較)。本 endpoint はその単一 CAS writer に委譲し、結果を HTTP に写像する
    (None -> 404 / ``AutonomyExpectationMismatch`` -> 409)。endpoint 側に CAS の二重実装は
    持たない (no-CAS writer を production path から排除)。
    """

    service = ProjectAutonomySettingsService(session)
    try:
        result = await service.update_autonomy_level(
            tenant_id=tenant_id,
            project_id=project_id,
            autonomy_level=payload.autonomy_level,
            expected_autonomy_level=payload.expected_autonomy_level,
        )
    except AutonomyExpectationMismatch as exc:
        # stale な baseline からの AI 権限 re-escalation を 409 で拒否する。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "autonomy_level was changed by another update; "
                "reload the current value and retry"
            ),
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found for tenant",
        )

    project = result.project
    # Codex adversarial R2 (HIGH): autonomy_level が実際に遷移した場合のみ config_changed
    # audit を記録する。no-op / retry で偽の permission transition を残すと、AI 権限制御
    # (ADR Gate #4) の audit が実遷移と乖離する。AI 権限の audit は実遷移と 1:1 対応させる。
    if result.changed:
        audit_event = AuditEvent(
            tenant_id=tenant_id,
            event_type="config_changed",
            actor_id=actor_id,
            event_payload={
                "rls_ready": True,
                "project_id": str(project_id),
                "changed_fields": ["autonomy_level"],
                "previous_autonomy_level": result.previous_autonomy_level,
                "new_autonomy_level": project.autonomy_level,
                "resolved_policy_profile": project.policy_profile,
            },
        )
        session.add(audit_event)
    await session.commit()
    return _to_project_item(project)


@router.patch("/projects/{project_id}/profile", response_model=ProjectListItem)
async def update_project_profile_endpoint(
    project_id: UUID,
    payload: ProjectProfileUpdate,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProjectListItem:
    """M-3 (ADR-00035): caller-editable な project metadata (name / description) を更新。

    policy_profile / autonomy_level は本 endpoint で扱わない。ProjectRepository が
    caller-supplied policy_profile / autonomy_level を reject するため、payload に
    含めても弾かれる (server-owned-boundary §1)。audit payload は ``changed_fields``
    のみ残し、name / description の本文値は永続化しない (秘密情報・長文保護)。
    """

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty update payload",
        )

    # Codex adversarial R3 (MEDIUM): audit の changed_fields は「送信された field」ではなく
    # 「実際に値が変わった field」を表す。name / description の本文値を audit に残さない
    # 設計では changed_fields が唯一の手がかりであり、過大記述すると incident review で実変更
    # と no-op / retry (基本情報フォームが name を常に送る等) を区別できなくなる。更新前の
    # 現在値を row lock 付きで取得して比較し、実 delta のみ更新・audit する。column select で
    # 取得するため ORM identity map を汚さず、後続 repo.update の RETURNING は更新後値を返す。
    locked = (
        await session.execute(
            select(Project.name, Project.description)
            .where(Project.tenant_id == tenant_id, Project.id == project_id)
            .with_for_update()
        )
    ).one_or_none()
    if locked is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found for tenant",
        )
    current_name, current_description = locked
    current_values: dict[str, str | None] = {
        "name": current_name,
        "description": current_description,
    }
    actual_changes = {
        field: value
        for field, value in update_data.items()
        if current_values.get(field) != value
    }

    repo = ProjectRepository(session)

    if not actual_changes:
        # 同一値の再送信 (no-op): 更新も audit もしない。row lock は commit で解放する。
        project = await repo.get(tenant_id=tenant_id, id=project_id)
        await session.commit()
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project not found for tenant",
            )
        return _to_project_item(project)

    try:
        project = await repo.update(tenant_id=tenant_id, id=project_id, payload=actual_changes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found for tenant",
        )

    audit_event = AuditEvent(
        tenant_id=tenant_id,
        event_type="config_changed",
        actor_id=actor_id,
        event_payload={
            "rls_ready": True,
            "project_id": str(project_id),
            # name / description の本文値は audit に残さない (実 delta の changed_fields のみ)
            "changed_fields": sorted(actual_changes.keys()),
        },
    )
    session.add(audit_event)
    await session.commit()
    return _to_project_item(project)
