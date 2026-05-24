"""Final-adopted artifact attribution and citation coverage metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.app_role import (
    assert_tenant_context,
    get_tenant_context,
    set_tenant_context,
)
from backend.app.db.models.adopted_artifact import AdoptedArtifact, AdoptedArtifactState
from backend.app.db.models.agent_run_event import AgentRunEvent
from backend.app.db.models.artifact import Artifact
from backend.app.repositories._payload_secret_scan import assert_no_raw_secret


@dataclass(frozen=True)
class AdoptedArtifactAttribution:
    id: UUID
    tenant_id: int
    project_id: UUID
    run_id: UUID
    artifact_id: UUID
    adoption_state: AdoptedArtifactState
    adoption_event_id: UUID | None
    finalized_at: datetime | None


@dataclass(frozen=True)
class AdoptedArtifactCitationCoverage:
    tenant_id: int
    root_run_id: UUID
    project_id: UUID
    lineage_run_count: int
    final_adopted_artifact_count: int
    citation_total_claim_count: int
    citation_covered_claim_count: int
    citation_coverage: float | None


class AdoptedArtifactAttributionService:
    """Record server-validated artifact adoption links."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_adoption(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        run_id: UUID,
        artifact_id: UUID,
        adopted_by_actor_id: UUID,
        adoption_state: AdoptedArtifactState = "final",
        adoption_event_id: UUID | None = None,
        finalized_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AdoptedArtifactAttribution:
        await _ensure_tenant_context(self.session, tenant_id)
        _validate_adoption_state(
            adoption_state=adoption_state,
            adoption_event_id=adoption_event_id,
            finalized_at=finalized_at,
        )
        await self._assert_artifact_boundary(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            artifact_id=artifact_id,
        )
        if adoption_state == "final":
            if adoption_event_id is None:
                raise ValueError("final adoption requires adoption_event_id.")
            await self._assert_final_adoption_event(
                tenant_id=tenant_id,
                run_id=run_id,
                artifact_id=artifact_id,
                adoption_event_id=adoption_event_id,
            )

        metadata_payload = dict(metadata or {"rls_ready": True})
        assert_no_raw_secret(metadata_payload, path="$adopted_artifacts.metadata")

        row = AdoptedArtifact(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run_id,
            artifact_id=artifact_id,
            adoption_state=adoption_state,
            adoption_event_id=adoption_event_id,
            adopted_by_actor_id=adopted_by_actor_id,
            finalized_at=finalized_at,
            metadata_=metadata_payload,
        )
        self.session.add(row)
        await self.session.flush()
        return _attribution_from_row(row)

    async def _assert_artifact_boundary(
        self,
        *,
        tenant_id: int,
        project_id: UUID,
        run_id: UUID,
        artifact_id: UUID,
    ) -> None:
        artifact_exists = await self.session.scalar(
            select(Artifact.id).where(
                Artifact.tenant_id == tenant_id,
                Artifact.project_id == project_id,
                Artifact.run_id == run_id,
                Artifact.id == artifact_id,
            )
        )
        if artifact_exists is None:
            raise ValueError(
                "artifact_id must belong to tenant_id + project_id + run_id."
            )

    async def _assert_final_adoption_event(
        self,
        *,
        tenant_id: int,
        run_id: UUID,
        artifact_id: UUID,
        adoption_event_id: UUID,
    ) -> None:
        event = await self.session.scalar(
            select(AgentRunEvent).where(
                AgentRunEvent.tenant_id == tenant_id,
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.id == adoption_event_id,
            )
        )
        if event is None:
            raise ValueError(
                "adoption_event_id must belong to tenant_id + run_id."
            )
        if event.event_type != "artifact_generated":
            raise ValueError("final adoption event must be artifact_generated.")
        payload = event.event_payload
        if str(payload.get("artifact_id")) != str(artifact_id):
            raise ValueError("final adoption event artifact_id mismatch.")
        if payload.get("adoption_state") != "final":
            raise ValueError("final adoption event must declare adoption_state=final.")


class AdoptedArtifactCitationCoverageService:
    """Read-only claim-level citation coverage from final adopted artifacts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch(
        self,
        *,
        tenant_id: int,
        root_run_id: UUID,
    ) -> AdoptedArtifactCitationCoverage | None:
        await _ensure_tenant_context(self.session, tenant_id)
        row = (
            await self.session.execute(
                _CITATION_COVERAGE_SQL,
                {"tenant_id": tenant_id, "root_run_id": str(root_run_id)},
            )
        ).mappings().one()

        lineage_run_count = _int(row["lineage_run_count"])
        if lineage_run_count == 0:
            return None

        project_id = row["project_id"]
        if not isinstance(project_id, UUID):
            project_id = UUID(str(project_id))

        return AdoptedArtifactCitationCoverage(
            tenant_id=tenant_id,
            root_run_id=root_run_id,
            project_id=project_id,
            lineage_run_count=lineage_run_count,
            final_adopted_artifact_count=_int(row["final_adopted_artifact_count"]),
            citation_total_claim_count=_int(row["citation_total_claim_count"]),
            citation_covered_claim_count=_int(row["citation_covered_claim_count"]),
            citation_coverage=_optional_float(row["citation_coverage"]),
        )


def _validate_adoption_state(
    *,
    adoption_state: AdoptedArtifactState,
    adoption_event_id: UUID | None,
    finalized_at: datetime | None,
) -> None:
    if adoption_state not in {"draft", "final"}:
        raise ValueError("adoption_state must be draft or final.")
    if adoption_state == "final":
        if adoption_event_id is None:
            raise ValueError("final adoption requires adoption_event_id.")
        if finalized_at is None:
            raise ValueError("final adoption requires finalized_at.")
        if finalized_at.tzinfo is None:
            raise ValueError("finalized_at must be timezone-aware.")
        return
    if adoption_event_id is not None or finalized_at is not None:
        raise ValueError("draft adoption cannot include final adoption fields.")


async def _ensure_tenant_context(session: AsyncSession, tenant_id: int) -> None:
    if not isinstance(tenant_id, int) or isinstance(tenant_id, bool) or tenant_id < 1:
        raise ValueError("tenant_id must be a positive integer.")
    current = await get_tenant_context(session)
    if current is None:
        await set_tenant_context(session, tenant_id)
    await assert_tenant_context(session, tenant_id)


def _attribution_from_row(row: AdoptedArtifact) -> AdoptedArtifactAttribution:
    finalized_at = row.finalized_at
    if finalized_at is not None and finalized_at.tzinfo is None:
        finalized_at = finalized_at.replace(tzinfo=UTC)
    return AdoptedArtifactAttribution(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        run_id=row.run_id,
        artifact_id=row.artifact_id,
        adoption_state=row.adoption_state,
        adoption_event_id=row.adoption_event_id,
        finalized_at=finalized_at,
    )


_CITATION_COVERAGE_SQL = sa.text(
    r"""
    with recursive run_tree as (
        select
            ar.id,
            ar.tenant_id,
            ar.project_id,
            ar.parent_run_id,
            array[ar.id]::uuid[] as path
          from agent_runs ar
         where ar.tenant_id = :tenant_id
           and ar.id = cast(:root_run_id as uuid)

        union all

        select
            child.id,
            child.tenant_id,
            child.project_id,
            child.parent_run_id,
            array_append(parent.path, child.id) as path
          from agent_runs child
          join run_tree parent
            on parent.tenant_id = child.tenant_id
           and parent.project_id = child.project_id
           and parent.id = child.parent_run_id
         where not child.id = any(parent.path)
    ),
    final_adoptions as (
        select
            aa.project_id,
            aa.run_id,
            aa.artifact_id,
            a.content_jsonb
          from adopted_artifacts aa
          join run_tree rt
            on rt.tenant_id = aa.tenant_id
           and rt.project_id = aa.project_id
           and rt.id = aa.run_id
          join artifacts a
            on a.tenant_id = aa.tenant_id
           and a.project_id = aa.project_id
           and a.run_id = aa.run_id
           and a.id = aa.artifact_id
         where aa.tenant_id = :tenant_id
           and aa.adoption_state = 'final'
    ),
    claim_rows as (
        select
            fa.artifact_id,
            claim.value as claim_json
          from final_adoptions fa
          cross join lateral jsonb_array_elements(
            case
                when jsonb_typeof(fa.content_jsonb->'sample_claims') = 'array'
                then fa.content_jsonb->'sample_claims'
                when jsonb_typeof(fa.content_jsonb#>'{input,sample_claims}') = 'array'
                then fa.content_jsonb#>'{input,sample_claims}'
                else '[]'::jsonb
            end
          ) as claim(value)
    ),
    normalized_claims as (
        select
            artifact_id,
            claim_json->>'claim_id' as claim_id,
            bool_or(
                case
                    when jsonb_typeof(claim_json->'citation_ids') = 'array'
                    then jsonb_array_length(claim_json->'citation_ids') > 0
                    else false
                end
            ) as has_citation
          from claim_rows
         where jsonb_typeof(claim_json) = 'object'
           and nullif(claim_json->>'claim_id', '') is not null
         group by artifact_id, claim_json->>'claim_id'
    )
    select
        (select project_id from run_tree limit 1) as project_id,
        (select count(*) from run_tree) as lineage_run_count,
        (select count(*) from final_adoptions) as final_adopted_artifact_count,
        (select count(*) from normalized_claims) as citation_total_claim_count,
        (select count(*) from normalized_claims where has_citation is true)
            as citation_covered_claim_count,
        (
            select
                case
                    when count(*) = 0 then null
                    else count(*) filter (where has_citation is true)::float
                         / count(*)::float
                end
              from normalized_claims
        ) as citation_coverage
    """
)


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int | float | Decimal | str):
        return int(value)
    raise TypeError(f"expected int-compatible DB value, got {type(value).__name__}.")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float | Decimal | str):
        return float(value)
    raise TypeError(f"expected float-compatible DB value, got {type(value).__name__}.")


__all__ = [
    "AdoptedArtifactAttribution",
    "AdoptedArtifactAttributionService",
    "AdoptedArtifactCitationCoverage",
    "AdoptedArtifactCitationCoverageService",
]
