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

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.dependencies.api_capability_token import maybe_require_cli_capability
from backend.app.config import get_settings
from backend.app.db.models.actor import Actor
from backend.app.db.models.audit_event import AuditEvent
from backend.app.db.models.project import Project, ProjectStatus
from backend.app.db.models.secret_ref import SecretRef, SecretRefScope, SecretRefStatus
from backend.app.domain.policy.autonomy_level import AutonomyLevel
from backend.app.repositories.project import ProjectRepository
from backend.app.repositories.secret_ref import SecretRefRepository
from backend.app.repositories.ticket import (
    BulkDeleteCountMismatch,
    ProjectArchivedError,
    ProjectNotFoundError,
    TicketRepository,
)
from backend.app.schemas.ticket import TicketImportItem
from backend.app.services.policy.archive_settings import (
    ArchiveExpectationMismatch,
    ProjectArchiveService,
)
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


class ProjectArchiveUpdate(BaseModel):
    """Q-4 (ADR-00037): プロジェクト archive/unarchive toggle。

    ``archived=True`` で active->archived、``False`` で archived->active (reversible soft toggle、
    hard delete しない)。``expected_status`` は M-3 autonomy CAS と同じ If-Match 相当の concurrency
    token: 編集の基にした現在 status を申告し、row lock 後の DB current と不一致なら 409。stale
    baseline からの誤 toggle (二重 archive / 競合 unarchive) を service 境界で防ぐ (authority 値では
    なく server-owned-boundary に反しない)。
    """

    model_config = ConfigDict(extra="forbid")

    archived: bool
    expected_status: ProjectStatus


class BulkSoftDeleteRequest(BaseModel):
    """Q-3 (ADR-00037): project 内 active 全 ticket の一括 soft-delete request。

    ``expected_active_count`` は二段階確認の最終段の CAS: UI で確認した active 件数を申告し、endpoint が
    DB current と比較して mismatch なら 409 (concurrent な追加/削除で意図しない件数を削除するのを防ぐ)。
    """

    model_config = ConfigDict(extra="forbid")

    expected_active_count: int = Field(ge=0)


class BulkSoftDeleteResponse(BaseModel):
    # no-op (active 0 件) は batch を発行しないため None (Codex adversarial #3、phantom batch 防止)。
    deleted_batch_id: UUID | None
    soft_deleted_count: int


class RestoreBatchRequest(BaseModel):
    """Q-3 (ADR-00037): 特定 deletion batch の復元 request。"""

    model_config = ConfigDict(extra="forbid")

    deleted_batch_id: UUID


class RestoreBatchResponse(BaseModel):
    restored_count: int


class ImportTicketsRequest(BaseModel):
    """Q-2 (ADR-00037): ticket 一括インポート request。

    ``tickets`` は 1-100 件の検証済み TicketImportItem。``dry_run=True`` は validation 結果のみ返し
    insert しない (preview)。
    """

    model_config = ConfigDict(extra="forbid")

    tickets: list[TicketImportItem] = Field(min_length=1, max_length=100)
    dry_run: bool = False


class ImportTicketsResponse(BaseModel):
    """Q-2 import の結果。本文値は含めず件数と衝突 slug のみ返す。"""

    dry_run: bool
    valid: bool
    imported_count: int
    in_payload_duplicate_slugs: list[str]
    existing_conflict_slugs: list[str]


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


class SecretRefListItem(BaseModel):
    """R-3 (ADR-00036): secret_refs の read-only インベントリ表示用 metadata。

    raw secret は DB に存在せず、本 schema は **明示 allowlist された公開 metadata のみ** 持つ。
    security topology (secret_uri / allowed_consumers / allowed_operations / owner_actor_id /
    metadata_ / runner_injectable) は意図的に含めない (Codex plan review R1 HIGH/MEDIUM)。
    SecretRef row からは ``_to_secret_ref_item`` で field 明示 mapping し、ORM/model dump は使わない
    (新カラム追加時に自動露出させない)。
    """

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    scope: SecretRefScope
    name: str
    version: str
    status: SecretRefStatus
    rotated: bool
    created_at: datetime
    updated_at: datetime
    deprecated_at: datetime | None
    revoked_at: datetime | None


class SecretRefListResponse(BaseModel):
    secret_refs: list[SecretRefListItem]


def _to_secret_ref_item(secret_ref: SecretRef) -> SecretRefListItem:
    # 明示 allowlist mapping。secret_uri / allowed_consumers / allowed_operations /
    # owner_actor_id / metadata_ / runner_injectable は意図的に写像しない。
    return SecretRefListItem(
        id=secret_ref.id,
        scope=secret_ref.scope,
        name=secret_ref.name,
        version=secret_ref.version,
        status=secret_ref.status,
        rotated=secret_ref.rotated_from_id is not None,
        created_at=secret_ref.created_at,
        updated_at=secret_ref.updated_at,
        deprecated_at=secret_ref.deprecated_at,
        revoked_at=secret_ref.revoked_at,
    )


async def _require_authenticated_owner(
    request: Request,
    actor_id: UUID,
    tenant_id: int,
    session: AsyncSession,
    *,
    unauthenticated_detail: str,
    forbidden_detail: str,
) -> UUID:
    """構成済み P0 owner のみを許可する共有 owner gate (fail-closed)。

    閲覧/破壊的操作の境界を実装で enforce する (Codex R1/R2/R3 HIGH)。条件 (すべて満たす必要あり):

    1. **認証済み session であること** (`request.state.authenticated is True`)。dev/test の
       `DevActorContextMiddleware` は cookie 無しでも default actor を seed し authenticated=False と
       するため、ここで明示的に弾く。これがないと local P0 path で未ログイン操作ができる。
    2. **構成済み P0 owner であること** (DB 上の actor_type=='human' AND stable actor_id ==
       settings.default_actor_id)。同一 tenant の別 human / service / agent / provider / github_app は
       403 (actor_type=='human' だけでは別 human が通過してしまう)。

    R-3 (ADR-00036) の secret inventory 閲覧と Q-2〜Q-4 (ADR-00037) の破壊的データ管理操作で共有する。
    `get_current_actor_id` は tenant 在籍のみ確認し authenticated フラグも owner も見ないため本 gate で
    補う。P0.1 multi-user 化では role/permission に置換する (位置を予約)。
    """
    if getattr(request.state, "authenticated", False) is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=unauthenticated_detail,
        )
    row = (
        await session.execute(
            select(Actor.actor_type, Actor.actor_id).where(
                Actor.tenant_id == tenant_id,
                Actor.id == actor_id,
            )
        )
    ).one_or_none()
    # Codex PR #298 (P2): owner 判定は session/actor context を確立した middleware と **同じ**
    # resolved settings を使う。app が injected Settings で構築された場合 (create_app(settings))、
    # middleware は app.state.settings の default_actor_id で actor を seed するため、ここで global
    # singleton を読むと injected と不一致になり構成済み owner を誤って reject しうる。
    # request.app.state.settings を優先し、無い場合のみ global にフォールバックする。
    settings = getattr(request.app.state, "settings", None) or get_settings()
    if (
        row is None
        or row.actor_type != "human"
        or row.actor_id != settings.default_actor_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=forbidden_detail,
        )
    return actor_id


async def require_secret_refs_viewer(
    request: Request,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> UUID:
    """R-3 (ADR-00036): secret inventory の閲覧境界を実装で enforce する (Codex R1/R2/R3 HIGH)。

    secret_refs metadata は raw secret でなくとも高価値 (鍵の存在・命名・対象・rotation を列挙可)。
    閲覧は構成済み P0 owner のみ (authenticated + human + default_actor_id)。owner 判定は共有
    `_require_authenticated_owner` に委譲し fail-closed (別 human / service / agent / provider /
    github_app / 未認証は 401/403)。
    """
    return await _require_authenticated_owner(
        request,
        actor_id,
        tenant_id,
        session,
        unauthenticated_detail="secret inventory requires an authenticated owner session",
        forbidden_detail="secret inventory is restricted to the project owner",
    )


async def require_project_owner(
    request: Request,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> UUID:
    """Q-2〜Q-4 (ADR-00037): 破壊的データ管理操作 (archive / bulk-soft-delete / restore / import)
    の owner gate。構成済み P0 owner のみ許可し、service / agent / provider / github_app / 別 human /
    未認証は fail-closed (401/403)。R-3 と同じ owner 判定を共有する。
    """
    return await _require_authenticated_owner(
        request,
        actor_id,
        tenant_id,
        session,
        unauthenticated_detail="this operation requires an authenticated owner session",
        forbidden_detail="this operation is restricted to the project owner",
    )


@router.get("/secret-refs", response_model=SecretRefListResponse)
async def list_secret_refs_endpoint(
    viewer_actor_id: UUID = Depends(require_secret_refs_viewer),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> SecretRefListResponse:
    """R-3 (ADR-00036): tenant 内 secret_refs の read-only インベントリ。

    raw secret は返さない (SecretBroker 非経由、capability token 発行なし)。明示 allowlist された
    公開 metadata のみ返し、security topology は含めない。閲覧境界は ``require_secret_refs_viewer``
    で enforce する (P0 human owner-only、service/agent 等は 403)。
    """
    repo = SecretRefRepository(session)
    secret_refs = await repo.list_all(tenant_id=tenant_id)
    return SecretRefListResponse(
        secret_refs=[_to_secret_ref_item(secret_ref) for secret_ref in secret_refs],
    )


@router.patch("/projects/{project_id}/archive", response_model=ProjectListItem)
async def update_project_archive_endpoint(
    project_id: UUID,
    payload: ProjectArchiveUpdate,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ProjectListItem:
    """Q-4 (ADR-00037): プロジェクトを archive/unarchive する破壊的操作 (ADR Gate #8)。

    owner gate (require_project_owner、構成済み P0 owner のみ) + compare-and-swap (expected_status)
    + 実遷移時のみ config_changed audit。archived <-> active は reversible soft toggle で hard delete
    しない。archived project への child-write (ticket create/update/import/bulk-delete/restore) の
    凍結は ``TicketRepository._assert_project_active`` が全 mutation 境界 (HTTP / MCP bridge /
    research-to-ticket) で enforce するため、本 endpoint は project.status の toggle のみを担う。

    M-3 autonomy CAS と同じく、CAS は実際の mutation 境界 (``ProjectArchiveService.set_archived``) で
    必須に強制し (row lock + expected との比較)、本 endpoint は単一 CAS writer に委譲して結果を HTTP
    に写像する (None -> 404 / ``ArchiveExpectationMismatch`` -> 409)。
    """
    service = ProjectArchiveService(session)
    try:
        result = await service.set_archived(
            tenant_id=tenant_id,
            project_id=project_id,
            archived=payload.archived,
            expected_status=payload.expected_status,
        )
    except ArchiveExpectationMismatch as exc:
        # stale な baseline からの誤 toggle (二重 archive / 競合 unarchive) を 409 で拒否する。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "project status was changed by another update; "
                "reload the current value and retry"
            ),
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found for tenant",
        )

    project = result.project
    # 実際に status が遷移した場合のみ config_changed audit を残す (no-op / 同一値の再送では残さない、
    # M-3 audit pattern と一致: audit は実遷移と 1:1)。
    if result.changed:
        audit_event = AuditEvent(
            tenant_id=tenant_id,
            event_type="config_changed",
            actor_id=owner_actor_id,
            event_payload={
                "rls_ready": True,
                "project_id": str(project_id),
                "changed_fields": ["status"],
                "previous_status": result.previous_status,
                "new_status": project.status,
            },
        )
        session.add(audit_event)
    await session.commit()
    return _to_project_item(project)


@router.post(
    "/projects/{project_id}/tickets/bulk-soft-delete",
    response_model=BulkSoftDeleteResponse,
)
async def bulk_soft_delete_tickets_endpoint(
    project_id: UUID,
    payload: BulkSoftDeleteRequest,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> BulkSoftDeleteResponse:
    """Q-3 (ADR-00037): project 内 active 全 ticket を soft-delete する破壊的操作 (ADR Gate #8)。

    owner gate + ``expected_active_count`` CAS (二段階確認の最終段: UI で確認した件数と DB current が
    不一致なら 409 で中断し再確認を要求、concurrent な追加/削除を検出)。archived project は 409
    (``ProjectArchivedError``)。新 deletion batch を発行し ``tickets_bulk_soft_deleted`` audit
    (batch_id + count + project_id、本文値は残さない) を残す。soft delete のみで hard delete せず、
    ``restore`` で batch 単位に復元できる。
    """
    repo = TicketRepository(session)
    # existence / archive freeze / CAS (expected_active_count) は repository 内で project row lock
    # 保持下に atomic 判定する (Codex adversarial #1/#2/#3)。endpoint で count → 別 statement の
    # update に分けると TOCTOU で stale baseline を 409 にできず、ユーザー未確認の ticket まで削除
    # しうるため、count↔update を lock 下で直列化する。
    try:
        deleted_batch_id, soft_deleted_count = await repo.bulk_soft_delete_in_project(
            tenant_id,
            project_id,
            expected_active_count=payload.expected_active_count,
            deleted_by_actor_id=owner_actor_id,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found for tenant",
        ) from exc
    except ProjectArchivedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project is archived; unarchive it before bulk-deleting tickets",
        ) from exc
    except BulkDeleteCountMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"expected {exc.expected} active tickets but found {exc.actual}; "
                "reload the current count and retry"
            ),
        ) from exc
    # 実際に削除した (soft_deleted_count > 0) ときのみ audit を残す。no-op (active 0 件) は batch を
    # 発行せず audit も残さない (実遷移と 1:1、Codex adversarial #3)。
    if soft_deleted_count > 0 and deleted_batch_id is not None:
        audit_event = AuditEvent(
            tenant_id=tenant_id,
            event_type="tickets_bulk_soft_deleted",
            actor_id=owner_actor_id,
            event_payload={
                "rls_ready": True,
                "project_id": str(project_id),
                "deleted_batch_id": str(deleted_batch_id),
                "soft_deleted_count": soft_deleted_count,
            },
        )
        session.add(audit_event)
    await session.commit()
    return BulkSoftDeleteResponse(
        deleted_batch_id=deleted_batch_id,
        soft_deleted_count=soft_deleted_count,
    )


@router.post(
    "/projects/{project_id}/tickets/restore",
    response_model=RestoreBatchResponse,
)
async def restore_tickets_batch_endpoint(
    project_id: UUID,
    payload: RestoreBatchRequest,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> RestoreBatchResponse:
    """Q-3 (ADR-00037): 特定 deletion batch を復元する破壊的操作の逆操作 (owner gate)。

    repository が tenant + project + batch + ``deleted_at IS NOT NULL`` で限定し越境復活を防ぐ。
    再 restore / 別 project の batch_id / 空 batch は ``restored_count=0`` で idempotent (二重復元で
    件数 inflation しない)。archived project は 409 (unarchive 要求)。実際に復元した
    (``restored_count > 0``) ときのみ ``tickets_restored`` audit を残す (audit は実遷移と 1:1)。
    """
    repo = TicketRepository(session)
    try:
        restored_count = await repo.restore_batch_in_project(
            tenant_id,
            project_id,
            payload.deleted_batch_id,
        )
    except ProjectArchivedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project is archived; unarchive it before restoring tickets",
        ) from exc
    # idempotent: 0 件復元 (再 restore / 越境 batch_id / 空 batch) では audit を残さない (実遷移と 1:1)。
    if restored_count > 0:
        audit_event = AuditEvent(
            tenant_id=tenant_id,
            event_type="tickets_restored",
            actor_id=owner_actor_id,
            event_payload={
                "rls_ready": True,
                "project_id": str(project_id),
                "deleted_batch_id": str(payload.deleted_batch_id),
                "restored_count": restored_count,
            },
        )
        session.add(audit_event)
    await session.commit()
    return RestoreBatchResponse(restored_count=restored_count)


@router.post(
    "/projects/{project_id}/tickets/import",
    response_model=ImportTicketsResponse,
)
async def import_tickets_endpoint(
    project_id: UUID,
    payload: ImportTicketsRequest,
    _cli_capability: object = Depends(maybe_require_cli_capability("task_write")),  # noqa: B008
    owner_actor_id: UUID = Depends(require_project_owner),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ImportTicketsResponse:
    """Q-2 (ADR-00037): validated JSON から ticket を一括インポートする破壊的 write (ADR Gate #8)。

    owner gate + untrusted boundary (各 item は ``TicketImportItem`` で schema validation 済、AI 出力
    直結なし)。all-or-nothing: in-payload slug 重複 or 既存 (active+deleted) slug 衝突が 1 件でも
    あれば 422 で全体 reject (原因 slug を列挙、partial write なし)。``dry_run=true`` は validation
    結果のみ返し insert しない (preview)。検証通過時のみ単一 transaction で全件 insert し、並行 import
    が pre-validation をすり抜けて DB unique violation を起こしたら全 rollback して 409 (DB-level 最終
    防衛)。archived project は 409。``tickets_imported`` audit (件数 + project_id、本文値は残さない)。
    """
    repo = TicketRepository(session)

    # Codex adversarial R7 #2: archive freeze を slug validation / dry_run より **前** に適用する。
    # archived project への import は slug conflict (422) や dry_run preview に関わらず常に 409 を返し、
    # archive freeze の contract を mutation 入口で一貫して fail-closed にする。
    # R26 (Codex App PR review): nonexistent project は dry_run を valid と誤判定し実 import が ticket FK
    # 違反まで進んで誤った 409 を返していたため、bulk-delete と整合する 404 を slug/dry_run より前に返す。
    try:
        await repo.assert_project_exists_active(tenant_id, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        ) from exc
    except ProjectArchivedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project is archived; unarchive it before importing tickets",
        ) from exc

    # (1) in-payload slug 重複検出 (同一 import 内で同 slug が複数)。
    seen: set[str] = set()
    in_payload_duplicates: set[str] = set()
    for item in payload.tickets:
        if item.slug in seen:
            in_payload_duplicates.add(item.slug)
        seen.add(item.slug)

    # (2) 既存 slug 衝突検出 (active + soft-deleted、unique は全行予約のため deleted も衝突対象)。
    existing_slugs = await repo.existing_slugs_in_project(tenant_id, project_id)
    existing_conflicts = {item.slug for item in payload.tickets if item.slug in existing_slugs}

    in_payload_dup_sorted = sorted(in_payload_duplicates)
    existing_conflict_sorted = sorted(existing_conflicts)
    valid = not in_payload_dup_sorted and not existing_conflict_sorted

    # dry_run は insert せず結果のみ返す (preview)。実 import 要求で衝突ありなら 422 で全体 reject。
    if payload.dry_run:
        return ImportTicketsResponse(
            dry_run=True,
            valid=valid,
            imported_count=0,
            in_payload_duplicate_slugs=in_payload_dup_sorted,
            existing_conflict_slugs=existing_conflict_sorted,
        )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "ticket import rejected due to slug conflicts",
                "in_payload_duplicate_slugs": in_payload_dup_sorted,
                "existing_conflict_slugs": existing_conflict_sorted,
            },
        )

    # 検証通過 + 実 import: 単一 transaction で全件 insert。並行 import が pre-validation を
    # すり抜けて slug unique violation を起こしたら全 rollback して 409 (DB-level 最終防衛、partial なし)。
    item_payloads = [
        {
            "slug": item.slug,
            "title": item.title,
            "description": item.description,
            "status": item.status,
            "priority": item.priority,
            "created_by_actor_id": owner_actor_id,
            "metadata_": {"rls_ready": True},
        }
        for item in payload.tickets
    ]
    try:
        imported = await repo.import_tickets_in_project(tenant_id, project_id, item_payloads)
    except ProjectArchivedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project is archived; unarchive it before importing tickets",
        ) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ticket import conflicted with a concurrent write; reload and retry",
        ) from exc

    audit_event = AuditEvent(
        tenant_id=tenant_id,
        event_type="tickets_imported",
        actor_id=owner_actor_id,
        event_payload={
            "rls_ready": True,
            "project_id": str(project_id),
            "imported_count": len(imported),
        },
    )
    session.add(audit_event)
    await session.commit()
    return ImportTicketsResponse(
        dry_run=False,
        valid=True,
        imported_count=len(imported),
        in_payload_duplicate_slugs=[],
        existing_conflict_slugs=[],
    )
