# task-03 plan: SP-007 Phase 5 Hook Trust Boundary

## Status

- plan_status: `PHASE_5A_5B_HELPERS_READY`
- prepared_at: `2026-05-24`
- source_sprint: `docs/sprints/SP-007_runner_sandbox.md`
- source_adr: `docs/adr/00012_hook_trust_boundary.md`
- implementation_scope: docs and in-repo scaffolding first; repo-external trust root switch requires explicit user approval.

## Current State

SP-007 is `done_with_phase5_defer`. Runner sandbox, forbidden path, dangerous command, resource cap, env scrub, public AC-HARD-05/06 fixtures, and runner mutation gateway scaffolding are already recorded as shipped.

The remaining Phase 5 work is BL-0082, BL-0083, and BL-0084:

| item | current state | required close condition |
|---|---|---|
| BL-0082 repo-external trusted wrapper | not installed | `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` validates repo hooks before dispatch |
| BL-0083 trusted state move | not moved | Bash snapshot state is under `~/.claude-trusted-state/taskmanagedai/`, not repo-local `.claude/.hook-state/` |
| BL-0084 sha256 manifest | not generated as trust root | manifest covers dispatcher and child hooks and fails closed on mismatch |

ADR-00012 is accepted as of 2026-05-22, but acceptance does not mean the machine-local wrapper was installed. The implementation readiness gate stays closed until the external files, rollback backups, and self-tests are explicitly approved and executed.

## Phase 5A/5B Helper Evidence (2026-05-24)

Repository-only helper work has been prepared:

- `scripts/regenerate-hook-manifest.sh` generates a deterministic `.claude/hooks/**/*.sh` manifest to `--stdout` or an explicit `--output` path only.
- `scripts/verify-hook-trust-root.sh` verifies wrapper presence, permissions, manifest drift, trusted state writability, and wrapper `--self-test` without mutating the trust root.
- `.claude/hooks/system/pretool-bash-snapshot.sh` and `.claude/hooks/system/posttool-bash-file-dispatcher.sh` honor `TASKMANAGEDAI_HOOK_STATE_DIR`, preserving the repo-local default until Phase 5C.
- `tests/harness/test_hook_trust_boundary.py` covers temp trust roots, manifest mismatch, non-executable wrapper rejection, external state dir use, and missing state dir fail-closed behavior.

No repo-external trust root, dotfiles, or settings switch is performed by Phase 5A/5B.

## Scope Split

### 1. Repository Documentation Updates

These are safe to land immediately.

- Add this plan as the current Phase 5 entry point.
- Update the SP-007 Review section with a 2026-05-24 current-state note:
  - ADR-00012 is now accepted.
  - BL-0082/BL-0083/BL-0084 remain unimplemented.
  - No repo-external files were created or modified by the planning PR.
- Update the carry-over matrix so task-02 batch C is completed and task-03 points to this plan.
- Keep SP-007 status as `done_with_phase5_defer` until wrapper self-test, manifest mismatch test, trusted-state test, and rollback test all pass.

### 2. Testable In-Repo Helper Code

These can be implemented in a follow-up PR before any machine-local switch.

| artifact | purpose | constraints |
|---|---|---|
| `scripts/regenerate-hook-manifest.sh` | deterministically hash `.claude/hooks/**/*.sh` into a manifest candidate | writes to an explicit output path only; does not touch `~/.claude-trusted` unless a later approved install command passes that path |
| `scripts/verify-hook-trust-root.sh` | verify wrapper presence, permissions, manifest match, state dir writability, and wrapper self-test | read-only by default; exits non-zero on mismatch |
| `tests/harness/test_hook_trust_boundary.py` | temp-home tests for manifest match/mismatch, missing child hook, non-executable hook, and state dir selection | must use a temporary HOME and temporary repo fixture; never read or write the real user trust root |
| hook state env support | update pre/post Bash snapshot scripts to honor `TASKMANAGEDAI_HOOK_STATE_DIR` | default remains current repo-local path until wrapper is activated |

Implementation note: do not point `.codex/hooks.json` at a Claude-only wrapper unless the command works with `PWD` and no `$CLAUDE_PROJECT_DIR`. Codex hook commands must remain executable shell commands in the Codex runtime.

### 3. Repo-External File Creation Or Modification

These require explicit approval at implementation time, even though the user has authorized broad autonomous work, because this is a host-level trust root.

| path | operation | required precondition |
|---|---|---|
| `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` | create or replace wrapper, mode `700` | reviewed wrapper source, backup dir prepared |
| `~/.claude-trusted/taskmanagedai-hook-manifest.sha256` | create or replace manifest, mode `600` | manifest generated from current repo HEAD and reviewed |
| `~/.claude-trusted-state/taskmanagedai/` | create trusted state dir, mode `700` | temp-home tests pass |
| `.claude/settings.json` | switch Claude Bash pre/post hooks to wrapper entrypoint | current settings backed up and wrapper `--self-test` passes |

The first external install should be done as a separate PR/operator step after the in-repo helper PR is merged. It should not be bundled with unrelated Sprint work.

### 4. User-Machine Rollback Steps

Rollback must be prepared before the settings switch.

1. Save backups under `~/.claude-trusted/backups/taskmanagedai/<timestamp>/`:
   - `.claude/settings.json`
   - `taskmanagedai-hook-wrapper.sh`
   - `taskmanagedai-hook-manifest.sha256`
2. If hooks fail closed unexpectedly, restore `.claude/settings.json` to the direct repo hook commands:
   - PreToolUse Bash: `"$CLAUDE_PROJECT_DIR"/.claude/hooks/system/block-git-add-bulk.sh`
   - PreToolUse Bash: `"$CLAUDE_PROJECT_DIR"/.claude/hooks/system/pretool-bash-snapshot.sh`
   - PostToolUse Bash: `"$CLAUDE_PROJECT_DIR"/.claude/hooks/system/posttool-bash-file-dispatcher.sh`
3. Unset `TASKMANAGEDAI_HOOK_STATE_DIR` for the session if set externally.
4. Move, do not delete, `~/.claude-trusted-state/taskmanagedai/` to the backup directory for inspection.
5. Run the existing direct-hook smoke checks before resuming:
   - `bash -n .claude/hooks/system/pretool-bash-snapshot.sh`
   - `bash -n .claude/hooks/system/posttool-bash-file-dispatcher.sh`
   - `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-007_runner_sandbox.md`

## Implementation Sequence

### Phase 5A: Docs And Tests Only

- Land this plan. Completed 2026-05-24.
- Add temp-home tests and helper scripts. Completed 2026-05-24.
- Verify helper scripts do not mutate user home by default. Completed 2026-05-24.
- Keep `.claude/settings.json`, `.codex/hooks.json`, and user-global trust roots unchanged.

### Phase 5B: Wrapper Candidate

- Add wrapper verification support as in-repo helper scripts. Completed 2026-05-24.
- Test verification flow in a temporary trust root with:
  - manifest match -> dispatch allowed,
  - manifest mismatch -> exit 2,
  - non-executable wrapper -> exit 2,
  - trusted state dir missing -> exit 2.
- Confirm no raw secret, token, or local absolute user-private path is committed except documented target paths.

### Phase 5C: Approved Machine-Local Install

- Request explicit approval for the operator step.
- Install wrapper, manifest, and state dir with restrictive modes.
- Switch `.claude/settings.json` only after `verify-hook-trust-root.sh` passes.
- Run mismatch and rollback drills immediately after the switch.

### Phase 5D: Closeout

- Update SP-007 BL-0082/BL-0083/BL-0084 to completed.
- Keep ADR-00012 accepted; add implementation evidence and rollback evidence.
- Change SP-007 status from `done_with_phase5_defer` to `done` only after all closeout evidence exists.

## Verification Plan

For this planning PR:

```bash
ruby -e 'require "yaml"; require "date"; YAML.safe_load(File.read("docs/sprints/SP-007_runner_sandbox.md"), permitted_classes: [Date], aliases: true)'
.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-007_runner_sandbox.md
git diff --check
```

For the follow-up helper-code PR:

```bash
bash -n scripts/regenerate-hook-manifest.sh
bash -n scripts/verify-hook-trust-root.sh
uv run pytest tests/harness/test_hook_trust_boundary.py -q
uv run ruff check tests/harness/test_hook_trust_boundary.py
PYTHONPATH=cli uv run mypy tests/harness/test_hook_trust_boundary.py
git diff --check
```

For the approved machine-local install:

```bash
bash scripts/verify-hook-trust-root.sh --trust-root "$HOME/.claude-trusted" --state-root "$HOME/.claude-trusted-state/taskmanagedai"
bash "$HOME/.claude-trusted/taskmanagedai-hook-wrapper.sh" --self-test
```

## Explicit Non-Goals

- Do not silently edit `~/.claude-trusted`, `~/.claude-trusted-state`, dotfiles, or user-global Claude/Codex configuration.
- Do not switch `.claude/settings.json` in the same PR as this plan.
- Do not make `.codex/hooks.json` depend on `$CLAUDE_PROJECT_DIR`.
- Do not mark SP-007 done until PH4-F-001 and PH4-F-002 are tested against the wrapper, not merely documented.
