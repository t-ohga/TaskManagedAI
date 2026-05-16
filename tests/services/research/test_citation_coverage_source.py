"""Pure unit tests for citation_coverage_source contract (Sprint 10
BL-0119). DB-touching integration is in
tests/security/test_research_cross_project_negative.py."""

from __future__ import annotations

import pytest

from backend.app.services.research.citation_coverage_source import (
    CitationCoverageError,
    CitationCoverageMetric,
    compute_citation_coverage,
)


class TestCitationCoverageMetricShape:
    """Verify the dataclass surface AC-KPI-04 consumers depend on."""

    def test_metric_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError
        from uuid import uuid4

        m = CitationCoverageMetric(
            agent_run_id=uuid4(),
            tenant_id=1,
            project_id=uuid4(),
            evidence_set_hash=None,
            distinct_claims=0,
            grounded_claims=0,
            coverage=0.0,
            denominator_nonzero=False,
        )
        with pytest.raises(FrozenInstanceError):
            m.coverage = 1.0  # type: ignore[misc]

    def test_metric_fields_match_schema(self) -> None:
        """Field names must align with CitationCoverageRead so the API
        can ``model_validate`` directly from the dataclass."""
        from dataclasses import fields

        from backend.app.schemas.grounding_support import CitationCoverageRead

        metric_fields = {f.name for f in fields(CitationCoverageMetric)}
        schema_fields = set(CitationCoverageRead.model_fields.keys())
        # Schema must have every field the dataclass exposes; extras
        # on the schema side (none expected) would be a contract drift.
        assert schema_fields == metric_fields, (
            f"CitationCoverageRead vs CitationCoverageMetric field drift: "
            f"only-in-schema={schema_fields - metric_fields}, "
            f"only-in-metric={metric_fields - schema_fields}"
        )


class TestCitationCoverageInputValidation:
    """``compute_citation_coverage`` should fail-closed before touching
    the session for caller-supplied invalid tenant_id."""

    @pytest.mark.asyncio
    async def test_tenant_id_must_be_positive_int(self) -> None:
        from uuid import uuid4

        with pytest.raises(CitationCoverageError) as exc:
            await compute_citation_coverage(
                session=None,  # type: ignore[arg-type] — should fail before touching
                tenant_id=0,
                project_id=uuid4(),
                agent_run_id=uuid4(),
            )
        assert exc.value.reason_code == "tenant_id_invalid"

    @pytest.mark.asyncio
    async def test_tenant_id_bool_rejected(self) -> None:
        from uuid import uuid4

        with pytest.raises(CitationCoverageError) as exc:
            await compute_citation_coverage(
                session=None,  # type: ignore[arg-type]
                tenant_id=True,  # type: ignore[arg-type] — bool is int subclass
                project_id=uuid4(),
                agent_run_id=uuid4(),
            )
        assert exc.value.reason_code == "tenant_id_invalid"
