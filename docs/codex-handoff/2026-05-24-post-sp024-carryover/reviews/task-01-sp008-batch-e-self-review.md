# task-01 SP-008 Batch E Self Review

Date: 2026-05-24

## Scope

Batch E adds the canonical SP-008 AgentRun KPI endpoint:

- `GET /api/v1/agent_runs/{run_id}/kpi`
- `backend/app/services/metrics/agent_run_kpi.py`
- API and DB regression coverage for AC-KPI-02 source exposure

It does not claim true GitHub PR merge timestamp ingestion. The current P0 source is explicitly a proxy from first `repo_pr_opened` event to `agent_runs.completed_at`.

## Findings

| severity | finding | disposition |
|---|---|---|
| HIGH | Endpoint could leak raw `agent_run_events.event_payload` while trying to expose PR metadata. | adopt: response model returns only ids, status, timestamps, counts, sample count, and proxy value. API test asserts `event_payload` / `payload` keys are absent. |
| HIGH | Cross-tenant reads could expose another tenant's run KPI. | adopt: service sets/asserts tenant context and filters `agent_runs` by `(tenant_id, id)` before event aggregation. DB test covers missing/cross-tenant return `None`. |
| MEDIUM | Running or failed runs could be counted as completed time-to-merge samples. | adopt: service emits a sample only when `status == completed`, `completed_at` exists, and PR-opened timestamp exists. |
| MEDIUM | Negative temporal samples could game median calculation. | adopt: service rejects `completed_at < first_repo_pr_opened_at`; regression test covers the case. |
| MEDIUM | Duplicate event rows could inflate counts if query rewrites later ignore event uniqueness. | adopt: query dedupes by `(run_id, seq_no)` before counting and selecting the first PR-opened timestamp. |

## Checklist

- [x] Server-owned tenant boundary: route depends on authenticated actor and tenant context; service performs tenant-scoped read.
- [x] No raw payload exposure: endpoint response has no event payload body.
- [x] AC-KPI-02 source is explicit: `repo_pr_opened_to_agent_run_completed`.
- [x] Running / incomplete / negative temporal cases do not produce samples.
- [x] Canonical route uses existing backend convention: `/api/v1/agent_runs/{run_id}/kpi`.
- [x] Residual true merge timestamp source is documented as future work.

## Verification

- `uv run ruff check backend/app/services/metrics/agent_run_kpi.py backend/app/services/metrics/__init__.py backend/app/api/agent_runs.py tests/metrics/test_agent_run_kpi.py tests/api/test_agent_runs_kpi.py tests/api/test_sp012_9_ui_wiring_routes.py`
- `PYTHONPATH=cli uv run mypy backend/app/services/metrics/agent_run_kpi.py backend/app/api/agent_runs.py tests/metrics/test_agent_run_kpi.py tests/api/test_agent_runs_kpi.py`
- `uv run pytest tests/api/test_agent_runs_kpi.py tests/api/test_sp012_9_ui_wiring_routes.py -q`
- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/metrics/test_agent_run_kpi.py -q`
