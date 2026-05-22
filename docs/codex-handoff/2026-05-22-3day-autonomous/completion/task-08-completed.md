# task-08 完了報告 (2026-05-22)

## summary

- task: Documentation drift fix
- start: 2026-05-22 JST
- end: 2026-05-22 JST
- scope: AgentRun event_type 28→37 wording、SP-014 completion frontmatter、
  SP-012-9 historical/current state split、rules/checklist source paths、
  task-08 review/completion artifacts
- branch: `docs/task-08-drift-fix-2026-05-22`

## completed changes

- SP-014 Sprint Pack frontmatter now reflects completed status.
- AgentRun event_type current state is documented as 28 baseline + 9 SP-014
  additions = 37.
- ADR-00004 now treats old Phase D/E numbering as historical and SP-014 28→37
  as current accepted implementation.
- `.claude/rules/agentrun-state-machine.md` now points to actual implemented
  source paths.
- SP-012-9 now distinguishes PR #109 kickoff snapshot from the current
  completed wiring state.
- Handoff task/checklist docs now use current migration names and 28→37 wording.

## Codex finding 採否判定

- HIGH:
  - finding: SP-014 frontmatter still said `ready`.
  - judgment: adopt. Set `completed` + `completed_at`.
- HIGH:
  - finding: old event_type wording could trigger wrong implementation.
  - judgment: adopt. Synced current target to 28→37.
- MEDIUM:
  - finding: placeholder source paths (`00NN_*`) remained in active docs.
  - judgment: adopt. Replaced with actual files.
- MEDIUM:
  - finding: SP-012-9 mixed kickoff-state text with completion state.
  - judgment: adopt. Labeled historical snapshot and current closure.
- MEDIUM:
  - finding: repo-wide markdownlint debt remains outside semantic drift scope.
  - judgment: defer. Keep this PR focused on correctness drift.

## defer / carry-over

- T08-DEFER-001: legacy markdownlint style cleanup for old Sprint Packs.
- T08-DEFER-002: `repo_pr_merged` event_type / formal `time_to_merge` metric
  remains SP-018+ carry-over from task-01 batch 0f.

## blocker

- No CRITICAL / HIGH / MEDIUM blocker remains for task-08 semantic docs scope.

## verification

- [x] event_type drift grep reviewed
- [x] SP-012-9 stale route/path grep clean for current-state falsehoods
- [x] `git diff --check`
- [x] new review/completion artifacts markdownlint clean

## Claude verification 依頼項目

1. Historical 22→25 Sprint 5.5 notes in ADR-00004 are intentionally preserved.
2. SP-014 completed frontmatter should be accepted as the Sprint Pack source of
   truth after PR #145-#150.
3. Legacy markdownlint style cleanup can remain out of scope unless a dedicated
   formatting pass is desired.
