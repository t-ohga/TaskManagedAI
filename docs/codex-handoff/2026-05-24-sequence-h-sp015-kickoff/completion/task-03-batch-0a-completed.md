# task-03 batch 0a Completed: SP-015 Schema and Migration

## status

- status: completed
- completed_at: 2026-05-24
- branch: `codex/sequence-h-sp015-kickoff-2026-05-24`
- scope: schema / migration / tests only

## summary

Implemented the SP-015 inter-agent message persistence baseline:

- Added `inter_agent_messages` ORM model.
- Added Alembic revision `0030_sp015_inter_agent_messages`.
- Added static schema tests for exact columns, receiver kinds, CHECKs, project-scoped unique constraints, FKs, and migration source drift.
- Added `inter_agent_messages` to DB schema introspection tenant-scoped table coverage.
- Accepted ADR-00018 at SP-015 kickoff and synchronized SP-015 frontmatter.

## files

- `backend/app/db/models/inter_agent_message.py`
- `backend/app/db/models/__init__.py`
- `migrations/versions/0030_sp015_inter_agent_messages.py`
- `tests/inter_agent/test_12_fields_schema.py`
- `tests/db/test_schema_introspection.py`
- `docs/adr/00018_inter_agent_communication.md`
- `docs/sprints/SP-015_inter_agent_communication.md`

## self-review

See `reviews/task-03-batch-0a-self-impl-review.md`.

## verification

- PASS: `uv run pytest tests/inter_agent/test_12_fields_schema.py -q`
- PASS: `uv run ruff check backend tests migrations`
- PASS: `uv run mypy backend/app/db/models/inter_agent_message.py tests/inter_agent/test_12_fields_schema.py tests/db/test_schema_introspection.py`
- PASS: test DB `alembic downgrade 0029_sp0045_tool_registry_core`
- PASS: test DB `alembic upgrade head`
- PASS: test DB `alembic current` -> `0030_sp015_inter_agent_messages (head)`
- PASS: test DB `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/db/test_schema_introspection.py -q`
- BLOCKED INFRA: `uv run alembic check` fails because `migrations/env.py` has `target_metadata = None` on `origin/main`.

## next

Proceed to task-03 batch 0b:
publisher service, sanitizer pipeline, `payload_data_class` derivation,
secret canary scan, `seq_no` / `previous_hash`, and no raw secret exposure.
