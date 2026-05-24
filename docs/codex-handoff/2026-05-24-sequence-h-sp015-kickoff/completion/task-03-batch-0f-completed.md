# task-03 batch 0f Completed: SP-015 Backup/Restore Regression and SecretBroker Token Negative

## status

- status: completed
- completed_at: 2026-05-24
- branch: `codex/sequence-h-sp015-kickoff-2026-05-24`
- scope: backup/restore drill regression + SecretBroker inter-agent token payload negative

## summary

Completed SP015-T07/T08:

- Added audit `correlation_id` for inter-agent audit events using message-id hash, not raw message body.
- Added DB-backed restore-drill regression covering:
  - parent / child AgentRun FK survival
  - inter_agent_messages seq/hash/consume state
  - project_agent_roles soft-delete (`deprecated_at`)
  - memory_records source FK applicable guard
  - audit_events correlation
- Added `InterAgentPayloadRejected(reason_code=...)` for sanitizer rejections.
- Added exact `inter_agent_message_token_payload` reason for SecretBroker capability-token pass-through attempts in inter-agent message payloads.
- Publish attempts with token payload now create no message, no artifact, and no AgentRunEvent; they emit a ref-only `inter_agent_message_denied` audit event without the raw token.

## files

- `backend/app/services/inter_agent/event_writer.py`
- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/sanitizer.py`
- `backend/app/services/inter_agent/__init__.py`
- `tests/db/test_backup_restore_inter_agent.py`
- `tests/security/test_secretbroker_inter_agent_token.py`
- `tests/audit/test_inter_agent_no_raw_payload.py`
- `docs/sprints/SP-015_inter_agent_communication.md`
- `docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/tasks/task-03-sp015-batch-0-inter-agent-message-core.md`
- `docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/README.md`

## self-review

See `reviews/task-03-batch-0f-self-impl-review.md`.

## verification

- PASS: `uv run ruff check backend/app/services/inter_agent tests/db/test_backup_restore_inter_agent.py tests/security/test_secretbroker_inter_agent_token.py tests/audit/test_inter_agent_no_raw_payload.py tests/inter_agent`
- PASS: `uv run mypy backend/app/services/inter_agent tests/db/test_backup_restore_inter_agent.py tests/security/test_secretbroker_inter_agent_token.py tests/audit/test_inter_agent_no_raw_payload.py tests/inter_agent`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/db/test_backup_restore_inter_agent.py tests/security/test_secretbroker_inter_agent_token.py -q`
  - result: 3 passed, 4 warnings
- PASS: `uv run ruff check backend tests migrations`
- PASS: `uv run mypy backend/app/db/models/inter_agent_message.py backend/app/schemas/inter_agent.py backend/app/services/inter_agent tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py tests/db/test_schema_introspection.py tests/db/test_backup_restore_inter_agent.py tests/security/test_secretbroker_inter_agent_token.py`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/audit/test_inter_agent_no_raw_payload.py tests/inter_agent/ tests/db/test_schema_introspection.py tests/db/test_backup_restore_inter_agent.py tests/security/test_secretbroker_inter_agent_token.py -q`
  - result: 58 passed, 88 warnings
- PASS: test DB `uv run alembic current`
  - result: `0030_sp015_inter_agent_messages (head)`
- PASS: test DB `uv run alembic downgrade 0029_sp0045_tool_registry_core`
- PASS: test DB `uv run alembic upgrade head`
- BLOCKED INFRA: `uv run alembic check` still fails because `migrations/env.py` does not provide `target_metadata`; unchanged repo infrastructure debt.

## next

Create task-03 completion summary, then proceed to task-04 SP-016 inventory / plan-only.
