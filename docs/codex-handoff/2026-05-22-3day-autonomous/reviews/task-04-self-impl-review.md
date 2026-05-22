# task-04 Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- SP-012-9 residual page wiring
- backend read-only APIs for AI Runs, Audit Log, and project list
- frontend API clients and Server Component pages
- route/redaction tests and existing i18n test updates
- Sprint Pack completion and task completion artifact

## Findings

- T04-F001 / HIGH / adopt:
  - finding: `/runs` and `/audit` could not be wired with real data because
    backend read routes were absent or draft-only.
  - fix: Added read-only `GET /api/v1/agent_runs`,
    `GET /api/v1/agent_runs/{id}`, and `GET /api/v1/audit_events`.
- T04-F002 / HIGH / adopt:
  - finding: Directly exposing AgentRunEvent or AuditEvent payload JSON would
    create a DOM leakage path for raw secret-shaped values.
  - fix: API responses expose `payload_keys` and
    `payload_redaction_status` only. If the shared secret scanner rejects the
    payload, keys are suppressed.
- T04-F003 / MEDIUM / adopt:
  - finding: Approvals list was wired only for pending requests, so approved /
    rejected / expired / invalidated review was unavailable.
  - fix: Added a backend `status` query filter and frontend status filter
    navigation.
- T04-F004 / MEDIUM / adopt:
  - finding: Settings page had no backend-backed project list and could only
    show static provider/policy skeleton data.
  - fix: Added `GET /api/v1/me/projects` and wired Settings to show current
    project plus read-only tenant project rows.
- T04-F005 / MEDIUM / adopt:
  - finding: Existing optional DB API tests treated asyncpg authentication
    failures as hard errors instead of local-skip conditions.
  - fix: Added `PostgresError` to the skip probe for approval and agent-run
    API tests; forced DB runs still hard-fail with `TASKMANAGEDAI_RUN_DB_TESTS=1`.
- T04-F006 / MEDIUM / defer:
  - finding: Persistent project switching and provider config mutation require
    membership/session semantics outside this task.
  - follow-up: Keep project switching, provider settings mutation, audit
    export, and run resume/cancel UI as SP-018 / multi-user follow-up.

## Readiness Gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM open: 0 for task-04 owned scope
- deferred: mutation/export/project-switching follow-up only
- status: READY for PR

## Verification

- targeted backend `ruff`
- targeted backend `mypy`
- targeted backend `pytest`
  - result: `7 passed, 12 skipped`
- frontend `pnpm typecheck`
- frontend `pnpm lint`
- frontend `pnpm test`
  - result: `22 passed / 90 tests`
- `git diff --check`
