# task-03 batch 0e Completed: SP-015 Audit Events and AgentRunEvent Refs

## status

- status: completed
- completed_at: 2026-05-24
- branch: `codex/sequence-h-sp015-kickoff-2026-05-24`
- scope: inter-agent audit events, AgentRunEvent refs, no raw payload regression

## summary

Implemented SP015-T05/T06:

- Added `InterAgentEventWriter`.
- Publish success now appends `inter_agent_message_sent` audit event and `inter_agent_message_sent_ref` AgentRunEvent.
- Consume success now appends `inter_agent_message_consumed` audit event and `inter_agent_message_consumed_ref` AgentRunEvent.
- Consume denial now appends `inter_agent_message_denied` audit event.
- Audit consumed / denied message ids are stored as SHA-256 hashes.
- Audit/timeline payloads are ref-only and writer-guarded against raw message body keys (`payload`, `body`, `content`, `artifact`, etc.).
- Added DB-backed regression coverage for sent / consumed / denied audit payloads, sent_ref / consumed_ref AgentRunEvent payloads, and raw body sentinel non-leakage.

## files

- `backend/app/services/inter_agent/event_writer.py`
- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/consumer.py`
- `backend/app/services/inter_agent/__init__.py`
- `tests/audit/test_inter_agent_no_raw_payload.py`
- `tests/inter_agent/test_consumer_service.py`
- `tests/inter_agent/test_publisher_service.py`
- `tests/inter_agent/test_trusted_instruction.py`
- `docs/sprints/SP-015_inter_agent_communication.md`
- `docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/tasks/task-03-sp015-batch-0-inter-agent-message-core.md`

## self-review

See `reviews/task-03-batch-0e-self-impl-review.md`.

## verification

- PASS: `uv run ruff check backend/app/services/inter_agent tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py`
- PASS: `uv run mypy backend/app/services/inter_agent tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/audit/test_inter_agent_no_raw_payload.py tests/inter_agent/ -q`
  - result: 32 passed, 38 warnings
- PASS: `uv run ruff check backend tests migrations`
- PASS: `uv run mypy backend/app/db/models/inter_agent_message.py backend/app/schemas/inter_agent.py backend/app/services/inter_agent tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py tests/db/test_schema_introspection.py`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/audit/test_inter_agent_no_raw_payload.py tests/inter_agent/ tests/db/test_schema_introspection.py -q`
  - result: 55 passed, 84 warnings
- PASS: test DB `uv run alembic current`
  - result: `0030_sp015_inter_agent_messages (head)`
- PASS: test DB `uv run alembic downgrade 0029_sp0045_tool_registry_core`
- PASS: test DB `uv run alembic upgrade head`
- BLOCKED INFRA: `uv run alembic check` still fails because `migrations/env.py` does not provide `target_metadata`; this is unchanged repo infrastructure debt.

## next

Proceed to task-03 batch 0f:
backup/restore drill extension and SecretBroker inter-agent token payload negative case.
