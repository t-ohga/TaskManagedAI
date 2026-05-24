# Current State (2026-05-24)

## Verified Repository State

- Remote `main` was verified at `60556b3661d3e06a4d085c731787e3379fe15f10` after PRs #219-#228.
- Open GitHub PR list was empty after PR #228 merge.
- Root worktree was clean, and `git stash list` returned no entries. Root `main` was fast-forwarded to remote after the autonomous PR sequence; no stash recovery is required.
- The SSH remote rejected `git fetch` with `Permission denied (publickey)`. HTTPS fetch worked. Use HTTPS fetch or `gh` API when local refs are stale.

## SP-024 Result

SP-024 is completed and merged through four PRs:

| PR | scope | result |
|---|---|---|
| #210 | autonomy policy engine matrix | merged |
| #211 | autonomy policy trace ledger | merged |
| #212 | autonomy settings surface | merged |
| #213 | regression closeout and Sprint Pack completion | merged |

All delayed inline review checks returned no actionable review threads. GitHub Actions jobs were not usable because of monthly quota exhaustion; local ruff, mypy, pytest, frontend typecheck/lint/vitest, DB tests, and Alembic upgrade/downgrade verification were used instead.

`uv run alembic check` still fails because `migrations/env.py` does not expose `target_metadata` for autogenerate. This is existing infrastructure debt, not introduced by SP-024. Alembic upgrade/downgrade/current verification passed.

## Stale Candidate Correction

The earlier next-candidate list named SP-014 batch 1+, SP-015 batch 0, and SP-016 batch 0. Repository state now shows:

| Sprint | current status | implication |
|---|---|---|
| SP-014 orchestrator agent | `completed` | do not re-open from stale list |
| SP-015 inter-agent communication | `completed` | do not re-open from stale list |
| SP-016 UI CLI parity | `completed` | do not re-open from stale list |
| SP-024 autonomy policy profiles | `completed` | runtime dogfooding enablement remains separate opt-in work |

## Remaining Non-Completed Sprint Packs

| Sprint | current status | current interpretation |
|---|---|---|
| SP-007 runner sandbox | `done_with_phase5_defer` | runner/security core is complete; Phase 5 plan + repo-only helpers are ready, but external trust-root install remains approval-gated |
| SP-008 GitHub App / RepoProxy | `partial_skeleton` | #219-#223 completed service-boundary batches; real GitHub transport, live ref re-fetch, deployment SOPS resolver, and external worker/API adoption remain |
| SP-009 P0 UI Pack | `partial_skeleton` | #224/#225 completed route reconciliation and contract/redaction tests; golden E2E, DOM secret scan, PayloadDataClass/future AuditEventType registry drift, and SP-009-5 implementation remain |
| SP-009-5 P0.1 UI deferred surfaces | `partial_skeleton` | Batch A `/today`, Batch B `/timeline`, and Batch C decision packet hash visibility are implemented; Batch D notification triage contract plan is ready; Newcomer Path and `request_revision` remain |
| SP-000 bootstrap | `ready` | old bootstrap metadata; treat as backlog hygiene, not feature implementation |

## Next Work Boundary

The safest next work is one of:

- SP-009-5 continuation: implement notification triage D1/D2 from the accepted plan; `request_revision` still requires ADR/API/state-machine planning; Newcomer Path is P0.1 polish.
- SP-008 residual implementation that does not require new GitHub App permissions or raw token exposure.
- SP-007 Phase 5C only after explicit machine-local trust-root approval.

Do not reopen stale SP-014/SP-015/SP-016 candidate work; those Sprint Packs are completed.
