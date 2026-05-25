# task-21 SP-009-5 Batch F4 CLI Onboarding Parity

## Scope

Implement the Newcomer Path CLI parity slice from the Batch F contract plan.

F4 keeps `tm` as the canonical CLI spelling and adds only safe first-use helpers. It must not add a path that silently starts a mutating run, creates workflow state, or uses the stale `tmai` name as canonical.

## Boundary

- Add `tm context show` as a read-only current-project context surface.
- Add `tm doctor` as a read-only backend reachability surface.
- Add `tm run plan --dry-run` for response-only dry-run planning.
- Add `tm ticket intake --guided` as the guided intake spelling for the same response-only dry-run endpoint.
- Do not create tickets, AgentRuns, approvals, approval revisions, notifications, audit events, repository operations, provider calls, capability tokens, merge/deploy actions, or persisted onboarding state.
- Omit `--dry-run` / `--guided` must fail before any network request.

## DoD

- [x] `tm` remains the only canonical CLI spelling in docs/tests.
- [x] `context show` and `doctor` are read-only capabilities outside the SP-016 13-capability matrix.
- [x] `run plan --dry-run` and `ticket intake --guided` call `POST /api/v1/onboarding/dry_run_plan`.
- [x] Ambiguous non-dry-run onboarding commands fail closed before network.
- [x] CLI tests cover the new surfaces and no-network failure cases.

## Verification

- passed: `uv run ruff check cli/tm tests/cli/test_tm_cli_foundation.py`
- passed: `PYTHONPATH=cli uv run mypy cli/tm tests/cli/test_tm_cli_foundation.py`
- passed: `uv run pytest tests/cli/test_tm_cli_foundation.py -q`

## Residual

- F5 closeout was closed by task-22.
