# Task Priority Matrix

## Prioritized Tasks

| priority | task | source | scope | plan required | expected effort |
|---|---|---|---|---|---|
| P0 | task-01 | SP-008 | GitHub App / RepoProxy residual reconciliation | required | 0.3-0.5 day |
| P0 | task-02 | SP-009 | P0 UI backend/frontend residual reconciliation | required | 0.3-0.5 day |
| P1 | task-03 | SP-007 | Phase 5 hook trust boundary plan | required before machine-local changes | 0.2-0.4 day |
| P1 | task-05 | SP-009-5 | P0.1 deferred UI surface split | required before SP-009-5 UI/code | 0.2 day |
| P1 | task-06 | SP-009-5 | Today/Inbox + minimal KPI strip read-only UI | completed 2026-05-24 | 0.5 day |
| P1 | task-07 | SP-009-5 | Unified execution timeline read-only UI | completed 2026-05-24 | 0.5 day |
| P1 | task-10 | SP-009-5 | Notification triage D1 DB/API contract | completed 2026-05-24 | 0.5 day |
| P1 | task-11 | SP-009-5 | Notification triage D2 UI/actions | completed 2026-05-24 | 0.5 day |
| P1 | task-12 | SP-009-5 | Request revision contract plan | completed 2026-05-24; E1-E3 implemented | 0.2 day |
| P1 | task-13 | SP-009-5 | Request revision E1 DB/API | completed 2026-05-24 | 0.5 day |
| P1 | task-14 | SP-009-5 | Request revision E2 Approval Detail UI | completed 2026-05-24 | 0.3 day |
| P1 | task-15 | SP-009-5 | Request revision E3 revised artifact handoff | completed 2026-05-24 | 0.4 day |
| P1 | task-16 | SP-009-5 | Newcomer Path F0 contract plan | completed 2026-05-24; F1 implemented, F2+ pending | 0.2 day |
| P1 | task-17 | SP-009-5 | Newcomer Path F1 read-only `/onboarding` UI | completed 2026-05-24; F2+ pending | 0.3 day |
| P1 | task-18 | SP-009-5 | Newcomer Path F2 guided intake dry-run contract plan | completed 2026-05-24; F2b implemented in task-19 | 0.2 day |
| P1 | task-19 | SP-009-5 | Newcomer Path F2b response-only dry-run backend API | completed 2026-05-24; F3 UI pending | 0.4 day |
| P1 | task-20 | SP-009-5 | Newcomer Path F3 dry-run plan-review UI | completed 2026-05-24; F4 CLI pending | 0.4 day |
| P2 | task-04 | SP-000 / roadmap | bootstrap/backlog status hygiene | optional docs-only (completed 2026-05-24) | 0.2 day |

## Recommended Order

```text
task-01 (SP-008 reconciliation)
  -> if READY: SP-008 implementation batches in separate PRs

task-02 (SP-009 reconciliation)
  -> completed through SP-009 contract/test cleanup PR

task-03 (SP-007 Phase 5 plan)
  -> plan artifact ready; implementation only after explicit machine-local trust-boundary approval

task-04 (status hygiene)
  -> completed after PR #227: current-state, backlog carry-over, and task index reconciled

task-05 (SP-009-5 split docs)
  -> completed before SP-009-5 UI/code: read-only UI and ADR/API-gated mutation surfaces separated

task-06 (SP-009-5 Batch A)
  -> completed: /today read-only Today/Inbox + minimal KPI strip using existing APIs only

task-07 (SP-009-5 Batch B)
  -> completed: /timeline unified read-only timeline using existing APIs only

task-10 (SP-009-5 Batch D1)
  -> completed: notification triage DB/API contract, redacted triage endpoint, snooze/resolve lifecycle, frontend client schema

task-11 (SP-009-5 Batch D2)
  -> completed: /notifications triage UI/actions using the D1 redacted API contract

task-12 (SP-009-5 Batch E0)
  -> completed: request_revision contract plan; E1 DB/API, E2 UI, and E3 revised-artifact handoff are implemented

task-13 (SP-009-5 Batch E1)
  -> completed: additive approval_revision_requests table, request_revision API/service, audit/notification metadata-only events

task-14 (SP-009-5 Batch E2)
  -> completed: Approval Detail request_revision form/action, no bulk action, no rationale echo in UI result

task-15 (SP-009-5 Batch E3)
  -> completed: internal revised artifact handoff service, fresh decision-packet guard, supersession wiring

task-16 (SP-009-5 Batch F0)
  -> completed: Newcomer Path contract plan; F1 read-only /onboarding is implemented; F2+ API/schema-gated dry-run plan remains next

task-17 (SP-009-5 Batch F1)
  -> completed: read-only /onboarding route, safe starter cards, navigation, Vitest, and desktop/mobile Playwright smoke; next implementation is F2 API/schema-gated dry-run plan

task-18 (SP-009-5 Batch F2 plan)
  -> completed: response-only dry-run intake API contract; F2b backend schema/service/API/tests are implemented in task-19

task-19 (SP-009-5 Batch F2b)
  -> completed: /api/v1/onboarding/dry_run_plan response-only backend contract; next implementation is F3 plan-review UI

task-20 (SP-009-5 Batch F3)
  -> completed: /onboarding dry-run form and plan-review rendering; next implementation is F4 CLI onboarding parity notes/tests
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
| F | webhook concrete route/adapters (completed 2026-05-24 Batch C2) | Tailscale-only ingress + raw HMAC material boundary |
| G | SP-008 status closeout + ADR/sprint docs | docs drift |

## SP-009 Tentative Implementation Batches

These are not coding instructions until task-02 marks them `READY`.

| batch | tentative scope | high-risk boundary |
|---|---|---|
| A | route/API existence diff after SP-012 and SP-016 (completed 2026-05-24 reconciliation) | API contract drift |
| B | read-only UI wiring gaps only (no backend route gap found for core four surfaces) | no mutation expansion |
| C | redaction and enum drift contract tests (completed 2026-05-24) | raw payload non-exposure |
| D | SP-009-5 split for Today/Inbox, unified timeline, request_revision, notification triage, KPI strip (completed 2026-05-24 docs-only) | scope control |

## SP-009-5 Tentative Implementation Batches

These are not coding instructions until a dedicated SP-009-5 implementation PR selects one batch and confirms the gate.

| batch | tentative scope | high-risk boundary |
|---|---|---|
| A | Today/Inbox + minimal KPI strip read-only UI (completed 2026-05-24) | existing API only; no mutation |
| B | unified execution timeline read-only UI (completed 2026-05-24) | raw payload / secret DOM exposure |
| C | decision packet hash visibility (completed 2026-05-24) | API field availability; no state transition |
| D1 | notification triage DB/API contract (completed 2026-05-24) | ADR-00003 event schema + migration |
| D2 | notification triage `/notifications` UI actions (completed 2026-05-24) | actor-owned transitions; no bulk action |
| E0 | approval `request_revision` contract plan (completed 2026-05-24) | no status enum expansion; old approval invalidated; replacement approval creates new row |
| E1 | approval `request_revision` DB/API (completed 2026-05-24) | additive table, human-only decider, raw-secret scan, migration up/down |
| E2 | approval `request_revision` UI action (completed 2026-05-24) | no bulk action; rationale redaction and DOM non-exposure |
| E3 | revised artifact handoff (completed 2026-05-24) | supersession wiring and stale hash negative tests |
| F0 | Newcomer Path contract plan (completed 2026-05-24) | read-only first route before API/schema/runtime gates; `tm` canonical CLI drift fix |
| F1 | Newcomer Path read-only `/onboarding` UI (completed 2026-05-24) | existing APIs only; no mutating AgentRun |
| F2a | guided intake dry-run API contract plan (completed 2026-05-24) | response-only decision; no persistence |
| F2b | guided intake dry-run backend contract implementation (completed 2026-05-24) | no implicit execution; server resolves effective action/approval |
| F3 | plan-review surface (completed 2026-05-24) | no implicit run start without approval/runtime handoff |
| F4 | CLI onboarding parity notes/tests | `tm` canonical; ambiguous mutating command fail-closed |

## SP-007 Phase 5 Plan

| phase | scope | write boundary |
|---|---|---|
| 5A | docs and temp-home tests/helper scaffolding (completed 2026-05-24) | repository only |
| 5B | wrapper candidate and manifest verification in temp trust root (completed 2026-05-24) | repository only |
| 5C | install `~/.claude-trusted` wrapper, manifest, trusted state, and settings switch | repo-external; requires explicit approval |
| 5D | SP-007 closeout and status update | repository docs after evidence |

## Common Verification

- Backend change: `uv run ruff check ...`, `PYTHONPATH=cli uv run mypy ...`, targeted `uv run pytest ... -q`.
- Frontend change: `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`, eslint for touched files, targeted vitest.
- Migration change: upgrade head, downgrade -1, upgrade head, current head. `alembic check` may remain blocked by existing `target_metadata` debt and must be documented separately.
- PR review: GraphQL review thread query plus `.claude/scripts/codex_pr_full_review.sh <PR>` after a short delay, then adopt/reject/defer every finding.
