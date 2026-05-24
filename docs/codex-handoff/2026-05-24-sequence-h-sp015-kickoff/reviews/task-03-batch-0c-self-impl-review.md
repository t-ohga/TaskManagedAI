# task-03 batch 0c Self-Impl-Review

## verdict

- task: SP-015 batch 0c consumer service, atomic consume, replay/hijack defense
- status: READY for batch 0d
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- unresolved MEDIUM: 0
- deferred infrastructure debt: `uv run alembic check` remains blocked by `migrations/env.py target_metadata = None`.

## implementation reviewed

- `backend/app/schemas/inter_agent.py`
- `backend/app/services/inter_agent/consumer.py`
- `backend/app/services/inter_agent/__init__.py`
- `backend/app/schemas/__init__.py`
- `tests/inter_agent/test_consumer_service.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## adversarial findings

| id | severity | category | decision | result |
|---|---|---|---|---|
| T03-0C-R1-001 | HIGH | non-atomic consume race | adopt | Consume uses one `UPDATE ... WHERE ... RETURNING` statement; 100 concurrent attempts yield exactly 1 success. |
| T03-0C-R1-002 | HIGH | receiver hijack | adopt | WHERE clause includes receiver_kind-specific eligibility and child membership under the same tenant/project/parent_run. |
| T03-0C-R1-003 | HIGH | replay / chain tamper | adopt | WHERE clause verifies `seq_no=1 previous_hash is null` or previous row `payload_hash` matches `previous_hash`; mismatch denies consume. |
| T03-0C-R1-004 | MEDIUM | denial observability | adopt | Denial classifier returns `already_consumed`, `expired`, `sender_self_consume`, `previous_hash_mismatch`, or `receiver_ineligible`. |
| T03-0C-R1-005 | MEDIUM | timezone bind bug | adopt | Expired classification now compares by DB row predicate instead of binding Python datetime to `now()`. |

## invariant checklist

- [x] Consume is atomic and idempotent via DB row update.
- [x] Already consumed messages cannot be consumed again.
- [x] Expired messages are denied.
- [x] Sender cannot consume its own message.
- [x] Direct receiver must match `child_run_id` and be under `parent_run_id`.
- [x] Role receiver requires consumer role match under the same parent.
- [x] Broadcast receiver requires consumer child membership under the same parent.
- [x] Previous hash chain mismatch is denied before marking consumed.
- [x] 100 concurrent consume attempts produce exactly one success.

## verification

```bash
TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/inter_agent/test_consumer_service.py -q
# 8 passed, 14 warnings

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/inter_agent/ tests/db/test_schema_introspection.py -q
# 43 passed, 64 warnings

uv run ruff check backend tests migrations
# All checks passed

uv run mypy backend/app/db/models/inter_agent_message.py \
  backend/app/schemas/inter_agent.py \
  backend/app/services/inter_agent \
  tests/inter_agent \
  tests/db/test_schema_introspection.py
# Success: no issues found in 10 source files
```

## readiness gate

- CRITICAL = 0
- HIGH = 0 after adopted fixes
- Batch 0d may start.
