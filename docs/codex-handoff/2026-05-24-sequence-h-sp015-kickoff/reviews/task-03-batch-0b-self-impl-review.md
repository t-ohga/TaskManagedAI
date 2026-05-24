# task-03 batch 0b Self-Impl-Review

## verdict

- task: SP-015 batch 0b publisher service and sanitizer pipeline
- status: READY for batch 0c
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- unresolved MEDIUM: 0
- deferred infrastructure debt: `uv run alembic check` remains blocked by `migrations/env.py target_metadata = None`.

## implementation reviewed

- `backend/app/schemas/inter_agent.py`
- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/sanitizer.py`
- `backend/app/services/inter_agent/__init__.py`
- `backend/app/schemas/__init__.py`
- `tests/inter_agent/test_publisher_service.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## adversarial findings

| id | severity | category | decision | result |
|---|---|---|---|---|
| T03-0B-R1-001 | HIGH | caller-supplied trust promotion | adopt | Removed `trust_level` from `InterAgentPublishRequest`; batch 0b publisher always persists `untrusted_content`. trusted_instruction promotion remains batch 0d with approval 4-binding. |
| T03-0B-R1-002 | HIGH | server-owned self-claim | adopt | Sanitizer now rejects payload keys that claim `tenant_id`, `project_id`, `payload_data_class`, `trust_level`, approval refs, or `action_class`. |
| T03-0B-R1-003 | MEDIUM | data-class boundary | adopt | `payload_data_class` is absent from caller schema and nested classifier input; service computes it through `classify_payload_data_class`. |
| T03-0B-R1-004 | MEDIUM | message body leakage | adopt | Message body is stored as an Artifact; `inter_agent_messages` stores `artifact_ref` + `payload_hash` only. Artifact is `exportable=false`. |
| T03-0B-R1-005 | MEDIUM | seq race | adopt | Publisher takes a parent-stream PostgreSQL advisory transaction lock before computing `seq_no` / `previous_hash`. |

## invariant checklist

- [x] No caller-facing `tenant_id`, `project_id`, `sender_actor_id`, `payload_data_class`, or `trust_level`.
- [x] Raw secret / canary patterns rejected before artifact persistence.
- [x] Server-owned claim keys rejected inside structured payload.
- [x] `payload_data_class` computed server-side from classifier signals.
- [x] Active `sanitizer_policy_versions` row is required.
- [x] Sender and direct receiver must be children of the same parent run.
- [x] Sender cannot target itself as direct child receiver.
- [x] Message chain uses monotonic `seq_no` and previous message `payload_hash`.

## verification

```bash
uv run pytest tests/inter_agent/test_publisher_service.py -q
# 3 passed, 2 skipped without DB env

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/inter_agent/test_publisher_service.py -q
# 5 passed, 4 warnings

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/inter_agent/ -q
# 12 passed, 4 warnings

uv run ruff check backend tests migrations
# All checks passed

uv run mypy backend/app/db/models/inter_agent_message.py \
  backend/app/schemas/inter_agent.py \
  backend/app/services/inter_agent \
  tests/inter_agent \
  tests/db/test_schema_introspection.py
# Success: no issues found in 8 source files

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
uv run alembic current
# 0030_sp015_inter_agent_messages (head)
```

`uv run alembic check` remains blocked by unchanged repo infrastructure:

```text
FAILED: Can't proceed with --autogenerate option; environment script migrations/env.py does not provide a MetaData object or sequence of objects to the context.
```

## readiness gate

- CRITICAL = 0
- HIGH = 0 after adopted fixes
- Batch 0c may start.
