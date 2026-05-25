# task-18 SP-009-5 Batch F2 Plan Self Review

## Scope Reviewed

- F2 guided intake dry-run API contract plan.
- ADR-00003 extension note.
- SP-009-5 / handoff / backlog status synchronization.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| Treating F2 as a persisted onboarding state would add DB semantics without a lifecycle decision. | HIGH | adopt | F2 is response-only; persistence is deferred to a later accepted batch. |
| Adding `read_only` to canonical `ActionClass` would drift the 7-class policy taxonomy. | HIGH | adopt | `read_only` is a dry-run-only sentinel; mutating classes keep the existing `ActionClass` enum. |
| `draft_pr_requires_approval` could accidentally become an execution shortcut. | HIGH | adopt | F2 returns plan metadata only and sets all `would_create` fields to false. |
| Caller-supplied `policy_profile` could bypass server-owned policy resolution. | HIGH | adopt | Request schema forbids `policy_profile` and related ownership fields. |
| Raw first-run task text can contain secrets. | MEDIUM | adopt | Plan requires raw-secret canary rejection before response construction. |

## Invariant Checklist

- [x] No DB migration or persistence in the planning PR.
- [x] No AgentRun, ticket, approval, notification, audit, repo, provider, merge, deploy, or CLI mutation in F2.
- [x] `policy_profile` remains server-owned.
- [x] First-run mutating classes are approval-gated or denied.
- [x] `tm` remains canonical for later CLI onboarding.
- [x] Response excludes raw secrets, raw provider payloads, raw tokens, capability tokens, raw logs, and stack details.

## Verification

- passed: YAML safe-load for SP-009-5 and ADR-00003.
- passed: sprint frontmatter hook for SP-009-5.
- passed: ADR / sprint / backlog / handoff cross-reference check.
- passed: `git diff --check`.
- planned: PR Codex review baseline and delayed inline review polling.

## Residual

- F2b backend implementation was completed later in task-19.
- F3 plan-review UI remains pending.
- F4 CLI onboarding parity was closed by task-21.
