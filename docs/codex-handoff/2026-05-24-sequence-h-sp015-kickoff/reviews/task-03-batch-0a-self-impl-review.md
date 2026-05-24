# task-03 batch 0a Self-Impl-Review

## verdict

- task: SP-015 batch 0a schema and migration
- status: READY for batch 0b
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- unresolved MEDIUM: 0
- deferred infrastructure debt: `uv run alembic check` cannot run because `migrations/env.py` keeps `target_metadata = None` on `origin/main`.

## implementation reviewed

- `backend/app/db/models/inter_agent_message.py`
- `migrations/versions/0030_sp015_inter_agent_messages.py`
- `backend/app/db/models/__init__.py`
- `tests/inter_agent/test_12_fields_schema.py`
- `tests/db/test_schema_introspection.py`
- `docs/adr/00018_inter_agent_communication.md`
- `docs/sprints/SP-015_inter_agent_communication.md`

## adversarial findings

| id | severity | category | decision | result |
|---|---|---|---|---|
| T03-0A-R1-001 | HIGH | receiver hijack boundary | adopt | `receiver_kind` target CHECK now has three explicit fail-closed branches: direct agent_run requires `child_run_id` and no `receiver_ref`; role requires role ref and no child id; broadcast requires neither. |
| T03-0A-R1-002 | HIGH | action_class privilege boundary | adopt | Added global non-null `action_class` subset CHECK so `merge` / `deploy` cannot be smuggled on non-trusted rows. |
| T03-0A-R1-003 | MEDIUM | ADR/schema drift | adopt | ADR-00018 SQL now uses `(tenant_id, project_id, source_artifact_id)` Artifact FK, matching the implemented Artifact unique constraint. |
| T03-0A-R1-004 | MEDIUM | ADR gate lifecycle | adopt | ADR-00018 moved from `proposed` to `accepted` at SP-015 kickoff, and SP-015 moved it from `planned_adr_refs` to `adr_refs`. |
| T03-0A-R1-005 | MEDIUM | migration quality signal | defer | `alembic check` is blocked by existing `target_metadata = None`; used test DB downgrade -> upgrade -> current head plus schema introspection tests as the migration signal. |

## invariant checklist

- [x] Tenant/project boundary is present on project, AgentRun, Artifact, and unique constraints.
- [x] No raw message body column was added.
- [x] `payload_hash`, `artifact_ref`, `schema_version`, and `idempotency_key` are required.
- [x] `payload_data_class` is canonical; `data_class` was not introduced.
- [x] trusted_instruction requires approval/server-owned refs plus action class subset.
- [x] direct self-consume is rejected by DB CHECK.
- [x] receiver target shape is fail-closed per receiver kind.
- [x] migration downgrade drops indexes before the table.

## verification

```bash
uv run pytest tests/inter_agent/test_12_fields_schema.py -q
# 7 passed

uv run ruff check backend tests migrations
# All checks passed

uv run mypy backend/app/db/models/inter_agent_message.py \
  tests/inter_agent/test_12_fields_schema.py \
  tests/db/test_schema_introspection.py
# Success: no issues found in 3 source files

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
uv run alembic downgrade 0029_sp0045_tool_registry_core
# downgrade 0030 -> 0029 passed

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
uv run alembic upgrade head
# upgrade 0029 -> 0030 passed

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
uv run alembic current
# 0030_sp015_inter_agent_messages (head)

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/db/test_schema_introspection.py -q
# 23 passed, 46 warnings
```

`uv run alembic check` result:

```text
FAILED: Can't proceed with --autogenerate option; environment script migrations/env.py does not provide a MetaData object or sequence of objects to the context.
```

`migrations/env.py` is unchanged from `origin/main`, so this is not introduced by batch 0a.

## readiness gate

- CRITICAL = 0
- HIGH = 0 after adopted fixes
- Batch 0b may start.
