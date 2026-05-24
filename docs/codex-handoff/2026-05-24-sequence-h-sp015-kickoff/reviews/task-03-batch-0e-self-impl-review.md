# task-03 batch 0e Self-Impl-Review

## verdict

- task: SP-015 batch 0e audit events and AgentRunEvent refs
- status: READY for batch 0f
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- unresolved MEDIUM: 0

## implementation reviewed

- `backend/app/services/inter_agent/event_writer.py`
- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/consumer.py`
- `backend/app/services/inter_agent/__init__.py`
- `tests/audit/test_inter_agent_no_raw_payload.py`
- `tests/inter_agent/test_consumer_service.py`
- `tests/inter_agent/test_publisher_service.py`
- `tests/inter_agent/test_trusted_instruction.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## adversarial findings

| id | severity | category | decision | result |
|---|---|---|---|---|
| T03-0E-R1-001 | HIGH | raw message leakage | adopt | Writer rejects raw body keys (`payload`, `body`, `content`, `artifact`, etc.); DB-backed test confirms raw sentinel is absent from audit and run event payloads. |
| T03-0E-R1-002 | HIGH | audit id leakage | adopt | `inter_agent_message_consumed` / `denied` store hashed message ids, not raw UUIDs. |
| T03-0E-R1-003 | MEDIUM | disconnected implementation | adopt | Publisher and consumer now call the writer directly, so audit/timeline emission is not test-only. |
| T03-0E-R1-004 | MEDIUM | enum drift | adopt | Existing ADR-00004 event type set already contains `inter_agent_message_sent_ref` / `consumed_ref`; no new enum added. |
| T03-0E-R1-005 | MEDIUM | denial observability gap | adopt | Consume denial writes `inter_agent_message_denied` audit event with denial reason and ref-only message metadata when available. |

## invariant checklist

- [x] sent audit event includes required ADR-00018 fields and no message body.
- [x] consumed audit event includes required ADR-00018 fields and hashed message id.
- [x] denied audit event includes attempted message id hash, seq_no, denial_reason, and no message body.
- [x] AgentRunEvent sent_ref / consumed_ref payloads are ref-only.
- [x] raw secret scanner remains active through repository append boundaries.
- [x] raw message body keys are rejected before audit/timeline append.
- [x] publish / consume services emit events inside the same transaction as the message mutation.
- [x] caller-facing schemas still cannot supply audit or trust metadata.

## verification

```bash
uv run ruff check backend/app/services/inter_agent tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py
# All checks passed

uv run mypy backend/app/services/inter_agent tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py
# Success: no issues found in 10 source files

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/audit/test_inter_agent_no_raw_payload.py tests/inter_agent/ -q
# 32 passed, 38 warnings

uv run ruff check backend tests migrations
# All checks passed

uv run mypy backend/app/db/models/inter_agent_message.py \
  backend/app/schemas/inter_agent.py \
  backend/app/services/inter_agent \
  tests/inter_agent \
  tests/audit/test_inter_agent_no_raw_payload.py \
  tests/db/test_schema_introspection.py
# Success: no issues found in 13 source files

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/audit/test_inter_agent_no_raw_payload.py \
  tests/inter_agent/ \
  tests/db/test_schema_introspection.py -q
# 55 passed, 84 warnings

TASKMANAGEDAI_ENVIRONMENT=test TASKMANAGEDAI_DATABASE_URL=<local test db> \
  uv run alembic current
# 0030_sp015_inter_agent_messages (head)

TASKMANAGEDAI_ENVIRONMENT=test TASKMANAGEDAI_DATABASE_URL=<local test db> \
  uv run alembic downgrade 0029_sp0045_tool_registry_core
# PASS

TASKMANAGEDAI_ENVIRONMENT=test TASKMANAGEDAI_DATABASE_URL=<local test db> \
  uv run alembic upgrade head
# PASS

TASKMANAGEDAI_ENVIRONMENT=test TASKMANAGEDAI_DATABASE_URL=<local test db> \
  uv run alembic check
# BLOCKED INFRA: migrations/env.py does not provide target_metadata
```

## readiness gate

- CRITICAL = 0
- HIGH = 0 after adopted fixes
- Batch 0f may start.
