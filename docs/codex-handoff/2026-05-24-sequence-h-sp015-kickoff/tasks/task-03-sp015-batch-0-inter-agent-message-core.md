# task-03: SP-015 Batch 0 Inter-Agent Message Core

## status

task-02 is `READY`.

- batch 0a: completed (schema / migration / DB verification).
- batch 0b: completed (publisher / sanitizer / server-owned classification).
- batch 0c: completed (atomic consume / receiver eligibility / replay-hijack defense).
- batch 0d: completed (trusted_instruction approval 4-binding defense).
- batch 0e: completed (audit events / AgentRunEvent refs / no raw payload regression).
- batch 0f: completed (backup/restore regression / SecretBroker token payload negative).

## scope

SP-015 の batch 0 実装。
task-02 の plan review 結果に従い、small PR で段階実装する。

## proposed batch split

### batch 0a: schema and migration

- `inter_agent_messages` table.
- exact column set from ADR-00018 §1.
- Treat `12 fields` as historical shorthand, not a literal column count.
- FK / CHECK / index.
- unique constraints include `tenant_id`, `project_id`, and `parent_run_id`.
- downgrade path.
- schema tests.

### batch 0b: publisher service

- sanitizer pipeline.
- payload_data_class.
- secret canary scan.
- seq_no / previous_hash.
- no raw secret exposure.

### batch 0c: consumer service

- atomic consume SQL.
- receiver eligibility.
- replay / hijack deny.
- 100 concurrent consume test.

### batch 0d: trusted_instruction defense

- DB CHECK.
- service guard.
- Pydantic guard.
- tests.
- approval 4 binding negative cases.

### batch 0e: audit and AgentRunEvent refs

- sent / consumed / denied audit events.
- AgentRunEvent ref events.
- no raw payload helpers.
- enum exact set tests.

### batch 0f: backup / restore and SecretBroker negative

- backup / restore drill update.
- SecretBroker inter-agent token payload negative.
- completion docs and Sprint Pack review.

## invariant

- No caller-supplied tenant / project / actor.
- No raw secret.
- No raw message body in audit / AgentRunEvent.
- Atomic consume only.
- Receiver eligibility enforced in SQL or equivalent fail-closed guard.
- Event enums exact across all sources.

## verification

```bash
uv run ruff check backend tests
uv run mypy backend
uv run pytest tests/inter_agent/ tests/audit/ tests/security/ tests/db/ \
  tests/agent_runtime/test_event_type_enum.py -q
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

`uv run alembic check` is required unless the known
`migrations/env.py target_metadata` infrastructure debt still blocks it.
If blocked, record the exact reason and use fresh DB upgrade / downgrade /
upgrade as the migration quality signal.

## outputs

- implementation PRs per batch.
- `reviews/task-03-batch-*-self-impl-review.md`.
- `completion/task-03-batch-*-completed.md` for each batch.
- `completion/task-03-completed.md` after all SP-015 batch 0 slices finish.

## DoD checklist

- [x] task-02 READY result exists.
- [x] all batches completed or unfinished batches are explicit defer.
- [x] all SP015-T01-T08 must_ship items completed.
- [x] local verify recorded.
- [ ] Codex review helper actionable 0 for every code PR.
- [x] Sprint Pack review updated.
