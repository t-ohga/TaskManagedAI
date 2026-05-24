# task-16 SP-009-5 Batch F0 Self Review

## Scope Reviewed

- Newcomer Path source requirements from DI-28 / A-UX2-02.
- SP-009-5 Batch F planning boundaries.
- ADR-00015 / docs/cli canonical CLI naming.
- ADR-00025 autonomy and human-required action invariants.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| Early DI-28 wording names `tmai`, while the accepted repo contract makes `tm` canonical. | HIGH | adopt | F0 plan explicitly resolves the drift in favor of `tm` and blocks stale `tmai` usage for implementation. |
| A newcomer "start" button could accidentally become a mutating AgentRun shortcut. | HIGH | adopt | F1 is read-only only, and F2+ require API/schema/runtime gates before any execution path. |
| Persisting onboarding state in F1 would create DB/API semantics without a storage decision. | MEDIUM | adopt | F1 treats the DI-28 state model as UI progression only; persistence is deferred to a separate plan. |
| Guided intake could let caller-supplied `allowed_action_class` become an effective policy decision. | MEDIUM | adopt | F2 says the field is only an upper-bound request and the server resolves effective action/approval. |
| Plan-review approval could implicitly start execution. | MEDIUM | adopt | F3 blocks implicit AgentRun start unless backend approval/runtime handoff exists. |
| P0 backlog and priority matrix still said request_revision E2/E3 were unimplemented, which would mislead the next batch. | MEDIUM | adopt | Updated `docs/実装計画/P0_バックログ.md` and `02-task-priority-matrix.md` for E1-E3 completion and added Newcomer Path tracking. |

## Invariant Checklist

- [x] No code, route, API, DB, migration, CLI, or runtime change in F0.
- [x] No status enum or AgentRunEvent enum expansion.
- [x] No first-run mutating AgentRun start.
- [x] No caller-supplied `policy_profile`.
- [x] `secret_access`, `merge`, `deploy`, and `provider_call` remain human-required.
- [x] Raw secrets, raw provider payloads, raw logs, and capability tokens are not exposed.
- [x] `tm` is canonical; stale `tmai` wording is not propagated into the plan.
- [x] F1 read-only UI is separated from F2 API/schema/runtime work.

## Verification

- passed: Sprint Pack frontmatter YAML safe load.
- passed: Sprint Pack frontmatter hook.
- passed: cross-reference `rg` for task-16 / Newcomer Path / Batch F / `tm` / `tmai`.
- passed: P0 backlog / roadmap drift repair for SP-009-5 carry-over.
- passed: `git diff --check`.

## Residual

- F1 route implementation remains next.
- F2 dry-run API contract remains unimplemented.
- CLI onboarding commands remain documentation candidates until SP-016 parity work accepts them.
