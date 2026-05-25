# task-22 SP-009-5 Batch F5 Newcomer Path Closeout

## Scope

Close the Newcomer Path Batch F status after F0-F4 shipped through PRs #240-#244.

This is a docs/status/verification synchronization task. It must not add new runtime behavior, persisted onboarding state, dry-run storage, approval shortcuts, AgentRun start paths, repository operations, provider calls, SecretBroker resolution, merge, or deploy behavior.

## Route/API/CLI Parity

| surface | shipped behavior | verification source |
|---|---|---|
| `/onboarding` | read-only first-use route plus dry-run form/result review | frontend Vitest and desktop/mobile smoke from F1/F3 |
| `POST /api/v1/onboarding/dry_run_plan` | deterministic response-only dry-run plan; no workflow state creation | backend schema/API/service pytest from F2b |
| `tm context show` | read-only current-project context helper | CLI contract tests from F4 |
| `tm doctor` | read-only backend reachability helper | CLI contract tests from F4 |
| `tm ticket intake --guided` | response-only dry-run intake; required flag fail-closed | CLI contract tests from F4 |
| `tm run plan --dry-run` | response-only dry-run plan; required flag fail-closed | CLI contract tests from F4 |

## Closeout Decisions

- Dry-run plans remain response-only and non-persistent.
- Persisted onboarding state remains deferred until a separate API/schema/runtime plan accepts storage, retention, and visibility semantics.
- No approve/start execution UI or CLI shortcut is added in F5.
- F5 does not change SP-009-5 pack status to `completed` because non-Newcomer SP-009-5 residuals remain tracked separately.

## DoD

- [x] Route/API/CLI parity docs mention `/onboarding`, `/api/v1/onboarding/dry_run_plan`, and `tm` newcomer commands.
- [x] SP-009-5 Review lists F1-F4 verification evidence plus F5 closeout verification.
- [x] P0 backlog marks `SP0095-UX-01` Newcomer Path completed.
- [x] Handoff startup prompt no longer points the next run at F5.
- [x] No dry-run persistence, onboarding state persistence, provider call, SecretBroker call, AgentRun start, approval creation, repository operation, merge, or deploy path is added.

## Verification

- `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/onboarding-page.test.tsx __tests__/onboarding-actions.test.ts __tests__/onboarding-dry-run-plan-form.test.tsx __tests__/lib/api/onboarding.test.ts __tests__/navigation.test.tsx`
- `uv run ruff check backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py cli/tm tests/cli/test_tm_cli_foundation.py`
- `PYTHONPATH=cli uv run mypy backend/app/api/onboarding.py backend/app/schemas/onboarding.py backend/app/services/onboarding/dry_run_plan.py cli/tm tests/cli/test_tm_cli_foundation.py`
- `uv run pytest tests/api/test_onboarding_dry_run_plan.py tests/services/test_onboarding_dry_run_plan_service.py tests/cli/test_tm_cli_foundation.py -q`
- YAML safe-load, sprint frontmatter hook, and `git diff --check`.

## Residual

- SP-009-5 remains `partial_skeleton` because Today/Inbox due display, timeline budget source, and SP-009 golden/DOM/enum evidence residuals are outside Newcomer Path Batch F.
- F5 PR must still run `codex_pr_full_review.sh` and thread-aware GitHub comment polling before merge.
