"""Sprint 12 batch 1 (BL-0148 endpoint): KPI rollup API endpoint tests.

dependency_overrides で auth + tenant context を bypass、`run_kpi_rollup`
を monkeypatch で mock し、endpoint contract を verify する pure unit-test.

DB integration は不要 (本 endpoint は read-only filesystem read のみ、
DB / Redis 依存なし).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app.api.approval_inbox import (
    get_current_actor_id,
    get_db_session,
    get_tenant_id,
)
from backend.app.api.kpi_rollup import router as kpi_rollup_router
from backend.app.services.eval.kpi_rollup import (
    KpiEntry,
    KpiRollupSummary,
)
from backend.app.services.eval.kpi_rollup_runner import (
    CorpusLoadResult,
    KpiRollupRunnerError,
)

_TENANT_ID = 1
_ACTOR_ID = UUID("00000000-0000-4000-8000-000000007001")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(kpi_rollup_router)

    async def override_tenant() -> int:
        return _TENANT_ID

    async def override_actor() -> UUID:
        return _ACTOR_ID

    async def override_db() -> AsyncIterator[None]:
        # endpoint は DB session を使わないが get_current_actor_id が depend
        yield None

    app.dependency_overrides[get_tenant_id] = override_tenant
    app.dependency_overrides[get_current_actor_id] = override_actor
    app.dependency_overrides[get_db_session] = override_db
    return app


def _build_summary(*, p0_accept: bool, met_count: int) -> KpiRollupSummary:
    """fixture KpiRollupSummary (frozen)。"""

    entries = tuple(
        KpiEntry(
            kpi_id=kpi_id,
            metric_key=metric_key,
            metric_value=metric_value,
            threshold_met=(i < met_count),
            threshold_reason="threshold_met" if (i < met_count) else "below_threshold",
        )
        for i, (kpi_id, metric_key, metric_value) in enumerate(
            (
                ("AC-KPI-01", "acceptance_pass_rate", 0.75),
                ("AC-KPI-02", "time_to_merge", 1.5),
                ("AC-KPI-03", "approval_wait_ms", 3_000_000.0),
                ("AC-KPI-04", "citation_coverage", 0.95),
                ("AC-KPI-05", "cost_per_completed_task", 0.3),
            )
        )
    )
    return KpiRollupSummary(
        kpi_count=5,
        met_count=met_count,
        failed_count=5 - met_count,
        p0_accept=p0_accept,
        fail_tolerance=1,
        entries=entries,
    )


def _build_load_results() -> tuple[CorpusLoadResult, ...]:
    return tuple(
        CorpusLoadResult(
            kpi_id=kpi_id,
            dataset_key=dataset_key,
            dataset_version=f"v2026.05.17-{dataset_key}",
            fixture_count=1,
        )
        for kpi_id, dataset_key in (
            ("AC-KPI-01", "acceptance_pass_rate"),
            ("AC-KPI-02", "time_to_merge"),
            ("AC-KPI-03", "approval_wait_ms"),
            ("AC-KPI-04", "citation_coverage"),
            ("AC-KPI-05", "cost_per_completed_task"),
        )
    )


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_endpoint_returns_200_with_p0_accept_true(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5 KPI all-pass で 200 + p0_accept=True を返す。"""

    def fake_run_kpi_rollup(**_: Any) -> tuple[KpiRollupSummary, tuple[CorpusLoadResult, ...]]:
        return _build_summary(p0_accept=True, met_count=5), _build_load_results()

    monkeypatch.setattr(
        "backend.app.api.kpi_rollup.run_kpi_rollup", fake_run_kpi_rollup
    )

    response = await client.get("/api/v1/eval/kpi-rollup")
    assert response.status_code == 200
    payload = response.json()
    assert payload["kpi_count"] == 5
    assert payload["met_count"] == 5
    assert payload["failed_count"] == 0
    assert payload["p0_accept"] is True
    assert payload["fail_tolerance"] == 1
    assert len(payload["entries"]) == 5
    assert len(payload["corpus_loads"]) == 5
    # AC-KPI-01..05 順 invariant
    assert [e["kpi_id"] for e in payload["entries"]] == [
        "AC-KPI-01",
        "AC-KPI-02",
        "AC-KPI-03",
        "AC-KPI-04",
        "AC-KPI-05",
    ]


@pytest.mark.asyncio
async def test_endpoint_returns_200_with_p0_accept_false(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2 件 未達で p0_accept=False (改善 Sprint 必要)、HTTP は 200 維持。"""

    def fake_run_kpi_rollup(**_: Any) -> tuple[KpiRollupSummary, tuple[CorpusLoadResult, ...]]:
        return _build_summary(p0_accept=False, met_count=3), _build_load_results()

    monkeypatch.setattr(
        "backend.app.api.kpi_rollup.run_kpi_rollup", fake_run_kpi_rollup
    )

    response = await client.get("/api/v1/eval/kpi-rollup")
    assert response.status_code == 200
    payload = response.json()
    assert payload["met_count"] == 3
    assert payload["failed_count"] == 2
    assert payload["p0_accept"] is False


@pytest.mark.asyncio
async def test_endpoint_returns_503_on_corpus_load_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """corpus load 失敗で 503 + error_code を返す (raw secret を含まない)。"""

    def fake_run_kpi_rollup(**_: Any) -> tuple[KpiRollupSummary, tuple[CorpusLoadResult, ...]]:
        raise KpiRollupRunnerError(
            "corpus load failed for kpi_id=AC-KPI-01 dataset_key=acceptance_pass_rate: "
            "manifest.json not found"
        )

    monkeypatch.setattr(
        "backend.app.api.kpi_rollup.run_kpi_rollup", fake_run_kpi_rollup
    )

    response = await client.get("/api/v1/eval/kpi-rollup")
    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["error_code"] == "kpi_rollup_corpus_load_failed"
    assert "manifest.json not found" in payload["detail"]["error_summary"]


@pytest.mark.asyncio
async def test_endpoint_response_is_immutable_shape(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """response payload の各 entry に必須 fields が全て含まれる (frozen contract)。"""

    def fake_run_kpi_rollup(**_: Any) -> tuple[KpiRollupSummary, tuple[CorpusLoadResult, ...]]:
        return _build_summary(p0_accept=True, met_count=5), _build_load_results()

    monkeypatch.setattr(
        "backend.app.api.kpi_rollup.run_kpi_rollup", fake_run_kpi_rollup
    )

    response = await client.get("/api/v1/eval/kpi-rollup")
    assert response.status_code == 200
    payload = response.json()

    for entry in payload["entries"]:
        assert set(entry.keys()) == {
            "kpi_id",
            "metric_key",
            "metric_value",
            "threshold_met",
            "threshold_reason",
        }

    for cl in payload["corpus_loads"]:
        assert set(cl.keys()) == {
            "kpi_id",
            "dataset_key",
            "dataset_version",
            "fixture_count",
        }


@pytest.mark.asyncio
async def test_endpoint_rejects_when_no_actor_context() -> None:
    """actor context 不在 (401) — dependency_overrides を入れない app で verify。"""

    app = FastAPI()
    app.include_router(kpi_rollup_router)
    # tenant のみ override (actor は意図的に未設定)

    async def override_tenant() -> int:
        return _TENANT_ID

    async def override_db() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_tenant_id] = override_tenant
    app.dependency_overrides[get_db_session] = override_db
    # get_current_actor_id は override しない → request.state.actor_id missing で 401

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        response = await c.get("/api/v1/eval/kpi-rollup")
        # 401 (actor context missing) または 400 (tenant context missing)
        # actor が depend されるので 401 が期待値
        assert response.status_code in (400, 401)


@pytest.mark.asyncio
async def test_endpoint_metric_value_none_serializes_as_null(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """metric_value=None (corpus undefined) は JSON null として serialize。"""

    def fake_run_kpi_rollup(**_: Any) -> tuple[KpiRollupSummary, tuple[CorpusLoadResult, ...]]:
        entries = (
            KpiEntry(
                kpi_id="AC-KPI-01",
                metric_key="acceptance_pass_rate",
                metric_value=None,
                threshold_met=False,
                threshold_reason="no_evaluated_criteria",
            ),
            KpiEntry(
                kpi_id="AC-KPI-02",
                metric_key="time_to_merge",
                metric_value=1.5,
                threshold_met=True,
                threshold_reason="threshold_met",
            ),
            KpiEntry(
                kpi_id="AC-KPI-03",
                metric_key="approval_wait_ms",
                metric_value=3_000_000.0,
                threshold_met=True,
                threshold_reason="threshold_met",
            ),
            KpiEntry(
                kpi_id="AC-KPI-04",
                metric_key="citation_coverage",
                metric_value=0.95,
                threshold_met=True,
                threshold_reason="threshold_met",
            ),
            KpiEntry(
                kpi_id="AC-KPI-05",
                metric_key="cost_per_completed_task",
                metric_value=0.3,
                threshold_met=True,
                threshold_reason="threshold_met",
            ),
        )
        summary = KpiRollupSummary(
            kpi_count=5,
            met_count=4,
            failed_count=1,
            p0_accept=True,
            fail_tolerance=1,
            entries=entries,
        )
        return summary, _build_load_results()

    monkeypatch.setattr(
        "backend.app.api.kpi_rollup.run_kpi_rollup", fake_run_kpi_rollup
    )

    response = await client.get("/api/v1/eval/kpi-rollup")
    assert response.status_code == 200
    payload = response.json()
    assert payload["entries"][0]["metric_value"] is None
    assert payload["entries"][0]["threshold_met"] is False
    assert payload["entries"][0]["threshold_reason"] == "no_evaluated_criteria"
