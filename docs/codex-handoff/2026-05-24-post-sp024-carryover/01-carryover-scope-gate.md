# Carry-over Scope Gate

## Gate Decision

Before writing SP-008 / SP-009 / SP-007 implementation code, Codex must prove that the target residual is still current. The proof must cite current files and tests, not only old Sprint Pack checkboxes.

## Why This Gate Exists

SP-008, SP-009, and SP-007 were created before later accepted work landed. Their status fields are intentionally not all `completed`, but their unchecked task lists are not reliable enough as direct implementation instructions.

The risky parts are:

- GitHub App installation token handling,
- SecretBroker broker-mediated operation boundaries,
- RepoProxy branch / commit / Draft PR mutation,
- webhook HMAC and replay handling,
- AgentRunEvent append-only event contracts,
- API route and frontend wiring that may have been superseded by SP-012 / SP-016,
- repo-external trusted hook wrapper changes on the local machine.

## Required Reconciliation Evidence

Each carry-over task must produce:

1. **Residual table**: old BL / current evidence / still-needed decision.
2. **Adopt-defer-reject table**: every old checkbox is classified.
3. **Boundary declaration**: DB migration, API contract, secret, external exposure, and runner/repo mutation impact.
4. **Verification plan**: exact ruff, mypy, pytest, frontend, Alembic, and review commands.
5. **PR review plan**: how inline GitHub review comments and `codex_pr_full_review.sh` findings are checked and closed.

## Stop Conditions

Stop and write `STOPPED.md` if any of these occur:

- a residual task requires new GitHub App permissions not covered by ADR-00011,
- raw installation token or capability token exposure is needed to make the design work,
- a migration cannot be downgraded cleanly,
- SP-009 requires new write mutations before the backend contract is accepted,
- SP-007 requires editing repo-external trusted wrapper files without explicit user confirmation for that machine-local state,
- three consecutive review or verification attempts fail for the same cause.

## Merge Gate

Admin bypass merge is acceptable only when all local gates pass, review threads are clean, Actions failure is confirmed as quota/no-steps, and the PR description documents:

- scope,
- verification,
- self-review findings and disposition,
- known deferred work,
- why the change is safe to merge without Actions.
