# task-01 batch 0b Self-Impl-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0b review_artifacts 4 重防御
- protocol: `00-codex-behavior-guide.md` §3.2 Self-Impl-Review
- implementation target:
  - `migrations/versions/0026_sp014_review_artifacts.py`
  - `backend/app/db/models/review_artifact.py`
  - `backend/app/domain/review_artifact.py`
  - `backend/app/schemas/review_artifact.py`
  - `backend/app/services/orchestrator/review_artifact_guard.py`
  - `tests/multi_agent/test_review_artifact_4_defense.py`

## implemented

- Added `review_artifacts` table with:
  - action_class DB CHECK limited to `task_write/repo_write/pr_open/secret_access`
  - `review_verdict` semantic split from Approval (`pass/fail/needs_revision`)
  - requester/reviewer self-review DB CHECK
  - project-bound FKs for parent/requester/reviewer runs and both artifact refs
  - policy input binding columns: `target_artifact_hash`, `policy_version`, `provider_request_fingerprint_hash`
- Added domain Literal/frozenset sources for review artifact action classes and verdicts.
- Added Pydantic create schema with `extra="forbid"`, hash format validation, enum validation, and requester/reviewer separation.
- Added service guard `validate_review_artifact_for_action_class()`:
  - tenant/project context enforced server-side
  - reviewer role resolved from `agent_runs`, not caller input
  - requester/reviewer parent boundary checked
  - target/review artifacts loaded within the same tenant/project boundary
  - target hash + action_class + policy_version + provider_request_fingerprint_hash matched against the review target policy input
  - review artifact must be `trust_level='validated_artifact'`
- Added contract tests for DB CHECK, DB cross-project FK, Pydantic extra/enum rejection, service hash/action binding rejection, reviewer role rejection, requester/reviewer identity rejection, and cross-project service rejection.

## adversarial review findings

| id | severity | category | symptom | judgment | fix |
|---|---|---|---|---|---|
| SP014-B0B-IMPL-R1-F001 | HIGH | project boundary | ADR SQL snippet still allowed tenant-only artifact refs if copied literally. | adopt | Migration/model use `(tenant_id, project_id, id)` artifact FKs and direct DB FK negative test. |
| SP014-B0B-IMPL-R1-F002 | HIGH | policy binding | A table with only `review_target_artifact_id` would not prove the reviewed policy input matched the Policy Engine input. | adopt | Added hash/version/fingerprint/action columns and service guard payload binding checks. |
| SP014-B0B-IMPL-R1-F003 | MEDIUM | server-owned-boundary | Exposing tenant/project or reviewer role in the caller schema would let caller-provided metadata influence review validity. | adopt | Pydantic schema excludes tenant/project/role fields; service queries `agent_runs` and `artifacts` server-side. |
| SP014-B0B-IMPL-R1-F004 | MEDIUM | weak test coverage | Initial DB coverage could pass with only the action-class CHECK and miss cross-project artifact FK drift. | adopt | Added `test_db_fk_rejects_cross_project_target_artifact`. |
| SP014-B0B-IMPL-R1-F005 | LOW | verification isolation | Running two DB pytest commands concurrently against the same test database caused reset/migration races and false failures. | adopt | Re-ran on a dedicated temporary Postgres at `127.0.0.1:55432` sequentially. |

## invariant checklist

- server-owned-boundary: PASS; caller schema has no tenant/project/role fields and `tenant_id` extra field is rejected.
- 5+ source enum integrity: PASS for the new review_artifact action subset and verdict sources (Literal + frozenset + Pydantic + DB CHECK + pytest).
- AgentRun 16 status invariant: PASS; no AgentRun status changes.
- blocked_reason 3 value invariant: PASS; no blocked_reason changes.
- raw secret / token leakage: PASS; no secret material or capability token columns/log paths introduced.
- approval 4 binding analogue: PASS; artifact hash + policy_version + provider_request_fingerprint_hash + action_class are enforced in service guard.
- self-review prevention: PASS; DB + Pydantic + service reject requester/reviewer identity.
- cross-project artifact boundary: PASS; DB FK + service query + contract test.

## verification

- `uv run ruff check backend tests`: PASS
- `uv run mypy backend`: PASS (`253 source files`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/multi_agent/test_review_artifact_4_defense.py -q`: PASS (`9 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/multi_agent/ -q`: PASS (`47 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/runtime/test_agent_run_events.py tests/runtime/test_agentrun_transitions.py -q`: PASS (`51 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`: PASS
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic check`: NOT CLEAN, existing env limitation (`migrations/env.py` does not provide `target_metadata`)

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0
- deferred: `alembic check` infrastructure drift only, same debt as batch 0a
- verdict: READY for batch 0b PR
