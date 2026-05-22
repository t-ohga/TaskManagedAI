# task-07 Self-Impl-Review

Date: 2026-05-22 JST

## Scope implemented

- Added production signed-session middleware coverage:
  - missing cookie already covered
  - invalid cookie returns structured 401
  - expired cookie returns structured 401
  - valid cookie resolves tenant, actor, principal, and authenticated flag
- Added Tickets request contract coverage:
  - create request rejects caller-supplied `project_id`
  - create request rejects caller-supplied `tenant_id`
  - create request rejects caller-supplied `created_by_actor_id`
  - update request rejects the same server-owned fields
  - update request keeps absent / null / empty `description` distinct
  - empty update payload returns 400 before repository / DB access
- Added AgentRunEvent 5+ source enum coverage:
  - ORM `agent_run_events_ck_event_type` CheckConstraint exact-set comparison
    against `ALL_AGENT_RUN_EVENT_TYPES`
- Hardened optional AgentRunEvent DB probe:
  - asyncpg `PostgresError` auth failures now skip locally unless DB tests are
    explicitly forced.

## Findings

- T07-F001 / HIGH / adopt:
  - finding: valid cookie test used a fixed timestamp that was already expired
    by the current run time.
  - fix: generate the valid cookie from `datetime.now(UTC)` with a one-hour TTL.
- T07-F002 / HIGH / adopt:
  - finding: `tests/runtime/test_agent_run_events.py` did not catch asyncpg
    `InvalidPasswordError`, causing optional local DB tests to error instead of
    skip.
  - fix: include `PostgresError` in the availability probe exception set while
    preserving hard-fail behavior when `TASKMANAGEDAI_RUN_DB_TESTS=1`.
- T07-F003 / MEDIUM / adopt:
  - finding: mypy could not prove Starlette middleware `cls` identity
    comparisons.
  - fix: compare middleware class names through a small helper.
- T07-F004 / MEDIUM / adopt:
  - finding: direct `AgentRunEvent.__table__.constraints` access typed as
    generic `FromClause` under mypy.
  - fix: cast to SQLAlchemy `Table` before reading constraints.
- T07-F005 / MEDIUM / defer:
  - finding: endpoint-level 409 race coverage is not meaningful without a
    version / etag contract.
  - follow-up: add optimistic concurrency semantics before testing 409.

## Readiness gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM open: 0 for task-07 owned scope
- deferred: optimistic concurrency semantics only
- status: READY for PR

## Verification

- PASS: `uv run ruff check` on changed tests
- PASS: `uv run mypy` on changed tests
- PASS: targeted pytest on changed tests:
  - `26 passed, 20 skipped`
