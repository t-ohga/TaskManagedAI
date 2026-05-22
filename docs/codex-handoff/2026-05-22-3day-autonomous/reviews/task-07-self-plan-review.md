# task-07 Self-Plan-Review

Date: 2026-05-22 JST

## Scope

- Backend test coverage expansion for post-PR #100 untested branches.
- No production code behavior change planned.
- Primary targets:
  - dev session cookie valid / invalid / expired branches
  - Tickets request contract server-owned fields and clearable description
  - AgentRunEvent event_type cross-source enum integrity, including ORM CHECK

## Round 1 inventory

- Tickets API already has DB-backed repository coverage for project boundary,
  create, update, and cross-project negative paths.
- Dev actor middleware covered default dev/test fallback and production missing
  cookie, but not invalid, expired, or valid signed session cookie resolution.
- AgentRunEvent already covered Literal, canonical tuple, Pydantic schema, and
  migration CHECK source. ORM CheckConstraint source was not independently
  asserted.
- Policy profile seed coverage is already strong: exact profiles, exact 14
  action-effect rows, trigger-based new-tenant seed, FK rejection, repository
  server-owned boundary, and fail-closed resolver.

## Adopt / defer

- T07-PLAN-F001 / HIGH / adopt:
  - finding: production session middleware could regress invalid/expired cookie
    rejection or valid cookie actor resolution without a local test.
  - planned fix: add three explicit request-context tests with exact status and
    actor context assertions.
- T07-PLAN-F002 / HIGH / adopt:
  - finding: Tickets request models could accidentally accept caller-supplied
    `tenant_id`, `project_id`, or `created_by_actor_id`.
  - planned fix: add one test per field for create and update request shapes.
- T07-PLAN-F003 / MEDIUM / adopt:
  - finding: `description` clear semantics depend on `exclude_unset=True`; null,
    empty string, and absent field must remain distinct.
  - planned fix: add separate tests for absent / null / empty string.
- T07-PLAN-F004 / MEDIUM / adopt:
  - finding: AgentRunEvent enum 5+ source coverage lacked direct ORM
    CheckConstraint comparison after SP-014 event_type 37.
  - planned fix: parse ORM CHECK values and compare exact set to
    `ALL_AGENT_RUN_EVENT_TYPES`.
- T07-PLAN-F005 / MEDIUM / defer:
  - finding: 404 vs 409 concurrent endpoint race coverage needs DB/API
    concurrency fixture and possibly endpoint semantics clarification.
  - reason: current implementation does not expose optimistic concurrency
    fields. Keep as future API-contract enhancement, not a weak synthetic test.

## Readiness gate

- CRITICAL: 0
- HIGH open: 0 after planned adoption
- status: READY for implementation
