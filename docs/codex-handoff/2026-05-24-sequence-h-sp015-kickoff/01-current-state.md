# Current State

## repository

- source of truth: `origin/main`
- current main merge commit:
  `dac63d83f6546deab39234f6a090b6dff33e93f9`
- latest closeout PR: #172
- open PR at handoff creation: none
- hosted GitHub Actions: monthly quota blocked

## previous handoff status

`docs/codex-handoff/2026-05-22-3day-autonomous/` is complete on `main`.

- task completed: 8 / 8
- merged PR: #145-#171
- closeout PR: #172
- Codex inline residual: 18 findings, all adopt fixed in #171
- known CRITICAL / HIGH after closeout: none

## completed Sprint / Pack state

- SP-013: completed
- SP-014: completed
- SP-012-8: completed
- SP-012-9: completed
- SP-022-1: completed
- SP-0045: completed
- SP-011-5: completed

## next Sprint state

### SP-015 inter-agent communication

- status: `draft`
- type: `heavy`
- prerequisite:
  SP-013 foundation and SP-014 orchestrator are complete.
- implementation target:
  SP-014 publisher stub becomes real inter-agent message implementation.
- risk:
  DB schema, atomic consume, replay/hijack defense, audit payload,
  SecretBroker negative case, ADR update.
- known plan drift to resolve:
  SP-015 still contains older `event_type 22→31` / event 28/29 wording.
  SP-014 completed with event_type 28→37, so task-02 must reconcile the
  SP-015 / ADR-00004 event source plan before implementation.

### SP-016 UI CLI parity

- status: `draft`
- type: `heavy`
- prerequisite:
  SP-015 message backend should be fixed before message-related CLI parity.
- allowed in this handoff:
  inventory / plan-only.
- not allowed in this handoff before SP-015:
  CLI capability token implementation, parity command implementation.

## local checkout warning

The root checkout may be stale or contain unrelated local changes.
Codex must work from a clean `origin/main` worktree and must not commit
unrelated local diffs from the root checkout.

## carry-over from previous completion report

- SP014-CARRY-001:
  `repo_pr_merged` event_type and formal `time_to_merge` metric remain
  ADR-00004 / SP-018+ scope.
- SP014-CARRY-002:
  final `citation_coverage` attribution needs adopted_artifacts link table.
- SP014-CARRY-003:
  full remote adapter / Codex app-server / Claude SDK adapter remains
  ADR-00013 proposed/full integration scope.
- SP012-9-CARRY-001:
  admin page mutations and export remain SP-018+ scope.
- SP022-1-CARRY-001:
  Phase 7b Mac to VPS migration drill remains user/operator-timed.
- INFRA-CARRY-001:
  `uv run alembic check` remains blocked by existing
  `migrations/env.py target_metadata` infrastructure debt unless fixed
  separately.
- INFRA-CARRY-002:
  hosted GitHub Actions are monthly-quota blocked.
