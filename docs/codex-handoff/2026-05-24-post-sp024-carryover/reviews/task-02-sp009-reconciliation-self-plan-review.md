# task-02 SP-009 Reconciliation Self-Plan-Review

Date: 2026-05-24

## Round 1: Structure Review

Decision: adopt docs-first reconciliation before implementation.

Findings:

1. `docs/sprints/SP-009_p0_ui_pack.md` frontmatter said backend routes were absent. Current main has real routes for tickets, agent runs, audit events, and approvals, so the old `skeleton_pending_backend` label is stale.
2. P0 backlog carry-over rows still described BL-0103a/0106a/0107a as route work. Current code closes those rows enough to mark them done, while BL-0107b and BL-EnumDrift remain open.
3. Some Playwright assertions still describe skeleton-era regions/tables. They should be handled as the next narrow contract/test PR, not mixed into the reconciliation docs.

Adopted changes:

- Reclassify SP-009 as `partial_skeleton`, not `completed`.
- Mark backend route residuals closed where current code proves implementation.
- Define the next implementation PR as contract/test cleanup only.

## Round 2: Adversarial Review

Finding A: Overclaiming completion risk.

- Risk: tickets/agent_runs/audit route existence could be mistaken for full SP-009 completion.
- Decision: adopt. The sprint remains `partial_skeleton`; at reconciliation time golden E2E, DOM secret scan, enum drift contract, unified timeline, and SP-009-5 split remained open. Task-05 closes the docs-only split while leaving implementation open.

Finding B: Wrong API route risk.

- Risk: old shorthand `GET /api/v1/tickets` could lead a future implementer to add a duplicate route and weaken project boundary.
- Decision: adopt. The docs explicitly preserve `GET /api/v1/projects/{project_id}/tickets` as the accepted route.

Finding C: Mutation scope creep risk.

- Risk: Approval `request_revision` could be smuggled into the next cleanup PR.
- Decision: adopt. The task keeps `request_revision` out of scope until ADR/API/state-machine planning is accepted.

Finding D: Redaction false confidence.

- Risk: backend redacted metadata does not prove frontend DOM cannot leak a future raw payload.
- Decision: adopt. BL-0107b remains open and the next PR must add a DOM secret scan regression.

Finding E: E2E drift invisibility.

- Risk: stale Playwright tests might silently remain unrun and misrepresent coverage.
- Decision: adopt. The next PR starts with stale Sprint 9 Playwright assertion cleanup.

## Readiness Gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM: 0 open for this docs reconciliation
- Next implementation: SP-009 contract/test cleanup
