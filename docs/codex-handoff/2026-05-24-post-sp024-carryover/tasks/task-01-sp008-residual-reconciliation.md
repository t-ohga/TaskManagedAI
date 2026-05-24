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
| BL-0100 `repo_pr_opened` actual emission | SP-008 review summary | likely still needed; must be append-only and raw-token-free |
| BL-0102 KPI endpoint/helper | SP-008 review summary | may overlap later metrics code; inspect before code |
| GitHub App admin registration / secret metadata | P0 backlog carry-over | confirm whether real admin setup is available or should remain stubbed |

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
