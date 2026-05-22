# task-04 Self-Plan-Review (SP-012-9 residual wiring)

Date: 2026-05-22 JST

## Scope

- task: SP-012-9 residual wiring
- pages: Approvals, AI Runs, Audit Log, Settings
- existing pattern: Tickets page and `frontend/lib/api/tickets.ts`
- explicit defer: approval mutation changes, run resume/cancel UI, audit export,
  provider/settings mutation, and multi-project membership switching

## Round 1: structural review

### Current inventory

- Approvals:
  - backend `approval_inbox.py` has list/detail/decide routes.
  - frontend list/detail already fetch real data, but list is pending-only and
    the API client has no status filter.
- AI Runs:
  - backend `agent_runs.py` only exposes cancel.
  - frontend `/runs` and `/runs/[id]` are static skeletons; API client keeps
    draft `_listAgentRunsDraft` / `_getAgentRunDraft` helpers.
- Audit Log:
  - no read API route exists for `audit_events`.
  - frontend audit page is static sample data; API client is draft-only.
- Settings:
  - backend has `/api/v1/me/current_project`.
  - no project list route exists; settings page is static sample data.

### Planned batches

- batch A: backend read APIs
  - add `GET /api/v1/agent_runs` and `GET /api/v1/agent_runs/{id}`.
  - add `GET /api/v1/audit_events`.
  - add `GET /api/v1/me/projects`.
- batch B: frontend API clients
  - promote Runs and Audit clients from draft helpers to real functions.
  - add Approval status filter support.
  - add project list support to session/settings helpers.
- batch C: page wiring
  - wire `/approvals`, `/runs`, `/runs/[id]`, `/audit`, and `/settings`.
  - keep mutation controls deferred unless they already existed before task-04.
- batch D: tests, Sprint Pack review, self-review, and completion artifact.

### Structural decisions

- Use existing routes `/runs` rather than introducing `/agent-runs` because
  navigation and current app structure already use `/runs`.
- Expose AgentRunEvent and Audit payloads as redacted metadata only:
  `payload_keys` / `payload_redaction_status`, not raw JSON values.
- Keep project selection read-only for P0.1 because current backend only has a
  single-project session model and no actor-project membership table.
- Do not add migrations. All added routes read existing tables.
- Use fixed `limit=50` defaults and simple offset pagination; richer controls
  remain SP-018.

## Round 1 findings

- T04-PLAN-R1-F001 / HIGH / adopt:
  - finding: Runs and Audit pages cannot be wired safely without backend read
    routes; draft frontend helpers would otherwise keep skeleton behavior.
  - planned fix: Add read-only FastAPI routes with tenant/session dependencies.
- T04-PLAN-R1-F002 / HIGH / adopt:
  - finding: Raw `event_payload` / `audit_payload` values could expose
    sensitive strings if sent directly to the DOM.
  - planned fix: API responses expose only sorted payload keys plus a redaction
    status and suppress keys entirely if the existing secret scanner fails.
- T04-PLAN-R1-F003 / MEDIUM / adopt:
  - finding: Approvals list is pending-only although the task asks for
    all-status visibility.
  - planned fix: Add a status query parameter and render status filter links.
- T04-PLAN-R1-F004 / MEDIUM / defer:
  - finding: Settings project switching needs persistent session/project
    membership semantics that do not exist in P0.1 yet.
  - planned fix: Show current project and tenant project list read-only; record
    switching as SP-018/multi-user follow-up.

## Readiness gate

- CRITICAL: 0
- HIGH: 0 open after planned adoption
- status: READY for implementation
