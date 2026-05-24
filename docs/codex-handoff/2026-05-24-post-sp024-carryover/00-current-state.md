# Current State (2026-05-24)

## Verified Repository State

- Remote `main` was verified at `2cc7b6b5d5fa760ce671549efb7db7a0d54d0adc` after SP-024 closeout.
- Open GitHub PR list was empty.
- Root worktree was clean, and `git stash list` returned no entries.
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
| SP-007 runner sandbox | `done_with_phase5_defer` | implementation is mostly complete; Phase 5 repo-external hook trust work remains intentionally deferred |
| SP-008 GitHub App / RepoProxy | `partial_skeleton` | high-risk residual remains; exact residual must be reconciled before code |
| SP-009 P0 UI Pack | `skeleton_pending_backend` | likely stale after later UI/API work; reconcile before implementation |
| SP-000 bootstrap | `ready` | old bootstrap metadata; treat as backlog hygiene, not feature implementation |

## Next Work Boundary

The safest next work is a docs-only reconciliation PR, then a small implementation PR. Starting with SP-008 code without reconciliation risks duplicating later Sprint work or reopening GitHub App secret/repository mutation boundaries with stale assumptions.
