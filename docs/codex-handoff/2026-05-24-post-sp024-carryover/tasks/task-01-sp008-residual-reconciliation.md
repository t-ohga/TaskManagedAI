# task-01: SP-008 Residual Reconciliation

## Purpose

Reconcile SP-008 GitHub App / RepoProxy before any new code. SP-008 is high-risk because it controls external repository mutation, installation-token use, Draft PR creation, webhook handling, and KPI measurement.

## Required Reads

1. `docs/sprints/SP-008_github_app_repoproxy.md`
2. `docs/adr/00011_github_app_permission_matrix.md`
3. `docs/adr/00006_secrets_management.md`
4. `docs/adr/00009_action_class_taxonomy.md`
5. `docs/実装計画/P0_バックログ.md` rows BL-0094 through BL-0102 and carry-over rows around BL-0094 / BL-0095 / BL-0097 / BL-0100 / BL-0102
6. Existing `backend/app/services/repoproxy/`, `tests/repoproxy/`, `backend/app/services/secrets/`, and AgentRun event domain files

## Output

Produce a small docs-only PR or Sprint Review update that contains:

- exact shipped evidence for each SP-008 BL,
- exact residual list,
- adopted implementation batch order,
- verification commands,
- PR review procedure,
- explicit defer/reject list.

## Initial Residual Hypothesis

Validate this; do not assume it is final:

| residual | likely status source | required decision |
|---|---|---|
| BL-0096a 4-binding signature refactor | SP-008 review summary | confirm whether later SecretBroker/policy work already closed it |
| BL-0097 GitHubAppAdapter HTTP wrapper | SP-008 review summary | likely still needed; must remain broker-mediated |
| BL-0100 `repo_pr_opened` actual emission | SP-008 review summary | event writer + DB append test added in Batch D; `DraftPRRuntime` call-site wrapper added in Batch D2; external API/worker adoption remains after real GitHub transport is enabled |
| BL-0102 KPI endpoint/helper | SP-008 review summary | completed 2026-05-24 Batch E as `GET /api/v1/agent_runs/{run_id}/kpi` + `AgentRunKpiService`; true PR merged timestamp remains future event source |
| BL-0101a webhook route/adapters | SP-008 review summary | concrete SecretRef resolver + Redis SETNX replay adapter + FastAPI `POST /webhooks/github` added in Batch C2; deployment SOPS material resolver remains runtime wiring |
| GitHub App admin registration / secret metadata | P0 backlog carry-over | confirm whether real admin setup is available or should remain stubbed |

## 2026-05-24 Reconciliation Result

The hypothesis is adopted with refinements:

- SecretBroker repo operation primitives exist, but end-to-end RepoProxy issue/redeem integration is not proven.
- `repo_pr_opened` exists as an event enum and now has event writer + `DraftPRRuntime` call-site coverage; external API/worker adoption waits for real GitHub transport.
- KPI code existed for eval corpus and orchestrator proxy rollup. 2026-05-24 Batch E added the canonical SP-008 endpoint `GET /api/v1/agent_runs/{run_id}/kpi`.
- Webhook HMAC now has service + route/adapters coverage. The remaining deployment piece is the raw material resolver that decrypts SOPS material for the already-registered `secret_refs` metadata row.
- ADR-00011 remains accepted as a design decision, but its previous acceptance history overstated implementation closure.

See `../reviews/task-01-sp008-residual-reconciliation.md` and the 2026-05-24 SP-008 Review entry.

## Plan Review Requirements

- CRITICAL=0 before implementation can start.
- Any raw token exposure path is CRITICAL and must block.
- Any new GitHub App permission outside ADR-00011 must block.
- Any direct `.github/workflows/**` write capability must block.
- Any Draft PR self-approval path must block.

## Verification Seed

Use or update these commands after reconciliation identifies touched files:

```bash
uv run ruff check backend/app/services/repoproxy tests/repoproxy
PYTHONPATH=cli uv run mypy backend/app/services/repoproxy tests/repoproxy
uv run pytest tests/repoproxy -q
git diff --check
```
