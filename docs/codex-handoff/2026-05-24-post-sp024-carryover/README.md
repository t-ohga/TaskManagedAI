# Post-SP024 Carry-over Handoff (2026-05-24)

## Purpose

SP-024 closed the autonomy policy/profile/settings/trace foundation. The next candidate list that mentioned SP-014 / SP-015 / SP-016 is now stale because those Sprint Packs are `completed` in the repository.

This handoff is a safe restart package for the remaining carry-over area. It intentionally starts with reconciliation before implementation, because the open candidates include GitHub App / RepoProxy, runner trust boundary, and P0 UI backend wiring. Those touch secrets, external repository mutation, webhook verification, and API contracts.

## Read Order

| file | role |
|---|---|
| `README.md` | master index |
| `00-current-state.md` | verified state after SP-024 closeout |
| `01-carryover-scope-gate.md` | safety gate before coding |
| `02-task-priority-matrix.md` | prioritized task list and dependencies |
| `03-verification-and-review-checklist.md` | PR, inline review, and local verification gate |
| `04-codex-startup-prompt.md` | prompt for the next Codex execution |
| `tasks/task-01-sp008-residual-reconciliation.md` | SP-008 residual plan |
| `tasks/task-02-sp009-ui-backend-reconciliation.md` | SP-009 residual plan |
| `tasks/task-03-sp007-phase5-trust-boundary.md` | SP-007 Phase 5 plan |
| `tasks/task-04-status-hygiene.md` | current-state / backlog status hygiene after PRs #219-#227 |
| `tasks/task-05-sp0095-split-docs.md` | SP-009-5 P0.1 deferred UI split |
| `tasks/task-06-sp0095-readonly-ui.md` | SP-009-5 Batch A read-only Today/Inbox UI |
| `tasks/task-07-sp0095-timeline-ui.md` | SP-009-5 Batch B unified timeline UI |
| `tasks/task-08-sp0095-decision-packet.md` | SP-009-5 Batch C decision packet hash visibility |
| `tasks/task-09-sp0095-notification-triage-plan.md` | SP-009-5 Batch D notification triage plan |
| `tasks/task-10-sp0095-notification-triage-api.md` | SP-009-5 Batch D1 notification triage DB/API |
| `tasks/task-11-sp0095-notification-triage-ui.md` | SP-009-5 Batch D2 notification triage UI/actions |
| `tasks/task-12-sp0095-request-revision-plan.md` | SP-009-5 Batch E request_revision contract plan |
| `tasks/task-13-sp0095-request-revision-api.md` | SP-009-5 Batch E1 request_revision DB/API |
| `tasks/task-14-sp0095-request-revision-ui.md` | SP-009-5 Batch E2 request_revision Approval Detail UI |
| `plans/task-03-sp007-phase5-trust-boundary-plan.md` | SP-007 Phase 5 trust-boundary implementation sequence |
| `plans/task-09-sp0095-notification-triage-contract-plan.md` | Notification triage DB/API/UI contract plan |
| `plans/task-12-sp0095-request-revision-contract-plan.md` | Approval request_revision DB/API/UI/runtime contract plan |

## Operating Rule

Do not start SP-008 / SP-009 / SP-007 carry-over code directly from old Sprint Pack checkboxes. First complete task-01 or task-02 reconciliation and update the implementation batch plan with:

- exact already-shipped evidence,
- exact residual tickets,
- high-risk boundaries,
- local verification commands,
- PR review and inline comment response procedure.

## Immediate Recommendation

1. Run task-01 first: SP-008 residual reconciliation.
2. If task-01 confirms the residual is still current, implement SP-008 in the smallest safe batch order: server-owned binding, broker-mediated GitHub adapter, webhook service boundary, `repo_pr_opened` event, KPI endpoint, then docs/status closeout.
3. For SP-009-5, Batch E must use `plans/task-12-sp0095-request-revision-contract-plan.md`; E1 DB/API and E2 UI are implemented, and E3 revised-artifact handoff remains.
4. Run task-05 before SP-009 P0.1 UI code; it separates read-only UI surfaces from ADR/API-gated mutation surfaces.
5. Run task-02 before any remaining SP-009 code because SP-012 / SP-016 already changed the UI and CLI surface.
6. Run task-03 only as planning unless the user explicitly wants repo-external hook trust changes applied on this machine. The current plan artifact is `plans/task-03-sp007-phase5-trust-boundary-plan.md`.
