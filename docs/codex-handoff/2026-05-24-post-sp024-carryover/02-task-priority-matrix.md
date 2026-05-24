# Task Priority Matrix

## Prioritized Tasks

| priority | task | source | scope | plan required | expected effort |
|---|---|---|---|---|---|
| P0 | task-01 | SP-008 | GitHub App / RepoProxy residual reconciliation | required | 0.3-0.5 day |
| P0 | task-02 | SP-009 | P0 UI backend/frontend residual reconciliation | required | 0.3-0.5 day |
| P1 | task-03 | SP-007 | Phase 5 hook trust boundary plan | required before machine-local changes | 0.2-0.4 day |
| P2 | task-04 | SP-000 / roadmap | bootstrap/backlog status hygiene | optional docs-only | 0.2 day |

## Recommended Order

```text
task-01 (SP-008 reconciliation)
  -> if READY: SP-008 implementation batches in separate PRs

task-02 (SP-009 reconciliation)
  -> if READY: SP-009 narrow backend/API or UI PR, not both unless plan requires it

task-03 (SP-007 Phase 5 plan)
  -> implementation only after explicit machine-local trust-boundary approval
```

## SP-008 Tentative Implementation Batches

These are not coding instructions until task-01 marks them `READY`.

| batch | tentative scope | high-risk boundary |
|---|---|---|
| A | residual server-owned 4-binding signature / request fingerprint refactor | API contract + SecretBroker fingerprint |
| B | GitHubAppAdapter broker-mediated adapter boundary | raw token non-exposure + GitHub API boundary |
| C | webhook SecretBroker/replay service boundary | raw HMAC secret redaction + replay defense |
| D | `repo_pr_opened` AgentRunEvent writer + runtime call-site wiring | append-only event contract |
| E | AC-KPI-02 `time_to_merge` endpoint/helper (completed 2026-05-24 Batch E) | KPI source-of-truth and duplicate counting |
| F | SP-008 status closeout + ADR/sprint docs | docs drift |

## SP-009 Tentative Implementation Batches

These are not coding instructions until task-02 marks them `READY`.

| batch | tentative scope | high-risk boundary |
|---|---|---|
| A | route/API existence diff after SP-012 and SP-016 | API contract drift |
| B | read-only UI wiring gaps only | no mutation expansion |
| C | redaction and enum drift contract tests | raw payload non-exposure |
| D | status closeout or new SP-009-5 split | scope control |

## Common Verification

- Backend change: `uv run ruff check ...`, `PYTHONPATH=cli uv run mypy ...`, targeted `uv run pytest ... -q`.
- Frontend change: `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`, eslint for touched files, targeted vitest.
- Migration change: upgrade head, downgrade -1, upgrade head, current head. `alembic check` may remain blocked by existing `target_metadata` debt and must be documented separately.
- PR review: GraphQL review thread query plus `.claude/scripts/codex_pr_full_review.sh <PR>` after a short delay, then adopt/reject/defer every finding.
