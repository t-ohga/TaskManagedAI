# task-03 batch 0d Completed: SP-015 Trusted Instruction Defense

## status

- status: completed
- completed_at: 2026-05-24
- branch: `codex/sequence-h-sp015-kickoff-2026-05-24`
- scope: trusted_instruction service guard / approval 4-binding tests

## summary

Implemented trusted_instruction promotion without opening a caller-supplied trust path:

- Added internal `TrustedInstructionGrant`.
- Added `publish_trusted_instruction`.
- Verified approved approval, human decider, source artifact project boundary, and artifact_hash / policy_version / provider_request_fingerprint / action_class equality.
- Rejected merge/deploy and non-approved approval reuse.
- Added DB-backed success and negative tests.

## files

- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/__init__.py`
- `tests/inter_agent/test_trusted_instruction.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## self-review

See `reviews/task-03-batch-0d-self-impl-review.md`.

## verification

- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/inter_agent/test_trusted_instruction.py -q`
- PASS: DB-backed `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/inter_agent/ tests/db/test_schema_introspection.py -q`
- PASS: `uv run ruff check backend tests migrations`
- PASS: `uv run mypy backend/app/db/models/inter_agent_message.py backend/app/schemas/inter_agent.py backend/app/services/inter_agent tests/inter_agent tests/db/test_schema_introspection.py`
- BLOCKED INFRA: `uv run alembic check` fails because `migrations/env.py` has `target_metadata = None` on `origin/main`.

## next

Proceed to task-03 batch 0e:
audit_events sent / consumed / denied payload schema, AgentRunEvent ref events,
and no raw payload helpers.
