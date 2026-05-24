# task-01 SP-008 Residual Reconciliation Review

Date: 2026-05-24

## Verdict

READY for small implementation batches, but not READY for SP-008 closeout.

The current repository has enough primitives to continue SP-008, but it does not support the earlier claim that all ADR-00011 acceptance items were completed. The safe next path is implementation batch A through E in `docs/sprints/SP-008_github_app_repoproxy.md`.

## Evidence Checked

- `backend/app/services/repoproxy/permission_matrix.py`
- `backend/app/services/repoproxy/repoproxy.py`
- `backend/app/services/repoproxy/webhook_hmac.py`
- `backend/app/domain/agent_runtime/operation_context.py`
- `backend/app/services/secrets/broker.py`
- `backend/app/domain/agent_runtime/event_type.py`
- `backend/app/services/metrics/orchestrator_kpi_rollup.py`
- `tests/repoproxy/`
- `tests/runtime/test_secret_broker_issue.py`
- `tests/runtime/test_secret_broker_negative.py`
- `docs/adr/00011_github_app_permission_matrix.md`
- `docs/sprints/SP-008_github_app_repoproxy.md`

## Adopted Corrections

| item | disposition |
|---|---|
| ADR-00011 acceptance history overclaimed implementation completion | adopt: changed entries to current-tree evidence status |
| SP-008 review summary was internally contradictory | adopt: replaced with 2026-05-24 reconciliation summary |
| Missing implementation batch order | adopt: added batches A-E |

## Residual Implementation Order

1. RepoProxy server-owned binding refactor: completed through Batch A/A2; live Git ref re-fetch remains with transport.
2. GitHubAppAdapter broker-mediated HTTP wrapper + live Git ref re-fetch.
3. Webhook SecretBroker/replay service layer.
4. Actual `repo_pr_opened` runtime emission.
5. Agent-runs KPI endpoint or explicit superseding endpoint decision.

## Review Notes

- Do not expose raw installation tokens to RepoProxy callers.
- Do not add GitHub App permissions outside `config/github_app_permissions.toml`.
- Do not treat `repo_pr_opened` enum presence as actual runtime emission.
- Do not treat eval corpus `time_to_merge` helpers as the SP-008 `/agent-runs/{id}/kpi` endpoint.
