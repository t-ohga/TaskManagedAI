# task-03 batch 0c Completed: SP-015 Consumer Atomic Consume

## status

- status: completed
- completed_at: 2026-05-24
- branch: `codex/sequence-h-sp015-kickoff-2026-05-24`
- scope: consumer service / atomic consume / replay-hijack tests

## summary

Implemented the SP-015 consume side:

- Added `InterAgentConsumeRequest`.
- Added `InterAgentConsumerService` with atomic `UPDATE ... RETURNING`.
- Added receiver eligibility SQL for direct child, role, and broadcast.
- Added previous hash chain validation before consume.
- Added denial reason classification for already consumed, expired, sender self-consume, previous hash mismatch, and receiver ineligible cases.
- Added DB-backed tests including the required 100 concurrent consume case.

## files

- `backend/app/schemas/inter_agent.py`
- `backend/app/schemas/__init__.py`
- `backend/app/services/inter_agent/__init__.py`
- `backend/app/services/inter_agent/consumer.py`
- `tests/inter_agent/test_consumer_service.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## self-review

See `reviews/task-03-batch-0c-self-impl-review.md`.

## verification

- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/inter_agent/test_consumer_service.py -q`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/inter_agent/ tests/db/test_schema_introspection.py -q`
- PASS: `uv run ruff check backend tests migrations`
- PASS: `uv run mypy backend/app/db/models/inter_agent_message.py backend/app/schemas/inter_agent.py backend/app/services/inter_agent tests/inter_agent tests/db/test_schema_introspection.py`
- BLOCKED INFRA: `uv run alembic check` fails because `migrations/env.py` has `target_metadata = None` on `origin/main`.

## next

Proceed to task-03 batch 0d:
trusted_instruction defense, service guard, Pydantic guard, and approval 4-binding negative cases.
