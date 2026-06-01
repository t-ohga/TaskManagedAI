from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.config import get_settings
from backend.app.db.models.agent_run import AgentRun
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.context_snapshot import ContextSnapshot
from backend.app.domain.agent_runtime.active_scope import soft_deleted_ticket_run_exclusion
from backend.app.domain.agent_runtime.status import AgentRunStatus, BlockedReason
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret
from backend.app.repositories.artifact import ArtifactRepository
from backend.app.services.agent_runtime.cancel import cancel_agent_run
from backend.app.services.metrics.agent_run_kpi import (
    AgentRunKpi,
    AgentRunKpiService,
    TimeToMergeProxySource,
)
from backend.app.services.realtime.agent_run_stream import AgentRunStreamResponse

router = APIRouter(prefix="/api/v1/agent_runs", tags=["agent_runs"])

PayloadRedactionStatus = Literal["keys_only", "blocked_by_secret_scan"]


class CancelAgentRunRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AgentRunResponse(BaseModel):
    id: UUID
    tenant_id: int
    project_id: UUID
    parent_run_id: UUID | None
    status: AgentRunStatus
    blocked_reason: BlockedReason | None
    error_code: str | None
    error_summary: str | None
    completed_at: datetime | None


class AgentRunRead(AgentRunResponse):
    role_id: str | None
    role_scope: str | None
    orchestrator_lease_expires_at: datetime | None
    last_progress_at: datetime | None
    progress_seq: int
    created_at: datetime
    updated_at: datetime


class AgentRunListResponse(BaseModel):
    items: list[AgentRunRead]
    total: int
    limit: int
    offset: int


CostSummaryRange = Literal["today", "week", "month", "quarter", "all"]


class CostSummaryByStatus(BaseModel):
    status: str
    cost_usd: float
    run_count: int


class CostSummaryResponse(BaseModel):
    total_cost_usd: float | None
    total_tokens_input: int
    total_tokens_output: int
    run_count: int
    measured_run_count: int
    unmeasured_run_count: int
    by_status: list[CostSummaryByStatus]
    range: CostSummaryRange


class RoleFacetEntry(BaseModel):
    role_id: str
    count: int


class RoleFacetResponse(BaseModel):
    roles: list[RoleFacetEntry]
    # 適用された status filter (省略時 null = tenant-wide facet)。
    status: AgentRunStatus | None


ActivityBucketGranularity = Literal["day", "week"]


class ActivityBucket(BaseModel):
    bucket_start: datetime
    run_count: int
    # measured run (cost_usd not null) が 0 件なら null (未計測を $0 と誤認させない、ADR-00040 R1-2)。
    cost_usd: float | None
    measured_run_count: int
    unmeasured_run_count: int


class ActivityTimeseriesResponse(BaseModel):
    # sparse: active run のある bucket のみ (run_count=0 bucket は返さない、ADR-00040 R1-3)。
    buckets: list[ActivityBucket]
    bucket: ActivityBucketGranularity
    range: CostSummaryRange


class AgentRunEventRead(BaseModel):
    id: UUID
    run_id: UUID
    seq_no: int
    event_type: str
    actor_id: UUID
    payload_keys: list[str]
    payload_redaction_status: PayloadRedactionStatus
    created_at: datetime


class ContextSnapshotRead(BaseModel):
    id: UUID
    run_id: UUID
    prompt_pack_version: str
    prompt_pack_lock: str
    policy_version: str
    policy_pack_lock: str
    repo_state_keys: list[str]
    tool_manifest_keys: list[str]
    evidence_set_hash: str
    has_provider_continuation_ref: bool
    provider_request_fingerprint_keys: list[str]
    snapshot_kind: str
    created_at: datetime


class AgentRunDetailResponse(AgentRunRead):
    events: list[AgentRunEventRead]
    context_snapshot: ContextSnapshotRead | None


class AgentRunKpiResponse(BaseModel):
    run_id: UUID
    tenant_id: int
    project_id: UUID
    status: AgentRunStatus
    completed_at: datetime | None
    repo_pr_opened_event_count: int
    first_repo_pr_opened_at: datetime | None
    time_to_merge_proxy_sample_count: int
    time_to_merge_proxy_ms: float | None
    time_to_merge_proxy_source: TimeToMergeProxySource


def _to_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        parent_run_id=run.parent_run_id,
        status=run.status,
        blocked_reason=run.blocked_reason,
        error_code=run.error_code,
        error_summary=run.error_summary,
        completed_at=run.completed_at,
    )


def _to_read(run: AgentRun) -> AgentRunRead:
    return AgentRunRead(
        id=run.id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        parent_run_id=run.parent_run_id,
        status=run.status,
        blocked_reason=run.blocked_reason,
        error_code=run.error_code,
        error_summary=run.error_summary,
        completed_at=run.completed_at,
        role_id=run.role_id,
        role_scope=run.role_scope,
        orchestrator_lease_expires_at=run.orchestrator_lease_expires_at,
        last_progress_at=run.last_progress_at,
        progress_seq=run.progress_seq,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _payload_keys(payload: dict[str, Any]) -> tuple[list[str], PayloadRedactionStatus]:
    try:
        assert_no_raw_secret(payload, path="$agent_run_event_payload")
    except ValueError:
        return [], "blocked_by_secret_scan"
    return sorted(payload.keys()), "keys_only"


def _to_event_read(event: AgentRunEvent) -> AgentRunEventRead:
    payload_keys, payload_redaction_status = _payload_keys(event.event_payload)
    return AgentRunEventRead(
        id=event.id,
        run_id=event.run_id,
        seq_no=event.seq_no,
        event_type=event.event_type,
        actor_id=event.actor_id,
        payload_keys=payload_keys,
        payload_redaction_status=payload_redaction_status,
        created_at=event.created_at,
    )


def _safe_json_keys(payload: dict[str, Any]) -> list[str]:
    try:
        assert_no_raw_secret(payload, path="$context_snapshot_payload")
    except ValueError:
        return []
    return sorted(payload.keys())


def _to_context_snapshot_read(snapshot: ContextSnapshot) -> ContextSnapshotRead:
    return ContextSnapshotRead(
        id=snapshot.id,
        run_id=snapshot.run_id,
        prompt_pack_version=snapshot.prompt_pack_version,
        prompt_pack_lock=snapshot.prompt_pack_lock,
        policy_version=snapshot.policy_version,
        policy_pack_lock=snapshot.policy_pack_lock,
        repo_state_keys=_safe_json_keys(snapshot.repo_state),
        tool_manifest_keys=_safe_json_keys(snapshot.tool_manifest),
        evidence_set_hash=snapshot.evidence_set_hash,
        has_provider_continuation_ref=snapshot.provider_continuation_ref is not None,
        provider_request_fingerprint_keys=_safe_json_keys(
            snapshot.provider_request_fingerprint
        ),
        snapshot_kind=snapshot.snapshot_kind,
        created_at=snapshot.created_at,
    )


def _to_kpi_response(kpi: AgentRunKpi) -> AgentRunKpiResponse:
    return AgentRunKpiResponse(
        run_id=kpi.run_id,
        tenant_id=kpi.tenant_id,
        project_id=kpi.project_id,
        status=kpi.status,
        completed_at=kpi.completed_at,
        repo_pr_opened_event_count=kpi.repo_pr_opened_event_count,
        first_repo_pr_opened_at=kpi.first_repo_pr_opened_at,
        time_to_merge_proxy_sample_count=kpi.time_to_merge_proxy_sample_count,
        time_to_merge_proxy_ms=kpi.time_to_merge_proxy_ms,
        time_to_merge_proxy_source=kpi.time_to_merge_proxy_source,
    )


@router.get("", response_model=AgentRunListResponse)
async def list_agent_runs_endpoint(
    status_filter: AgentRunStatus | None = Query(default=None, alias="status"),
    role: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AgentRunListResponse:
    """List AgentRuns for the current tenant.

    `actor_id` is intentionally resolved via Depends to enforce authenticated
    session context even though list visibility is tenant-scoped in P0.1.
    """
    # ADR-00037 R15 (Codex adversarial): soft-deleted ticket bound の run を default 一覧から除外する
    # (全 read path active-scope)。ticket-less run は含む。restore で再び現れる。
    conditions = [AgentRun.tenant_id == tenant_id, soft_deleted_ticket_run_exclusion()]
    if status_filter is not None:
        conditions.append(AgentRun.status == status_filter)
    if role is not None:
        conditions.append(AgentRun.role_id == role)

    total = await session.scalar(select(func.count()).select_from(AgentRun).where(*conditions))
    result = await session.execute(
        select(AgentRun)
        .where(*conditions)
        .order_by(AgentRun.created_at.desc(), AgentRun.id)
        .limit(limit)
        .offset(offset)
    )
    runs = list(result.scalars())
    return AgentRunListResponse(
        items=[_to_read(run) for run in runs],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


def _cost_summary_cutoff(range_value: CostSummaryRange) -> datetime | None:
    """range から created_at の cutoff を server 側で算出 (caller-supplied date 禁止)."""
    now = datetime.now(UTC)
    if range_value == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_value == "week":
        return now - timedelta(days=7)
    if range_value == "month":
        return now - timedelta(days=30)
    if range_value == "quarter":
        return now - timedelta(days=90)
    return None


@router.get("/cost_summary", response_model=CostSummaryResponse)
async def cost_summary_endpoint(
    range_value: CostSummaryRange = Query(default="all", alias="range"),
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> CostSummaryResponse:
    """AgentRun のコスト/トークンを集計 (read-only、ADR-00033).

    tenant 境界を強制し、cost_usd / tokens のみ返す (raw secret なし)。
    `actor_id` は authenticated session 強制のため Depends で resolve。
    """
    conditions = [AgentRun.tenant_id == tenant_id]
    cutoff = _cost_summary_cutoff(range_value)
    if cutoff is not None:
        conditions.append(AgentRun.created_at >= cutoff)
    # ADR-00037 R12/R13/R15 (Codex adversarial): soft-deleted ticket bound の run を cost/KPI 集計から
    # 除外する (全 read path active-scope の共通 predicate)。ticket-less run は含む、restore で復帰。
    conditions.append(soft_deleted_ticket_run_exclusion())

    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(AgentRun.cost_usd), Decimal(0)),
                func.coalesce(func.sum(AgentRun.tokens_input), 0),
                func.coalesce(func.sum(AgentRun.tokens_output), 0),
                func.count(),
                func.count(AgentRun.cost_usd),
            ).where(*conditions)
        )
    ).one()
    total_cost, total_in, total_out, run_count, measured_count = totals

    by_status_rows = (
        await session.execute(
            select(
                AgentRun.status,
                func.coalesce(func.sum(AgentRun.cost_usd), Decimal(0)),
                func.count(),
            )
            .where(*conditions)
            .group_by(AgentRun.status)
            .order_by(AgentRun.status)
        )
    ).all()

    measured = int(measured_count or 0)
    total = int(run_count or 0)
    return CostSummaryResponse(
        # 測定済み run が 0 件なら null (未計測を $0 と誤認させない、ADR-00033 / Codex adversarial)
        total_cost_usd=float(total_cost) if measured > 0 else None,
        total_tokens_input=int(total_in or 0),
        total_tokens_output=int(total_out or 0),
        run_count=total,
        measured_run_count=measured,
        unmeasured_run_count=total - measured,
        by_status=[
            CostSummaryByStatus(
                status=str(row[0]),
                cost_usd=float(row[1]),
                run_count=int(row[2]),
            )
            for row in by_status_rows
        ],
        range=range_value,
    )


# role_facet は静的 route。`/{run_id}` (UUID detail) より **前** に定義しないと
# `/role_facet` が run_id として解釈され UUID 422 になる (ADR-00039 R2、route ordering)。
@router.get("/role_facet", response_model=RoleFacetResponse)
async def role_facet_endpoint(
    status_value: AgentRunStatus | None = Query(default=None, alias="status"),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> RoleFacetResponse:
    """AgentRun の role_id facet (read-only、ADR-00039 C-4).

    tenant 境界 + active-scope (soft-deleted ticket bound run 除外) を強制し、
    `role_id is not null` の distinct facet を返す (null = single-agent run は出さない)。
    任意 `status` で list endpoint と同じ status predicate を適用 (status-scoped facet、
    選択中 status に存在しない role chip をクリックして空一覧になる facet drift を防ぐ)。
    不正な status 値は FastAPI が 422 で reject。raw secret なし (件数のみ)。
    """
    conditions = [
        AgentRun.tenant_id == tenant_id,
        AgentRun.role_id.is_not(None),
        soft_deleted_ticket_run_exclusion(),
    ]
    if status_value is not None:
        conditions.append(AgentRun.status == status_value)

    rows = (
        await session.execute(
            select(AgentRun.role_id, func.count())
            .where(*conditions)
            .group_by(AgentRun.role_id)
            .order_by(AgentRun.role_id)
        )
    ).all()

    return RoleFacetResponse(
        roles=[RoleFacetEntry(role_id=str(row[0]), count=int(row[1])) for row in rows],
        status=status_value,
    )


# activity_timeseries も静的 route。`/{run_id}` より前に定義する (ADR-00040、route ordering)。
@router.get("/activity_timeseries", response_model=ActivityTimeseriesResponse)
async def activity_timeseries_endpoint(
    bucket: ActivityBucketGranularity = Query(default="day"),  # noqa: B008
    range_value: CostSummaryRange = Query(default="month", alias="range"),  # noqa: B008
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> ActivityTimeseriesResponse:
    """AgentRun のアクティビティ / コスト時系列 (read-only、ADR-00040 D-3/D-4).

    `date_trunc(bucket, created_at)` で bucket 集計。tenant 境界 + active-scope
    (soft-deleted ticket bound run 除外) を強制し、range cutoff は server 側で算出する。
    `bucket` は Literal[day,week] (FastAPI 検証、不正値 422)。SQLAlchemy が bind param 化するため
    caller 文字列を SQL に直接展開しない。sparse: active run のある bucket のみ返す。
    `cost_usd` は bucket 内 measured run (cost_usd not null) が 0 件なら null。
    raw secret なし (件数・cost のみ)。`actor_id` は authenticated session 強制のため Depends で resolve。
    """
    conditions = [AgentRun.tenant_id == tenant_id]
    cutoff = _cost_summary_cutoff(range_value)
    if cutoff is not None:
        conditions.append(AgentRun.created_at >= cutoff)
    # cost_summary / list と同じ active-scope (soft-deleted ticket bound run を除外)。
    conditions.append(soft_deleted_ticket_run_exclusion())

    # date_trunc は timestamptz を **DB session TimeZone** で切り詰めるため、session が非 UTC だと
    # bucket 境界がずれる (Codex ADR-00040 R2)。PostgreSQL 16 の 3 引数形で UTC を明示し、session
    # TimeZone 非依存の UTC bucket にする。bucket / 'UTC' とも SQLAlchemy が bind param 化する。
    bucket_start = func.date_trunc(bucket, AgentRun.created_at, "UTC").label("bucket_start")
    rows = (
        await session.execute(
            select(
                bucket_start,
                func.count(),
                func.coalesce(func.sum(AgentRun.cost_usd), Decimal(0)),
                func.count(AgentRun.cost_usd),
            )
            .where(*conditions)
            .group_by(bucket_start)
            .order_by(bucket_start)
        )
    ).all()

    buckets: list[ActivityBucket] = []
    for start, run_count, cost_sum, measured_count in rows:
        run_n = int(run_count or 0)
        measured_n = int(measured_count or 0)
        buckets.append(
            ActivityBucket(
                bucket_start=start,
                run_count=run_n,
                # measured 0 件なら null (未計測を $0 と誤認させない)。
                cost_usd=float(cost_sum) if measured_n > 0 else None,
                measured_run_count=measured_n,
                unmeasured_run_count=run_n - measured_n,
            )
        )
    return ActivityTimeseriesResponse(buckets=buckets, bucket=bucket, range=range_value)


class RunArtifact(BaseModel):
    """ADR-00042 L-2: artifact inventory の metadata-only 表現 (content / content_hash なし)."""

    id: UUID
    kind: str
    payload_data_class: str
    trust_level: str
    exportable: bool
    parent_artifact_id: UUID | None
    created_at: datetime


class RunArtifactListResponse(BaseModel):
    artifacts: list[RunArtifact]


@router.get("/{run_id}/artifacts", response_model=RunArtifactListResponse)
async def list_run_artifacts_endpoint(
    run_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> RunArtifactListResponse:
    """ADR-00042 L-2: run が生成した artifact の metadata inventory (read-only).

    content_jsonb / content_hash は返さない (metadata-only)。run 可視性 + active-scope
    (soft-deleted ticket bound run 除外) を repository の単一 statement で enforce し、run 不可視は
    404、run 可視・artifact 0 件は 200 empty。`provider_continuation_ref` は inventory / parent lineage
    から除外する (ContextSnapshot UI 非露出 rule)。`actor_id` は authenticated session 強制のため Depends。
    """
    rows = await ArtifactRepository(session).list_run_artifacts(tenant_id, run_id)
    if rows is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="agent run not found"
        )
    return RunArtifactListResponse(
        artifacts=[
            RunArtifact(
                id=row.id,
                kind=row.kind,
                payload_data_class=row.payload_data_class,
                trust_level=row.trust_level,
                exportable=row.exportable,
                parent_artifact_id=row.parent_artifact_id,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


@router.get("/{run_id}", response_model=AgentRunDetailResponse)
async def get_agent_run_endpoint(
    run_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AgentRunDetailResponse:
    """Read one AgentRun plus redacted event/context metadata."""
    # ADR-00037 R15 (Codex adversarial): soft-deleted ticket bound の run は default detail からも
    # 隠す (全 read path active-scope)。除外条件込みで取得し、該当しなければ 404 (restore で復帰)。
    run = await session.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
            soft_deleted_ticket_run_exclusion(),
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent run not found",
        )

    # 最新 200 件 (tail) を返す。SSE realtime (ADR-00038 / Codex PR #301 P2-1) では seed の最大
    # seq_no を resume cursor にするため、先頭 200 件を返すと >200 event の run で 201 件目以降を
    # 全 replay してしまう。tail を返すことで cursor=最新となり catch-up replay を避ける。
    events_result = await session.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.tenant_id == tenant_id, AgentRunEvent.run_id == run_id)
        .order_by(AgentRunEvent.seq_no.desc(), AgentRunEvent.created_at.desc(), AgentRunEvent.id.desc())
        .limit(200)
    )
    tail_events = list(events_result.scalars())
    tail_events.reverse()  # 表示用に昇順 (chronological) へ
    snapshot = await session.scalar(
        select(ContextSnapshot)
        .where(ContextSnapshot.tenant_id == tenant_id, ContextSnapshot.run_id == run_id)
        .order_by(ContextSnapshot.created_at.desc(), ContextSnapshot.id)
        .limit(1)
    )
    base = _to_read(run).model_dump()
    return AgentRunDetailResponse(
        **base,
        events=[_to_event_read(event) for event in tail_events],
        context_snapshot=_to_context_snapshot_read(snapshot) if snapshot is not None else None,
    )


@router.get("/{run_id}/kpi", response_model=AgentRunKpiResponse)
async def get_agent_run_kpi_endpoint(
    run_id: UUID,
    actor_id: UUID = Depends(get_current_actor_id),  # noqa: B008
    tenant_id: int = Depends(get_tenant_id),  # noqa: B008
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> AgentRunKpiResponse:
    """Read AC-KPI-02 source metrics for one tenant-scoped AgentRun.

    `actor_id` is resolved only for authentication. The response intentionally
    exposes timestamps and counts, not raw AgentRunEvent payloads.

    Note (ADR-00037 R15): この kpi endpoint は AC-KPI-02 単一 run point-read であり、Codex は
    agent_run_kpi.py を aggregation-scope 外として carve-out 済。soft-deleted ticket bound run の
    metric 露出を塞ぐ場合は AgentRunKpiService の SQL に active-scope を入れる必要があり、AC-KPI-02
    fixture 整合の確認を伴うため defer (ADR 残リスク §)。default run 露出は detail/list 側で active-scope 化済。
    """
    kpi = await AgentRunKpiService(session).fetch(tenant_id=tenant_id, run_id=run_id)
    if kpi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent run not found",
        )
    return _to_kpi_response(kpi)


def get_stream_auth_context(request: Request) -> int:
    """SSE stream 用 **sessionless** auth dependency (ADR-00038 R6/R7、code-review #2)。

    DB session を使わず request.state から **actor と tenant の両方** を fail-closed で検証する。
    `get_db_session` / `get_current_actor_id` を dependency graph に含めない (yield session の
    cleanup が stream 完了まで遅延し main pool を枯渇させるのを防ぐ)。未認証 (actor 不在) は 401。
    """
    actor_reference = getattr(request.state, "actor_id", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    if actor_reference is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant context missing",
        )
    return tenant_id


@router.get("/{run_id}/events/stream")
async def stream_agent_run_events_endpoint(
    run_id: UUID,
    last_event_id: int = Query(default=0, ge=0),  # noqa: B008
    tenant_id: int = Depends(get_stream_auth_context),  # noqa: B008
) -> Response:
    """AgentRun 進捗の SSE stream (ADR-00038 / L-3 realtime)。

    read-only。auth は **sessionless dep (`get_stream_auth_context`、request.state から actor+tenant を
    fail-closed 検証)** のみで、`get_db_session` / `get_current_actor_id` を dependency graph に含めない
    (R6/R7: yield session の cleanup が stream 完了まで遅延し main transactional pool を枯渇させるのを防ぐ)。

    `?last_event_id=<seq_no>` (int、非整数/UUID は FastAPI が 422) で resume する。capacity 判定 →
    active-scope preflight (404) → LISTEN → stream → release は `AgentRunStreamResponse.__call__` が
    単一 ASGI scope で所有する (capacity gate を DB preflight より前に置き、handoff leak 窓を排除、R3/R8)。

    flag-off (`agentrun_sse_enabled=false`) は **204** を返す (client は spec 通り再接続を停止、R4)。
    """
    if not get_settings().agentrun_sse_enabled:
        return Response(status_code=204)
    return AgentRunStreamResponse(
        tenant_id=tenant_id,
        run_id=run_id,
        last_event_id=last_event_id,
    )


@router.post("/{run_id}/cancel", response_model=AgentRunResponse, status_code=200)
async def cancel_agent_run_endpoint(
    run_id: UUID,
    body: CancelAgentRunRequest,
    actor_id: UUID = Depends(get_current_actor_id),
    tenant_id: int = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AgentRunResponse:
    try:
        run = await cancel_agent_run(
            session=session,
            run_id=run_id,
            reason=body.reason,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent run not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await session.commit()
    return _to_response(run)


__all__ = [
    "AgentRunDetailResponse",
    "AgentRunEventRead",
    "AgentRunKpiResponse",
    "AgentRunListResponse",
    "AgentRunRead",
    "AgentRunResponse",
    "CancelAgentRunRequest",
    "ContextSnapshotRead",
    "router",
]
