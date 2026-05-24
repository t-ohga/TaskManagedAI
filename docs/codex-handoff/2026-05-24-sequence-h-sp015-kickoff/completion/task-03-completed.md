# task-03 Completed: SP-015 Batch 0 Inter-Agent Message Core

## status

- status: completed
- completed_at: 2026-05-24
- branch: `codex/sequence-h-sp015-kickoff-2026-05-24`
- scope: SP-015 batch 0a-0f

## batch summary

| batch | status | scope |
|---|---|---|
| 0a | completed | `inter_agent_messages` schema / migration / DB introspection |
| 0b | completed | publisher service / sanitizer / payload_data_class server-owned calculation |
| 0c | completed | atomic consume / receiver eligibility / replay-hijack defense / 100 concurrent consume |
| 0d | completed | trusted_instruction defense / approval target 4-binding |
| 0e | completed | audit_events sent/consumed/denied + AgentRunEvent refs + no raw payload |
| 0f | completed | backup/restore regression + SecretBroker inter-agent token payload negative |

## must_ship closure

- [x] SP015-T01 inter_agent_messages table + exact column set + FK / CHECK / index + downgrade path
- [x] SP015-T02 publisher service + sanitizer pipeline + server-owned payload_data_class
- [x] SP015-T03 consumer service + atomic consume SQL + receiver eligibility + replay/hijack defense
- [x] SP015-T04 trusted_instruction 4-layer defense + approval target 4-binding negative cases
- [x] SP015-T05 audit_events 3 required payloads + no raw message body regression
- [x] SP015-T06 AgentRunEvent sent_ref / consumed_ref append + current event_type 37 reuse
- [x] SP015-T07 backup/restore 5-check regression
- [x] SP015-T08 SecretBroker inter-agent token payload negative

## files

- `backend/app/db/models/inter_agent_message.py`
- `migrations/versions/0030_sp015_inter_agent_messages.py`
- `backend/app/schemas/inter_agent.py`
- `backend/app/services/inter_agent/`
- `tests/inter_agent/`
- `tests/audit/test_inter_agent_no_raw_payload.py`
- `tests/db/test_backup_restore_inter_agent.py`
- `tests/security/test_secretbroker_inter_agent_token.py`
- `tests/db/test_schema_introspection.py`
- `docs/adr/00018_inter_agent_communication.md`
- `docs/sprints/SP-015_inter_agent_communication.md`

## verification

- PASS: `uv run ruff check backend tests migrations`
- PASS: `uv run mypy backend/app/db/models/inter_agent_message.py backend/app/schemas/inter_agent.py backend/app/services/inter_agent tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py tests/db/test_schema_introspection.py tests/db/test_backup_restore_inter_agent.py tests/security/test_secretbroker_inter_agent_token.py`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/audit/test_inter_agent_no_raw_payload.py tests/inter_agent/ tests/db/test_schema_introspection.py tests/db/test_backup_restore_inter_agent.py tests/security/test_secretbroker_inter_agent_token.py -q`
  - result: 58 passed, 88 warnings
- PASS: test DB `uv run alembic current`
  - result: `0030_sp015_inter_agent_messages (head)`
- PASS: test DB `uv run alembic downgrade 0029_sp0045_tool_registry_core`
- PASS: test DB `uv run alembic upgrade head`
- BLOCKED INFRA: `uv run alembic check` still fails because `migrations/env.py` does not provide `target_metadata`; unchanged repo infrastructure debt.

## residuals

- `alembic check` infrastructure debt remains outside SP-015 batch 0 scope.
- `Codex review helper actionable 0` is pending until a PR exists.
- SP-016 / SP-017 / SP-018 implementation remains deferred; task-04 is plan-only inventory.

## next

Proceed to task-04 SP-016 inventory / plan-only.
