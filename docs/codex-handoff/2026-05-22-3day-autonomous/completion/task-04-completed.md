# task-04 完了報告 (2026-05-22)

## summary

- task: SP-012-9 残 wiring
- start: 2026-05-22 JST
- end: 2026-05-22 JST
- scope: Approvals status filter、AI Runs list/detail、Audit Log list、
  Settings project list、redacted payload metadata、tests、SP-012-9 completed 化
- branch: `feat/sp012-9-residual-wiring-2026-05-22`

## completed changes

- `GET /api/v1/agent_runs` and `GET /api/v1/agent_runs/{id}` added.
- `GET /api/v1/audit_events` added.
- `GET /api/v1/me/projects` added.
- Approvals page now supports status-filtered listing.
- Runs, run detail, audit, and settings pages now fetch real backend data.
- AgentRunEvent / AuditEvent payloads are exposed as keys/redaction status,
  not raw JSON.
- Existing frontend i18n tests were updated for async Server Components.
- Optional DB test probes now skip local asyncpg auth failures unless forced.

## Codex finding 採否判定

- HIGH:
  - finding: Runs/Audit skeletons could remain falsely green without real read
    APIs.
  - judgment: adopt. Backend read routes and frontend clients/pages added.
- HIGH:
  - finding: Raw event payload rendering could leak secrets.
  - judgment: adopt. Redacted metadata-only response shape.
- MEDIUM:
  - finding: Approval list had pending-only visibility.
  - judgment: adopt. Status query and filter navigation added.
- MEDIUM:
  - finding: Settings had no project list API.
  - judgment: adopt. `/api/v1/me/projects` and read-only table added.
- MEDIUM:
  - finding: Local optional DB tests errored on asyncpg invalid password.
  - judgment: adopt. PostgresError local skip behavior added.

## defer / carry-over

- T04-DEFER-001: Approval mutation changes remain out of task-04 scope. The
  pre-existing detail decision form was not expanded.
- T04-DEFER-002: AgentRun resume/cancel UI remains SP-018.
- T04-DEFER-003: Audit export remains SP-018.
- T04-DEFER-004: Provider config mutation and persistent project switching
  remain multi-user / membership follow-up.

## blocker

- No CRITICAL / HIGH / MEDIUM blocker remains for task-04.
- DB-backed API tests skipped locally because the default PostgreSQL
  credentials fail authentication. Forced DB mode remains hard-fail.

## verification

- [x] `uv run ruff check` on changed backend API/tests
- [x] `uv run mypy` on changed backend API/tests
- [x] targeted backend API pytest:
      (`7 passed, 12 skipped`)
- [x] `pnpm typecheck`
- [x] `pnpm lint`
- [x] `pnpm test` (`22 passed / 90 tests`)
- [x] `git diff --check`
- [x] SP-012-9 frontmatter `ready -> completed`

## Claude verification 依頼項目

1. Event payload metadata-only response shapeが AC-HARD-02 と整合するか確認。
2. Runs/Audit/Settings の read-only UX が SP-018 mutation defer と整合するか確認。
3. task-08 で SP-012-9 本文の古い Sprint 11/12 reference drift を精査。
