# task-03 batch 0b Completed: SP-015 Publisher and Sanitizer

## status

- status: completed
- completed_at: 2026-05-24
- branch: `codex/sequence-h-sp015-kickoff-2026-05-24`
- scope: publisher / sanitizer / tests

## summary

Implemented the first SP-015 service layer:

- Added caller-facing `InterAgentPublishRequest` with server-owned fields excluded.
- Added sanitizer pipeline with raw secret / canary rejection and server-owned claim key rejection.
- Added publisher service that validates parent/sender/direct receiver boundaries, computes `payload_data_class`, creates a non-exportable Artifact body, and writes ref-only `inter_agent_messages` metadata.
- Added parent-stream advisory transaction locking for `seq_no` / `previous_hash` chain generation.
- Added unit and DB-backed tests for caller-field exclusion, receiver target shape, secret rejection, message chain creation, and sender boundary rejection.

## files

- `backend/app/schemas/inter_agent.py`
- `backend/app/schemas/__init__.py`
- `backend/app/services/inter_agent/__init__.py`
- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/sanitizer.py`
- `tests/inter_agent/test_publisher_service.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## self-review

See `reviews/task-03-batch-0b-self-impl-review.md`.

## verification

- PASS: `uv run pytest tests/inter_agent/test_publisher_service.py -q`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/inter_agent/test_publisher_service.py -q`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/inter_agent/ -q`
- PASS: `uv run ruff check backend tests migrations`
- PASS: `uv run mypy backend/app/db/models/inter_agent_message.py backend/app/schemas/inter_agent.py backend/app/services/inter_agent tests/inter_agent tests/db/test_schema_introspection.py`
- PASS: test DB `uv run alembic current` -> `0030_sp015_inter_agent_messages (head)`
- BLOCKED INFRA: `uv run alembic check` fails because `migrations/env.py` has `target_metadata = None` on `origin/main`.

## next

Proceed to task-03 batch 0c:
consumer service, atomic consume SQL, receiver eligibility, replay / hijack denial,
and concurrent consume test.
