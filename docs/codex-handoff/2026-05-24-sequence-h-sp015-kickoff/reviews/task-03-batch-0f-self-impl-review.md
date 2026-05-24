# task-03 batch 0f Self-Impl-Review

## verdict

- task: SP-015 batch 0f backup/restore regression and SecretBroker token negative
- status: READY for task-03 closeout
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- unresolved MEDIUM: 0

## implementation reviewed

- `backend/app/services/inter_agent/event_writer.py`
- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/sanitizer.py`
- `backend/app/services/inter_agent/__init__.py`
- `tests/db/test_backup_restore_inter_agent.py`
- `tests/security/test_secretbroker_inter_agent_token.py`
- `tests/audit/test_inter_agent_no_raw_payload.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## adversarial findings

| id | severity | category | decision | result |
|---|---|---|---|---|
| T03-0F-R1-001 | HIGH | audit correlation leaks raw message id | adopt | Audit `correlation_id` uses SHA-256 of message id / publish idempotency key, not raw message body or raw token. |
| T03-0F-R1-002 | HIGH | SecretBroker token pass-through | adopt | Sanitizer detects token-payload keys before raw scan and returns exact `inter_agent_message_token_payload`; publisher emits ref-only denial audit. |
| T03-0F-R1-003 | MEDIUM | denial path creates partial message artifacts | adopt | Token payload test asserts zero `inter_agent_messages`, zero `artifacts`, and zero `agent_run_events`. |
| T03-0F-R1-004 | MEDIUM | restore drill is documentation-only | adopt | `tests/db/test_backup_restore_inter_agent.py` verifies the five SP015-T07 checks against a live migrated PostgreSQL test DB. |
| T03-0F-R1-005 | LOW | memory_records not yet present | defer | Test includes an applicable guard: current schema documents absence; if table appears, it must expose source-related FK columns. SP-018 owns the memory backend. |

## invariant checklist

- [x] parent/child AgentRun relationship survives restore-style verification.
- [x] message seq/hash/consume state is query-verifiable after publish + consume.
- [x] project role soft-delete marker is preserved.
- [x] memory_records source FK is verified when applicable and explicitly absent otherwise.
- [x] audit sent/consumed rows share a non-raw correlation id.
- [x] SecretBroker capability token cannot be passed through inter-agent message payloads.
- [x] denial audit does not contain raw token or token key.
- [x] denial path does not persist a message, artifact, or run event.

## verification

```bash
uv run ruff check backend/app/services/inter_agent \
  tests/db/test_backup_restore_inter_agent.py \
  tests/security/test_secretbroker_inter_agent_token.py \
  tests/audit/test_inter_agent_no_raw_payload.py \
  tests/inter_agent
# All checks passed

uv run mypy backend/app/services/inter_agent \
  tests/db/test_backup_restore_inter_agent.py \
  tests/security/test_secretbroker_inter_agent_token.py \
  tests/audit/test_inter_agent_no_raw_payload.py \
  tests/inter_agent
# Success: no issues found in 12 source files

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/db/test_backup_restore_inter_agent.py \
  tests/security/test_secretbroker_inter_agent_token.py -q
# 3 passed, 4 warnings

uv run ruff check backend tests migrations
# All checks passed

uv run mypy backend/app/db/models/inter_agent_message.py \
  backend/app/schemas/inter_agent.py \
  backend/app/services/inter_agent \
  tests/inter_agent \
  tests/audit/test_inter_agent_no_raw_payload.py \
  tests/db/test_schema_introspection.py \
  tests/db/test_backup_restore_inter_agent.py \
  tests/security/test_secretbroker_inter_agent_token.py
# Success: no issues found in 15 source files

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/audit/test_inter_agent_no_raw_payload.py \
  tests/inter_agent/ \
  tests/db/test_schema_introspection.py \
  tests/db/test_backup_restore_inter_agent.py \
  tests/security/test_secretbroker_inter_agent_token.py -q
# 58 passed, 88 warnings

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
- Batch 0 complete summary may be created.
