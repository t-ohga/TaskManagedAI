# task-05 batch C Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- `ContextSnapshotRepository.create_snapshot` tool manifest boundary
- resume snapshot tool manifest inheritance
- Agent runtime resume snapshot wiring
- ContextSnapshot evidence hash and invariant regression tests
- local DB availability skip behavior for optional DB-backed tests

## Findings

- T05-BATCH-C-F001 / HIGH / adopt:
  - finding: `ContextSnapshotRepository.create_snapshot` still accepted
    caller-supplied `tool_manifest`, which violated the server-owned lock
    boundary introduced by SP-0045.
  - fix: Removed `tool_manifest` from the public repository and wrapper
    signatures. Normal snapshots now bind `current_tool_manifest()` inside the
    repository, and a TypeError regression test rejects caller-supplied
    manifest material.
- T05-BATCH-C-F002 / HIGH / adopt:
  - finding: resume snapshot wiring passed `previous_snapshot.tool_manifest`
    through the public wrapper, preserving the value but not the boundary.
  - fix: Replaced value pass-through with
    `inherit_tool_manifest_from_snapshot_id`; the repository loads the prior
    manifest from the DB row scoped to `(tenant_id, run_id, snapshot_id)`.
- T05-BATCH-C-F003 / HIGH / adopt:
  - finding: resume callers could inherit `evidence_set_hash` from one
    snapshot and `tool_manifest` from another, producing an impossible
    reproducibility lock pair.
  - fix: Added a guard requiring both inheritance IDs to reference the same
    ContextSnapshot row and covered the mismatch with a regression test.
- T05-BATCH-C-F004 / MEDIUM / adopt:
  - finding: DB-backed ContextSnapshot tests surfaced
    `asyncpg.exceptions.InvalidPasswordError` instead of skipping when the
    optional local test DB was unavailable.
  - fix: The availability probes now catch `asyncpg` PostgreSQL errors and
    still raise hard failures when `TASKMANAGEDAI_RUN_DB_TESTS=1` requests a
    mandatory DB run.
- T05-BATCH-C-F005 / MEDIUM / adopt:
  - finding: `_inherit_tool_manifest` had no DB-free regression, so local
    verification without PostgreSQL could not exercise the new server-owned
    lookup path.
  - fix: Added fake-session tests for scoped statement construction, successful
    manifest inheritance, and missing prior snapshot rejection.

## Readiness gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM open: 0 for batch C implementation
- deferred: live DB-backed tests skipped locally because the default
  `taskmanagedai_test` PostgreSQL credentials are unavailable; forced DB mode
  remains a hard failure.
- status: READY for PR

## Verification

- targeted ruff on the ContextSnapshot repository, orchestrator, and updated
  ContextSnapshot test files
- targeted mypy on the same implementation and test files
- targeted pytest for evidence hash and runtime invariant tests
  - result: 14 passed, 26 skipped
  - skipped: optional DB-backed cases skipped due local PostgreSQL
    authentication failure without `TASKMANAGEDAI_RUN_DB_TESTS=1`
- Tool Registry loader validate for `config/tool_registry.toml`
- `git diff --check`
