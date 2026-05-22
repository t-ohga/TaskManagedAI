# task-05 batch D Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- Tool Registry contract/adversarial tests
- SP-0045 Sprint Pack `completed` transition
- task-05 completion artifact

## Findings

- T05-BATCH-D-F001 / HIGH / adopt:
  - finding: Batch A loader tests verified enum sources, but there was no
    dedicated guard proving Tool Registry read-only actions stay disjoint from
    policy `action_class` values.
  - fix: Added `test_registry_contracts.py` to assert `allowed_actions` and
    the seven policy action classes are disjoint.
- T05-BATCH-D-F002 / HIGH / adopt:
  - finding: P0 mutating tool actions could drift into
    `config/tool_registry.toml` without a DB-backed test running locally.
  - fix: Added a DB-free contract test asserting configured actions equal the
    canonical read-only set and remain disjoint from P0 mutating tool actions.
- T05-BATCH-D-F003 / MEDIUM / adopt:
  - finding: Missing `max_outgoing_data_class` was documented as
    fail-closed, but there was no narrow loader regression for the unset
    classification case.
  - fix: Added a negative loader test requiring a validation failure when a
    tool entry omits `max_outgoing_data_class`.
- T05-BATCH-D-F004 / MEDIUM / adopt:
  - finding: Duplicate per-tool `allowed_actions` could make registry intent
    ambiguous even when the final set is unchanged.
  - fix: Added a regression for duplicate action rejection.
- T05-BATCH-D-F005 / MEDIUM / defer:
  - finding: Full DB-backed Tool Registry and ContextSnapshot tests remain
    dependent on local PostgreSQL credentials unavailable in this worktree.
  - follow-up: Keep DB runs as forced hard-fail checks with
    `TASKMANAGEDAI_RUN_DB_TESTS=1`; local non-DB contract checks cover batch D.

## Readiness gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM open: 0 for batch D implementation
- deferred: live DB execution only, due local credential availability
- status: READY for PR

## Verification

- targeted ruff for `tests/services/tool_registry/test_registry_contracts.py`
- targeted mypy for `tests/services/tool_registry/test_registry_contracts.py`
- targeted pytest for Tool Registry loader and contract tests
  - result: 10 passed
- Tool Registry loader validate for `config/tool_registry.toml`
- new artifact markdownlint clean
- `git diff --check`
