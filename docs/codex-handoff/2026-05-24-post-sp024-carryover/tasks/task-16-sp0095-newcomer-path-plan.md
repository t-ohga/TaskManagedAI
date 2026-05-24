# task-16 SP-009-5 Batch F0 Newcomer Path Plan

## Scope

Plan SP-009-5 Batch F before any Newcomer Path code, API, schema, CLI, or runtime mutation work.

The Newcomer Path is the first-use flow for an operator who has not internalized TaskManagedAI's project, repo, policy, autonomy, approval, and evidence boundaries. The plan must keep the first experience safe: the initial path can diagnose and explain, but it cannot start a mutating AgentRun.

## Source Requirements

- `docs/設計検討/設計問題点改善点/2026-05-14_第三回_UIUX自律ワークフロー整合レビュー.md` DI-28.
- `docs/設計検討/設計問題点改善点/2026-05-14_改善アクションバックログ.md` A-UX2-02.
- `docs/sprints/SP-009_p0_ui_pack.md` Q-E.5 / D-006.1.
- `docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md` Batch F.
- `docs/adr/00015_ui_cli_parity.md` and `docs/cli/README.md` for the current CLI canonical name.
- `docs/adr/00025_autonomy_policy_profiles.md` for L0-L3 onboarding safety boundaries.

## Boundary

- Do not add a route, component, API endpoint, DB table, migration, CLI command, or AgentRun transition in this planning batch.
- Do not use the stale `tmai` command name from early design notes as canonical. Current repo truth is `tm`.
- Do not introduce persisted onboarding state until a separate API/schema plan selects the storage model and verification.
- Do not add `AgentRunEvent` or status enum values without a separate 5+ source enum PR.
- Do not let the first-use path create a mutating run, repo write, PR, secret access, merge, deploy, or provider call.

## Planned Direction

Use Batch F0 as the contract plan, then implement Batch F in small PRs:

| batch | scope | mutation boundary |
|---|---|---|
| F0 | docs-only contract plan | no code/schema/runtime changes |
| F1 | read-only `/onboarding` checklist and safe navigation | existing APIs only; no persisted state |
| F2 | guided intake dry-run contract | no mutating AgentRun; API/schema gate before code |
| F3 | plan-review surface | approve/request revision/ask why only against accepted backend contract |
| F4 | CLI onboarding parity notes and tests | `tm` canonical only; mutating commands fail-closed |
| F5 | closeout and route parity | browser/Vitest/contract verification; docs synchronized |

## DoD

- [x] Newcomer Path source requirements are traced.
- [x] `tmai` vs `tm` drift is resolved in favor of repo-canonical `tm`.
- [x] F1 read-only UI work is separated from F2+ API/schema/runtime gates.
- [x] First-use mutating run start is explicitly blocked.
- [x] Verification plan covers docs, future UI, future API, future CLI, and GitHub review loops.

## Verification

- `ruby -e 'require "yaml"; require "date"; YAML.safe_load(File.read("docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md"), permitted_classes: [Date], aliases: true); puts "ok"'`
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh` for SP-009-5.
- `rg -n "task-16|Newcomer Path|Batch F|tm run|tmai" docs/codex-handoff/2026-05-24-post-sp024-carryover docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md docs/cli/README.md docs/adr/00015_ui_cli_parity.md`
- `git diff --check`

## Residual

- F1 route implementation remains next.
- F2+ may require an ADR/API contract PR before backend or DB changes.
- CLI command implementation remains tied to SP-016 / ADR-00015 parity contracts, not this docs-only plan.
