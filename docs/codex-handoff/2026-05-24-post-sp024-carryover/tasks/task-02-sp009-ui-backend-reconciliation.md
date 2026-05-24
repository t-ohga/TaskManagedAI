# task-02: SP-009 UI / Backend Reconciliation

## Purpose

Reconcile SP-009 after later UI, API, i18n, settings, and CLI work. SP-009 currently says `skeleton_pending_backend`, but SP-012 / SP-016 / SP-024 may have closed part of the original gap.

## Required Reads

1. `docs/sprints/SP-009_p0_ui_pack.md`
2. `docs/sprints/SP-012_p0_acceptance.md`
3. `docs/sprints/SP-016_ui_cli_parity.md`
4. frontend routes under `frontend/app/(admin)/`
5. frontend API client under `frontend/lib/api/`
6. backend routes under `backend/app/api/`
7. tests covering settings, tickets, approvals, agent runs, audit, and session API

## Output

Produce a reconciliation update that answers:

- which SP-009 UI surfaces are already real,
- which backend endpoints are still absent,
- which old UI requirements are now superseded,
- which SP-009 items should become SP-009-5 or P0.1,
- which next implementation PR is smallest and safest.

## Scope Rules

- Prefer read-only list/detail wiring before mutations.
- Do not add approval `request_revision` unless a separate accepted plan exists.
- Do not expose raw provider response, raw tool args, or raw realtime payload.
- Do not make frontend KPI values source-of-truth; backend ledger remains authoritative.

## Verification Seed

```bash
corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit
corepack pnpm@10.18.0 --dir frontend exec eslint <touched-files> --max-warnings=0
corepack pnpm@10.18.0 --dir frontend exec vitest run <targeted-tests>
uv run ruff check backend/app/api tests/api
PYTHONPATH=cli uv run mypy backend/app/api tests/api
uv run pytest tests/api -q
git diff --check
```

## 2026-05-24 Reconciliation Result

Status: READY for a narrow follow-up PR.

### Already Real

- Ticket list/detail/create/update: `backend/app/api/tickets.py`, `frontend/lib/api/tickets.ts`, `/tickets`, `/tickets/[id]`.
- Approval Inbox list/detail/decide: `backend/app/api/approval_inbox.py`, `frontend/lib/api/approvals.ts`, `/approvals`, `/approvals/[id]`.
- Agent Runs list/detail/kpi/cancel: `backend/app/api/agent_runs.py`, `frontend/lib/api/agent-runs.ts`, `/runs`, `/runs/[id]`.
- Audit Events list: `backend/app/api/audit.py`, `frontend/lib/api/audit.ts`, `/audit`.

### No Longer Current

- "tickets.py / audit_events.py absent" is stale.
- "agent_runs.py is cancel only" is stale.
- `GET /api/v1/tickets` shorthand should not be implemented; the accepted route is project-scoped: `GET /api/v1/projects/{project_id}/tickets`.
- Approval `request_revision` remains out of scope until ADR/API/state-machine planning is accepted.

### Open Residuals

- `frontend/tests/e2e/sprint9-pages.spec.ts` still contains skeleton-era assertions and should be updated to real page semantics.
- Frontend/backend enum drift contract is still missing except for the narrow TicketStatus unit check.
- Frontend DOM secret scan / redaction regression is still missing even though backend API responses expose payload keys only.
- Unified execution timeline and Today/Inbox board semantics should be split to SP-009-5/P0.1 rather than hidden inside this reconciliation.

### Smallest Safe Next PR

Implement SP-009 contract/test cleanup only:

1. Update stale Sprint 9 Playwright assertions to the current real pages.
2. Add exact-set enum drift contract for TicketStatus / AgentRunStatus / BlockedReason / AgentRunEventType.
3. Add frontend DOM secret scan regression for the real AgentRun/Audit pages.
4. Leave mutation expansion and Approval `request_revision` for a separate accepted plan.
