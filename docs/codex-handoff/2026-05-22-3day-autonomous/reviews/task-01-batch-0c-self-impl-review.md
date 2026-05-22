# task-01 batch 0c Self-Impl-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0c policy_profile + policy_decisions trace
- protocol: `00-codex-behavior-guide.md` §3.2 Self-Impl-Review
- implementation target:
  - `migrations/versions/0027_sp014_policy_profile.py`
  - `backend/app/domain/policy/profile.py`
  - `backend/app/db/models/policy_profile.py`
  - `backend/app/services/policy/profile_resolver.py`
  - `backend/app/schemas/project.py`
  - `backend/app/repositories/project.py`
  - `tests/policy/test_policy_profile_seed.py`
  - ADR / Sprint Pack / DD-02 docs

## implemented

- Added `policy_profiles` and `policy_profile_action_effects` with exact two profiles and 14 action effect seed rows.
- Added tenant insert trigger so new tenants automatically receive canonical policy profile rows.
- Hardened `projects.policy_profile` to `not null default 'default'` with `(tenant_id, policy_profile)` composite FK.
- Extended `policy_decisions` with `policy_profile`, `profile_resolved_effect`, and `required_review_artifact_id` review_artifact FK.
- Added fail-closed profile resolver for unknown profile and missing seed rows.
- Removed caller-supplied `policy_profile` from `ProjectCreate`; repository dict payloads containing it now raise `ValueError`.
- Added seed helper for test fixtures that deliberately truncate tenants or mutate profile seed rows.
- Updated ADR-00009, SP-014 Sprint Pack, and DD-02 policy schema.

## adversarial review findings

| id | severity | category | symptom | judgment | fix |
|---|---|---|---|---|---|
| SP014-B0C-IMPL-R1-F001 | HIGH | new tenant FK | Initial migration seed protected only tenants existing during upgrade. | adopt | Added `tenants_seed_policy_profiles` trigger and test coverage through new tenant/project fixtures. |
| SP014-B0C-IMPL-R1-F002 | HIGH | server-owned-boundary | `ProjectCreate` or repository payload could still carry `policy_profile`. | adopt | `ProjectCreate` forbids extra fields; repository create/update reject `policy_profile`. |
| SP014-B0C-IMPL-R1-F003 | MEDIUM | test isolation | The missing-seed negative test deleted a canonical row and could poison later exact row tests. | adopt | Restore canonical seed in `finally`; fixture reseeds before project inserts. |
| SP014-B0C-IMPL-R1-F004 | MEDIUM | doc drift | ADR/DD docs still mixed proposed policy_profile text and old `read/search` enum. | adopt | Added accepted update section and synchronized DD-02 action_class 7 values. |
| SP014-B0C-IMPL-R1-F005 | MEDIUM | migration verification | Editing unmerged 0027 after it had been applied locally can mask trigger drift. | adopt | Recreated the local test DB before DB verification, then ran downgrade/upgrade. |

## invariant checklist

- server-owned-boundary: PASS; caller cannot set project `policy_profile` through schema or repository payload.
- 5+ source enum integrity: PASS for policy_profile IDs/effects/action classes across Literal/frozenset, DB CHECKs, migration seed, seed helper, resolver, and pytest.
- exact seed invariant: PASS; two profiles and 14 action effect rows verified.
- fail-closed invariant: PASS; unknown profile and missing seed row resolve to deny.
- Approval 4 / Tier 2 alignment: PASS; policy_decisions can bind `required_review_artifact_id` without creating approval_requests.
- raw secret / token leakage: PASS; no raw secret / capability token fields or logs added.
- tenant boundary: PASS; profile FKs are tenant-scoped and new tenant trigger prevents default-FK drift.

## verification

- `uv run ruff check backend tests`: PASS
- `uv run mypy backend`: PASS (`257 source files`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/policy/test_policy_profile_seed.py -q`: PASS (`8 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/policy/ -q`: PASS (`73 passed, 1 xfailed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/db/test_repository_layer.py tests/db/test_schema_introspection.py tests/test_seeds.py -q`: PASS (`37 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/multi_agent/ -q`: PASS (`47 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/runtime/test_agent_run_events.py tests/runtime/test_agentrun_transitions.py -q`: PASS (`51 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic downgrade -1`: PASS
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic upgrade head`: PASS
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic check`: NOT CLEAN, existing env limitation (`migrations/env.py` does not provide `target_metadata`)

## broader drift observed

`TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest $(rg -l "insert into projects" tests) -q` was run as an adversarial sweep. It failed only on pre-existing schema drift unrelated to batch 0c:

- `tests/runtime/test_artifact_immutable.py`: direct artifact INSERT omits current `artifacts.project_id not null`.
- `tests/security/test_artifact_cross_project_negative.py`: fixture references removed `agent_runs.intent`.

Carry this to task-07 or task-08; do not block batch 0c because policy_profile-specific suites and migration up/down pass.

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0
- deferred: `alembic check` infrastructure drift and two pre-existing stale test fixtures
- verdict: READY for batch 0c PR
